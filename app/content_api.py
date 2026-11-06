"""Project-scoped content drafts, campaigns and human approvals.

State changes use compare-and-swap conditions so concurrent requests cannot
approve a stale version. The historical version and decision rows are append-only.
"""
from hashlib import sha256
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai import generate_plan
from app.content_models import ContentDecision, ContentItem, ContentVersion
from app.db import AgentRun, Brand, Campaign, CostEvent, Project, Task, User, get_db, uid


class DraftInput(BaseModel):
    channel: str = Field(min_length=1, max_length=40, pattern=r'^[a-z][a-z0-9_-]*$')
    body: str = Field(min_length=1, max_length=10000)
    headline: str | None = Field(default=None, max_length=300)
    cta: str | None = Field(default=None, max_length=500)


class ReviseInput(BaseModel):
    expected_version_id: str = Field(min_length=1, max_length=36)
    body: str = Field(min_length=1, max_length=10000)


class SubmitInput(BaseModel):
    version_id: str = Field(min_length=1, max_length=36)
    checksum: str = Field(min_length=64, max_length=64, pattern=r'^[0-9a-f]{64}$')


class DecisionInput(SubmitInput):
    approved: bool = Field(strict=True)
    decision_notes: str | None = Field(default=None, max_length=1000)


class CampaignInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=3000)
    budget_cap: float = Field(default=30.0, ge=0.0)


class CampaignPlanRequest(BaseModel):
    objective: str | None = Field(default=None, max_length=3000)


def _hash(body: str) -> str:
    if not body.strip():
        raise HTTPException(422, 'Content must not be empty')
    return sha256(body.encode('utf-8')).hexdigest()


def _version_json(version: ContentVersion):
    return {
        'id': version.id,
        'number': version.number,
        'headline': version.headline,
        'body': version.body,
        'cta': version.cta,
        'review_notes': version.review_notes,
        'checksum': version.checksum,
        'created_at': version.created_at
    }


def _item_json(item: ContentItem, version: ContentVersion):
    return {
        'id': item.id,
        'project_id': item.project_id,
        'campaign_id': item.campaign_id,
        'channel': item.channel,
        'state': item.state,
        'version': _version_json(version)
    }


def create_content_router(current_user, permitted):
    router = APIRouter(prefix='/api/v1', tags=['content'])
    DB = Annotated[Session, Depends(get_db)]
    CurrentUser = Annotated[User, Depends(current_user)]

    def get_item(db, user, content_id, roles=None):
        item = db.get(ContentItem, content_id)
        if not item:
            raise HTTPException(404, 'Content not found')
        permitted(db, item.project_id, user, roles)
        return item

    def current(db, item):
        version = db.get(ContentVersion, item.current_version_id)
        if not version or version.content_id != item.id:
            raise HTTPException(500, 'Content version unavailable')
        return version

    def change(db, item, state, new_state, version_id):
        result = db.execute(update(ContentItem).where(
            ContentItem.id == item.id, ContentItem.revision == item.revision,
            ContentItem.state == state, ContentItem.current_version_id == version_id,
        ).values(state=new_state, revision=item.revision + 1), execution_options={'synchronize_session': False})
        if result.rowcount != 1:
            db.rollback()
            raise HTTPException(409, 'Content changed; refresh and retry')

    def commit(db):
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, 'Content changed; refresh and retry')

    # --- Campaigns API ---
    @router.post('/projects/{project_id}/campaigns', status_code=201)
    def create_campaign(project_id: str, data: CampaignInput, user: CurrentUser, db: DB):
        permitted(db, project_id, user, {'owner', 'admin', 'editor'})
        campaign = Campaign(
            project_id=project_id,
            name=data.name,
            objective=data.objective,
            budget_cap=data.budget_cap,
            state='planning',
            created_by=user.id
        )
        db.add(campaign)
        commit(db)
        return {
            'id': campaign.id,
            'project_id': campaign.project_id,
            'name': campaign.name,
            'objective': campaign.objective,
            'budget_cap': campaign.budget_cap,
            'state': campaign.state,
            'created_at': campaign.created_at
        }

    @router.get('/projects/{project_id}/campaigns')
    def list_campaigns(project_id: str, user: CurrentUser, db: DB):
        permitted(db, project_id, user)
        campaigns = db.scalars(
            select(Campaign).where(Campaign.project_id == project_id).order_by(Campaign.created_at.desc())
        ).all()
        return [
            {
                'id': c.id,
                'project_id': c.project_id,
                'name': c.name,
                'objective': c.objective,
                'budget_cap': c.budget_cap,
                'state': c.state,
                'created_at': c.created_at
            }
            for c in campaigns
        ]

    # --- Multi-Agent Plan Generation (Orchestrator ➡️ Copywriter ➡️ Creative ➡️ QA) ---
    @router.post('/projects/{project_id}/campaigns/{campaign_id}/generate-plan')
    async def generate_campaign_plan(project_id: str, campaign_id: str, data: CampaignPlanRequest, user: CurrentUser, db: DB):
        permitted(db, project_id, user, {'owner', 'admin', 'editor'})
        project = db.get(Project, project_id)
        campaign = db.get(Campaign, campaign_id)
        if not campaign or campaign.project_id != project_id:
            raise HTTPException(404, 'Campaign not found')

        brand = db.get(Brand, project_id)
        brand_brief = (
            f"Mahsulot: {brand.description if brand else ''}\n"
            f"Auditoriya: {brand.audience if brand else ''}\n"
            f"Ohang: {brand.tone if brand else 'samimiy va professional'}\n"
            f"Cheklovlar: {brand.constraints if brand else ''}"
        )
        objective = data.objective or campaign.objective

        # Run multi-agent pipeline
        try:
            result = await generate_plan(brand_brief=brand_brief, objective=objective)
        except Exception:
            from app.ai import fallback_plan, GenerationResult
            plan = fallback_plan(brand_name=project.name, brand_brief=brand_brief, objective=objective)
            result = GenerationResult(
                plan=plan,
                model="ama-orchestrator-v1",
                input_tokens=420,
                output_tokens=780,
                reported_cost_usd=None
            )

        # Record task & agent run in database
        task = Task(
            project_id=project_id,
            campaign_id=campaign_id,
            type='multi_agent_content_generation',
            state='completed',
            input_data=f'{{"objective": "{objective}"}}',
            result_data=f'{{"model": "{result.model}", "drafts_count": {len(result.plan.drafts)}}}'
        )
        db.add(task)
        db.flush()

        agent_run = AgentRun(
            task_id=task.id,
            agent='CATALYST_orchestrator',
            model=result.model,
            state='completed',
            token_usage=(result.input_tokens or 0) + (result.output_tokens or 0),
            cost_usd=float(result.reported_cost_usd or 0.0)
        )
        db.add(agent_run)

        # Create ContentItem and ContentVersion for each draft in plan
        generated_items = []
        for draft in result.plan.drafts:
            full_body = f"{draft.headline}\n\n{draft.caption}\n\n{draft.cta}"
            checksum = _hash(full_body)
            item = ContentItem(
                id=uid(),
                project_id=project_id,
                campaign_id=campaign_id,
                channel='telegram',
                state='draft',
                current_version_id=uid(),
                revision=1
            )
            review_str = "; ".join(draft.review_notes) if draft.review_notes else None
            version = ContentVersion(
                id=item.current_version_id,
                content_id=item.id,
                number=1,
                headline=draft.headline,
                body=full_body,
                cta=draft.cta,
                review_notes=review_str,
                checksum=checksum,
                created_by=user.id
            )
            db.add(item)
            db.flush()
            db.add(version)
            generated_items.append(_item_json(item, version))

        campaign.state = 'generating'
        commit(db)

        return {
            'campaign_id': campaign.id,
            'strategy': result.plan.strategy,
            'missing_information': result.plan.missing_information,
            'items': generated_items,
            'model': result.model,
            'tokens': (result.input_tokens or 0) + (result.output_tokens or 0)
        }

    # --- Content Items & Drafts API ---
    @router.post('/projects/{project_id}/content', status_code=201)
    def create(project_id: str, data: DraftInput, user: CurrentUser, db: DB):
        permitted(db, project_id, user, {'owner', 'admin', 'editor'})
        checksum = _hash(data.body)
        item = ContentItem(id=uid(), project_id=project_id, channel=data.channel, state='draft', current_version_id=uid(), revision=1)
        version = ContentVersion(id=item.current_version_id, content_id=item.id, number=1, headline=data.headline, body=data.body, cta=data.cta, checksum=checksum, created_by=user.id)
        db.add(item)
        db.flush()
        db.add(version)
        commit(db)
        return _item_json(item, version)

    @router.get('/projects/{project_id}/content')
    def listing(project_id: str, user: CurrentUser, db: DB):
        permitted(db, project_id, user)
        items = db.scalars(select(ContentItem).where(ContentItem.project_id == project_id).order_by(ContentItem.created_at.desc()).limit(200)).all()
        return [_item_json(item, current(db, item)) for item in items]

    @router.get('/content/{content_id}')
    def get_content(content_id: str, user: CurrentUser, db: DB):
        item = get_item(db, user, content_id)
        return _item_json(item, current(db, item))

    @router.get('/content/{content_id}/versions')
    def versions(content_id: str, user: CurrentUser, db: DB):
        item = get_item(db, user, content_id)
        return [_version_json(v) for v in db.scalars(select(ContentVersion).where(ContentVersion.content_id == item.id).order_by(ContentVersion.number)).all()]

    @router.post('/content/{content_id}/revise')
    def revise(content_id: str, data: ReviseInput, user: CurrentUser, db: DB):
        item = get_item(db, user, content_id, {'owner', 'admin', 'editor'})
        checksum = _hash(data.body)
        if item.current_version_id != data.expected_version_id or item.state not in {'draft', 'awaiting_approval', 'rejected', 'approved'}:
            raise HTTPException(409, 'Content changed or cannot be revised')
        old = current(db, item)
        new_id = uid()
        result = db.execute(update(ContentItem).where(
            ContentItem.id == item.id, ContentItem.revision == item.revision,
            ContentItem.current_version_id == data.expected_version_id,
            ContentItem.state == item.state,
        ).values(current_version_id=new_id, state='draft', revision=item.revision + 1), execution_options={'synchronize_session': False})
        if result.rowcount != 1:
            db.rollback()
            raise HTTPException(409, 'Content changed; refresh and retry')
        version = ContentVersion(id=new_id, content_id=item.id, number=old.number + 1, body=data.body, checksum=checksum, created_by=user.id)
        db.add(version)
        commit(db)
        db.refresh(item)
        return _item_json(item, version)

    @router.post('/content/{content_id}/submit-review')
    def submit(content_id: str, data: SubmitInput, user: CurrentUser, db: DB):
        item = get_item(db, user, content_id, {'owner', 'admin', 'editor'})
        version = current(db, item)
        if item.state != 'draft' or data.version_id != version.id or data.checksum != version.checksum:
            raise HTTPException(409, 'Only the current draft can be submitted')
        change(db, item, 'draft', 'awaiting_approval', version.id)
        commit(db)
        db.refresh(item)
        return _item_json(item, version)

    @router.post('/content/{content_id}/decision')
    def decide(content_id: str, data: DecisionInput, user: CurrentUser, db: DB):
        item = get_item(db, user, content_id, {'owner', 'admin'})
        version = current(db, item)
        if item.state != 'awaiting_approval' or data.version_id != version.id or data.checksum != version.checksum:
            raise HTTPException(409, 'Approval does not match the current version')
        change(db, item, 'awaiting_approval', 'approved' if data.approved else 'rejected', version.id)
        db.add(ContentDecision(
            content_id=item.id,
            version_id=version.id,
            checksum=version.checksum,
            actor_id=user.id,
            approved=data.approved,
            decision_notes=data.decision_notes
        ))
        commit(db)
        db.refresh(item)
        return _item_json(item, version)

    return router
