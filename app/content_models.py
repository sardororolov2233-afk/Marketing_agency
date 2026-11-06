"""Durable drafts and append-only content versions and human decisions."""
from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base, uid


def utcnow():
    return datetime.now(timezone.utc)


class ContentItem(Base):
    __tablename__ = 'content_items'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'), index=True)
    campaign_id: Mapped[str | None] = mapped_column(ForeignKey('campaigns.id'), nullable=True, index=True)
    channel: Mapped[str] = mapped_column(String(40))
    state: Mapped[str] = mapped_column(String(32), default='draft')
    current_version_id: Mapped[str] = mapped_column(String(36))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ContentVersion(Base):
    __tablename__ = 'content_versions'
    __table_args__ = (UniqueConstraint('content_id', 'number'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    content_id: Mapped[str] = mapped_column(ForeignKey('content_items.id'), index=True)
    number: Mapped[int] = mapped_column(Integer)
    headline: Mapped[str | None] = mapped_column(String(300), nullable=True)
    body: Mapped[str] = mapped_column(Text)
    cta: Mapped[str | None] = mapped_column(String(500), nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    claim_sources: Mapped[str | None] = mapped_column(Text, nullable=True)
    checksum: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ContentDecision(Base):
    __tablename__ = 'content_decisions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    content_id: Mapped[str] = mapped_column(ForeignKey('content_items.id'), index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey('content_versions.id'))
    checksum: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    approved: Mapped[bool] = mapped_column(Boolean)
    decision_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
