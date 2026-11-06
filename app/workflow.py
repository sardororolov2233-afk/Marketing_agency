"""Content approval rules. The caller must authenticate actors and persist atomically.

This module does not send messages or store state. In particular, its guards must
be run inside a transaction with a lock on the content and job records in a
production implementation; in-memory objects alone cannot prevent races.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from uuid import UUID, uuid4


class WorkflowError(ValueError):
    """Invalid workflow transition or input."""


class Forbidden(WorkflowError):
    """The trusted membership does not authorize the action."""


@dataclass(frozen=True)
class Actor:
    """Membership resolved by the server, never directly from request data."""

    user_id: UUID
    project_id: UUID
    role: str


def _authorize(actor: Actor, project_id: UUID, roles: set[str]) -> None:
    if actor.project_id != project_id or actor.role not in roles:
        raise Forbidden("Project access denied")


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise WorkflowError("Timezone-aware datetime required")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class Version:
    id: UUID
    number: int
    text: str
    checksum: str

    @classmethod
    def create(cls, number: int, text: str) -> Version:
        if not isinstance(text, str) or not text.strip():
            raise WorkflowError("Content must not be empty")
        return cls(uuid4(), number, text, sha256(text.encode("utf-8")).hexdigest())


@dataclass(frozen=True)
class Decision:
    version_id: UUID
    checksum: str
    actor_id: UUID
    approved: bool
    decided_at: datetime


@dataclass
class Content:
    project_id: UUID
    channel: str
    id: UUID = field(default_factory=uuid4)
    versions: list[Version] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    state: str = "draft"

    @property
    def current(self) -> Version:
        if not self.versions:
            raise WorkflowError("Content has no version")
        return self.versions[-1]

    def revise(self, actor: Actor, text: str) -> Version:
        _authorize(actor, self.project_id, {"owner", "admin", "editor"})
        if self.state in {"publishing", "published", "outcome_unknown"}:
            raise WorkflowError("Cannot revise content after publishing starts")
        version = Version.create(len(self.versions) + 1, text)
        self.versions.append(version)
        # Historical decisions are retained, but none apply to the new version.
        self.state = "draft"
        return version

    def submit(self, actor: Actor) -> None:
        _authorize(actor, self.project_id, {"owner", "admin", "editor"})
        if self.state != "draft":
            raise WorkflowError("Only drafts can be submitted")
        self.current
        self.state = "awaiting_approval"

    def decide(self, actor: Actor, version_id: UUID, checksum: str,
               approved: bool, now: datetime) -> Decision:
        _authorize(actor, self.project_id, {"owner", "admin"})
        if self.state != "awaiting_approval":
            raise WorkflowError("Content is not awaiting approval")
        version = self.current
        if version.id != version_id or version.checksum != checksum:
            raise WorkflowError("Version or checksum changed")
        if not isinstance(approved, bool):
            raise WorkflowError("Decision must be boolean")
        decision = Decision(version.id, version.checksum, actor.user_id, approved, _aware(now))
        self.decisions.append(decision)
        self.state = "approved" if approved else "rejected"
        return decision

    def schedule(self, actor: Actor, version_id: UUID, due_at: datetime,
                 now: datetime) -> PublishJob:
        _authorize(actor, self.project_id, {"owner", "admin"})
        if self.state != "approved" or self.current.id != version_id:
            raise WorkflowError("Current version must be approved")
        decision = self.decisions[-1] if self.decisions else None
        if not decision or not decision.approved or decision.version_id != version_id or decision.checksum != self.current.checksum:
            raise WorkflowError("Approval does not match content")
        due = _aware(due_at)
        if due < _aware(now):
            raise WorkflowError("Schedule time is in the past")
        self.state = "scheduled"
        return PublishJob(self.project_id, self.id, version_id, self.current.checksum, due)


@dataclass
class PublishJob:
    project_id: UUID
    content_id: UUID
    version_id: UUID
    checksum: str
    due_at: datetime
    id: UUID = field(default_factory=uuid4)
    state: str = "scheduled"
    remote_id: str | None = None

    def begin(self, content: Content, now: datetime) -> Version:
        if self.state != "scheduled" or content.state != "scheduled":
            raise WorkflowError("Job is not scheduled")
        if self.content_id != content.id or self.project_id != content.project_id:
            raise WorkflowError("Job does not match content")
        if _aware(now) < self.due_at:
            raise WorkflowError("Job is not due")
        version = content.current
        decision = content.decisions[-1] if content.decisions else None
        if (version.id != self.version_id or version.checksum != self.checksum or
                not decision or not decision.approved or decision.version_id != version.id or
                decision.checksum != version.checksum):
            raise WorkflowError("Approved version changed")
        self.state = content.state = "publishing"
        return version

    def complete(self, content: Content, remote_id: str) -> None:
        if self.state != "publishing" or content.id != self.content_id or content.state != "publishing":
            raise WorkflowError("Job is not publishing")
        if not isinstance(remote_id, str) or not remote_id.strip():
            raise WorkflowError("Provider receipt required")
        self.remote_id = remote_id
        self.state = content.state = "published"

    def uncertain(self, content: Content) -> None:
        """A timeout may mean success: do not automatically retry the send."""
        if self.state != "publishing" or content.id != self.content_id or content.state != "publishing":
            raise WorkflowError("Job is not publishing")
        self.state = content.state = "outcome_unknown"
