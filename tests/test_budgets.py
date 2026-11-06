import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.budgets import ProjectBudget, create_budget_router, seed_initial_budget
from app.db import Base, Member, Project, User, get_db, make_engine


@pytest.fixture
def service(tmp_path):
    engine = make_engine('sqlite:///' + str(tmp_path / 'budget.db'))
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions.begin() as db:
        owner, outsider = User(telegram_user_id=1), User(telegram_user_id=2)
        db.add_all([owner, outsider]); db.flush()
        project = Project(name='Tamaddun', slug='tamaddun', owner_id=owner.id)
        db.add(project); db.flush()
        db.add(Member(project_id=project.id, user_id=owner.id, role='owner'))
        seed_initial_budget(db, project)
        owner_id, outsider_id, project_id = owner.id, outsider.id, project.id

    def override_db():
        with sessions() as db:
            yield db

    def current_user(x_user: str = Header()):
        with sessions() as db:
            return db.get(User, x_user)

    def permitted(db, project_id, user, roles=None):
        member = db.get(Member, (project_id, user.id))
        if member is None:
            raise HTTPException(404)
        if roles and member.role not in roles:
            raise HTTPException(403)
        return db.get(Project, project_id)

    app = FastAPI()
    app.dependency_overrides[get_db] = override_db
    app.include_router(create_budget_router(current_user, permitted))
    with TestClient(app) as client:
        yield client, sessions, owner_id, outsider_id, project_id
    engine.dispose()


def test_budget_is_preference_and_owner_only(service):
    client, sessions, owner, outsider, project = service
    path = f'/api/v1/projects/{project}/budget'
    response = client.get(path, headers={'x-user': owner})
    assert response.status_code == 200
    assert response.json()['monthly_limit_cents'] == 3000
    assert response.json()['limit_enforced'] is False
    assert response.json()['paid_generation_enabled'] is False
    assert response.json()['actual_spend_cents'] is None
    assert client.get(path, headers={'x-user': outsider}).status_code == 404
    assert client.put(path, headers={'x-user': outsider}, json={'monthly_limit_cents': 1}).status_code == 404
    with sessions.begin() as db:
        db.add(Member(project_id=project, user_id=outsider, role='viewer'))
    assert client.get(path, headers={'x-user': outsider}).status_code == 200
    assert client.put(path, headers={'x-user': outsider}, json={'monthly_limit_cents': 1}).status_code == 403
    assert client.put(path, headers={'x-user': owner}, json={'monthly_limit_cents': -1}).status_code == 422
    assert client.put(path, headers={'x-user': owner}, json={'monthly_limit_cents': True}).status_code == 422
    assert client.put(path, headers={'x-user': owner}, json={'monthly_limit_cents': 2500}).status_code == 200
    with sessions() as db:
        assert db.get(ProjectBudget, project).monthly_limit_cents == 2500
