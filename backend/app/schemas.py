from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Impact(StrictModel):
    candidate_id: str
    metric: Literal["quantity", "purchase", "transport", "storage", "testing", "disposal", "subtotal", "total"]
    value: str
    evidence_ref: str


class Proposal(StrictModel):
    candidate_ids: list[str]
    summary: str


class Rationale(StrictModel):
    candidate_id: str
    claim: str
    evidence_refs: list[str]
    message_refs: list[str]
    change_refs: list[str]
    remaining_risks: list[str]


class DepartmentTurn(StrictModel):
    role: str
    strategy_id: str
    version: int
    proposal: Proposal
    impacts: list[Impact]
    reasons: list[str]
    evidence_refs: list[str]
    change_requests: list[str]
    position: Literal["accept", "object", "needs_information"]
    recommendations: list[Rationale]


class Login(StrictModel):
    email: str
    password: str


class DiscussionInput(StrictModel):
    expected_revision: int
    alert_id: str | None = None


class ApprovalInput(StrictModel):
    expected_revision: int
    acknowledge_unverified: bool
    budget_approval_reason: str | None = None
    budget_approval_amount: str | None = None
