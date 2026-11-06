"""Project-scoped content drafts and human approvals.

State changes use compare-and-swap conditions so concurrent requests cannot
approve a stale version. The historical version and decision rows are append-only.
No endpoint in this module publishes content.
"""
from hashlib import sha256
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.content_models import ContentDecision, ContentItem, ContentVersion
from app.db import User, get_db, uid


class DraftInput(BaseModel):
    channel: str = Field(min_length=1, max_length=40, pattern=r'^[a-z][a-z0-9_-]*$')
    body: str = Field(min_length=1, max_length=10000)


class ReviseInput(BaseModel):
    expected_version_id: str = Field(min_length=1, max_length=36)
    body: str = Field(min_length=1, max_length=10000)


class SubmitInput(BaseModel):
    version_id: str = Field(min_length=1, max_length=36)
    checksum: str = Field(min_length=64, max_length=64, pattern=r'^[0-9a-f]{64}$')


class DecisionInput(SubmitInput):
    approved: bool = Field(strict=True)


def _hash(body):
    if not body.strip():
        raise HTTPException(422, 'Content must not be empty')
    return sha256(body.encode('utf-8')).hexdigest()


def _version_json(version):
    return {'id': version.id, 'number': version.number, 'body': version.body, 'checksum': version.checksum, 'created_at': version.created_at}


def _item_json(item, version):
    return {'id': item.id, 'project_id': item.project_id, 'channel': item.channel, 'state': item.state, 'version': _version_json(version)}


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

    @router.post('/projects/{project_id}/content', status_code=201)
    def create(project_id: str, data: DraftInput, user: CurrentUser, db: DB):
        permitted(db, project_id, user, {'owner', 'admin', 'editor'})
        checksum = _hash(data.body)
        item = ContentItem(id=uid(), project_id=project_id, channel=data.channel, state='draft', current_version_id=uid(), revision=1)
        version = ContentVersion(id=item.current_version_id, content_id=item.id, number=1, body=data.body, checksum=checksum, created_by=user.id)
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
        db.add(ContentDecision(content_id=item.id, version_id=version.id, checksum=version.checksum, actor_id=user.id, approved=data.approved))
        commit(db)
        db.refresh(item)
        return _item_json(item, version)

    return router
