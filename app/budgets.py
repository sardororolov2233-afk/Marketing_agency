"""Project budget preferences, not a provider-enforced spending limit.

Paid requests remain disabled until an atomic reservation ledger and an independently
verified provider-side cap can be enforced and reconciled for uncertain outcomes.
"""
from __future__ import annotations

from typing import Callable
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.db import Base, Project, User, get_db


class ProjectBudget(Base):
    __tablename__ = "project_budgets"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    monthly_limit_cents: Mapped[int] = mapped_column(Integer, nullable=False)


class BudgetInput(BaseModel):
    monthly_limit_cents: int = Field(strict=True, ge=0, le=100_000_000)


def seed_initial_budget(db: Session, project: Project) -> None:
    """Called in the transaction creating each of the three initial projects."""
    if project.slug in {"tamaddun", "uc-chi", "uytor"}:
        db.add(ProjectBudget(project_id=project.id, monthly_limit_cents=3000))


def create_budget_router(current_user: Callable, permitted: Callable) -> APIRouter:
    router = APIRouter(prefix="/api/v1/projects/{project_id}/budget", tags=["budget"])

    @router.get("")
    def get_budget(project_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
        permitted(db, project_id, user)
        budget = db.get(ProjectBudget, project_id)
        return {
            "monthly_limit_cents": budget.monthly_limit_cents if budget else None,
            "currency": "USD",
            "paid_generation_enabled": False,
            "limit_enforced": False,
            "actual_spend_cents": None,
            "message": "Budget preference only; provider charges are not connected or tracked.",
        }

    @router.put("")
    def set_budget(project_id: str, data: BudgetInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
        permitted(db, project_id, user, {"owner"})
        budget = db.get(ProjectBudget, project_id)
        if budget is None:
            budget = ProjectBudget(project_id=project_id, monthly_limit_cents=data.monthly_limit_cents)
            db.add(budget)
        else:
            budget.monthly_limit_cents = data.monthly_limit_cents
        db.commit()
        return {"monthly_limit_cents": budget.monthly_limit_cents, "currency": "USD", "limit_enforced": False, "paid_generation_enabled": False}

    return router
