"""FastAPI service for authenticated, project-scoped marketing workflows."""
import os
import logging
from contextlib import asynccontextmanager
from typing import Annotated
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.auth import issue_session, verify_init_data, verify_session
from app.db import Base, Brand, Member, Project, User, engine, get_db
from app.budgets import create_budget_router, seed_initial_budget


def owner_id() -> int:
    try:
        value = int(os.environ["OWNER_TELEGRAM_ID"])
        if value <= 0:
            raise ValueError()
        return value
    except (KeyError, ValueError):
        raise RuntimeError("OWNER_TELEGRAM_ID must be a positive Telegram user ID")


@asynccontextmanager
async def lifespan(app: FastAPI):
    owner_id()
    if not (os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN")):
        raise RuntimeError("TELEGRAM_BOT_TOKEN or BOT_TOKEN is required")
    if len(os.getenv("SESSION_SECRET", "")) < 32:
        raise RuntimeError("SESSION_SECRET must contain at least 32 characters")
    Base.metadata.create_all(engine)
    yield


# httpx request URLs contain the Telegram bot token.
logging.getLogger("httpx").setLevel(logging.WARNING)
app = FastAPI(title="AI Marketing Agency", version="0.1.0", lifespan=lifespan)
DB = Annotated[Session, Depends(get_db)]


class AuthRequest(BaseModel):
    init_data: str = Field(min_length=1, max_length=16384)


class ProjectInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class BrandInput(BaseModel):
    description: str = Field(default="", max_length=10000)
    audience: str = Field(default="", max_length=5000)
    tone: str = Field(default="", max_length=5000)
    language: str = Field(default="uz", min_length=2, max_length=20)
    constraints: str = Field(default="", max_length=5000)


def current_user(db: DB, authorization: Annotated[str | None, Header()] = None) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Authentication required")
    user = db.get(User, verify_session(authorization[7:]))
    if not user:
        raise HTTPException(401, "Invalid session")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def permitted(db: Session, project_id: str, user: User, roles=None) -> Project:
    member = db.get(Member, (project_id, user.id))
    project = db.get(Project, project_id)
    if not project or not member:
        raise HTTPException(404, "Project not found")
    if roles and member.role not in roles:
        raise HTTPException(403, "Insufficient project permissions")
    return project


def project_json(project: Project, role: str):
    return {"id": project.id, "name": project.name, "slug": project.slug, "role": role}


@app.get("/health/live")
def live():
    return {"status": "ok"}


@app.get("/health/ready")
def ready(db: DB):
    db.execute(select(1))
    return {"status": "ready"}


@app.post("/api/v1/auth/telegram")
def telegram_auth(data: AuthRequest, db: DB):
    telegram_id = verify_init_data(data.init_data)
    user = db.scalar(select(User).where(User.telegram_user_id == telegram_id))
    if not user:
        if telegram_id != owner_id():
            raise HTTPException(403, "User is not authorized")
        user = User(telegram_user_id=telegram_id)
        db.add(user)
        db.flush()
        for slug, name, description, audience in [
            ("oqi", "O‘qi", "Ta'lim platformasi va onlayn kurslar orqali yangi kasblarni o'rgatish.", "Yoshlar va talabalar"),
            ("yordamchi-ai", "Yordamchi AI", "Kichik va o‘rta bizneslar uchun sun'iy intellekt yordamchisi va avtomatlashtirish.", "Tadbirkorlar"),
            ("tamaddun", "Tamaddun", "Talabalarga maqola yozish bo‘yicha xizmat taklifini takomillashtirish.", "Talabalar"),
        ]:
            project = Project(name=name, slug=slug, owner_id=user.id)
            db.add(project)
            db.flush()
            seed_initial_budget(db, project)
            db.add_all([Member(project_id=project.id, user_id=user.id, role="owner"), Brand(project_id=project.id, description=description, audience=audience)])
        db.commit()
    return {"access_token": issue_session(user.id), "token_type": "bearer", "expires_in": 3600}


@app.get("/api/v1/me")
def me(user: CurrentUser):
    return {"id": user.id, "telegram_user_id": user.telegram_user_id}


@app.get("/api/v1/projects")
def list_projects(user: CurrentUser, db: DB):
    rows = db.execute(select(Project, Member.role).join(Member, Member.project_id == Project.id).where(Member.user_id == user.id)).all()
    return [project_json(p, role) for p, role in rows]


@app.post("/api/v1/projects", status_code=201)
def create_project(data: ProjectInput, user: CurrentUser, db: DB):
    if user.telegram_user_id != owner_id():
        raise HTTPException(403, "Only the owner can create projects")
    project = Project(name=data.name, slug=data.slug, owner_id=user.id)
    db.add(project)
    try:
        db.flush()
        db.add_all([Member(project_id=project.id, user_id=user.id, role="owner"), Brand(project_id=project.id)])
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Project slug already exists")
    return project_json(project, "owner")


@app.get("/api/v1/projects/{project_id}")
def get_project(project_id: str, user: CurrentUser, db: DB):
    project = permitted(db, project_id, user)
    return project_json(project, db.get(Member, (project_id, user.id)).role)


@app.get("/api/v1/projects/{project_id}/brand")
def get_brand(project_id: str, user: CurrentUser, db: DB):
    permitted(db, project_id, user)
    brand = db.get(Brand, project_id)
    if not brand:
        raise HTTPException(404, "Brand profile not found")
    return {field: getattr(brand, field) for field in BrandInput.model_fields}


@app.put("/api/v1/projects/{project_id}/brand")
def put_brand(project_id: str, data: BrandInput, user: CurrentUser, db: DB):
    permitted(db, project_id, user, {"owner", "admin", "editor"})
    brand = db.get(Brand, project_id)
    if not brand:
        brand = Brand(project_id=project_id)
        db.add(brand)
    for key, value in data.model_dump().items():
        setattr(brand, key, value)
    db.commit()
    return {field: getattr(brand, field) for field in BrandInput.model_fields}


@app.post("/webhooks/telegram/{opaque_path}")
async def telegram_webhook(opaque_path: str, update: dict, db: DB, x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None):
    import hmac
    import httpx
    from app.bot import handle_telegram_webhook

    expected_path = os.getenv("TELEGRAM_WEBHOOK_PATH", "")
    webhook_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    if not expected_path or not webhook_secret:
        raise HTTPException(503, "Telegram webhook is not configured")
    if not hmac.compare_digest(opaque_path.encode(), expected_path.encode()):
        raise HTTPException(404, "Not found")

    async def projects():
        owner = db.scalar(select(User).where(User.telegram_user_id == owner_id()))
        if not owner:
            return []
        return list(db.scalars(select(Project.name).join(Member, Member.project_id == Project.id).where(Member.user_id == owner.id)))

    async def send(chat_id, message):
        token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat_id, "text": message})
                response.raise_for_status()
                if not response.json().get("ok"):
                    raise ValueError("Telegram rejected request")
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, "Telegram request failed") from None

    status = await handle_telegram_webhook(update, x_telegram_bot_api_secret_token, webhook_secret, owner_id(), projects, send)
    if status != 200:
        raise HTTPException(status, "Telegram webhook rejected")
    return {"ok": True}

# Register project-scoped content tables and routes before application startup.
from app.content_api import create_content_router
app.include_router(create_content_router(current_user, permitted))
app.include_router(create_budget_router(current_user, permitted))

from pathlib import Path
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

_static_dir = Path(__file__).resolve().parent / 'static'
app.mount('/static', StaticFiles(directory=_static_dir), name='static')

@app.get('/', include_in_schema=False)
def mini_app():
    return FileResponse(_static_dir / 'index.html', headers={'Cache-Control': 'no-store'})
