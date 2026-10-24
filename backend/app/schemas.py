from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, SecretStr


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Impact(StrictModel):
    candidate_id: str
    metric: Literal["quantity", "purchase", "transport", "storage", "testing", "disposal", "subtotal", "total"] = Field(description="quantity는 주문 수량, 나머지는 금액이다. disposal은 예상 폐기 비용이지 폐기 수량이 아니다.")
    value: str = Field(description="해당 candidate_id의 impact_contract에서 metric에 대응하는 계산값을 단위 변환·재계산 없이 그대로 복사한다.")
    evidence_ref: str = Field(description="이 수치의 근거인 reference_contract.evidence_ids의 실제 ID.")


class Proposal(StrictModel):
    candidate_ids: list[str]
    summary: str = Field(description="자기 역할의 독립 검토 결론 또는 판단 보류. 첫 병렬 회차에서 다른 AI 제안을 수용했다고 표현하지 않는다.")


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
    reasons: list[str] = Field(description="역할 관점에서 등록 대안 간 장단점·트레이드오프를 비교한 간결한 근거. 공통 안전 안내 반복 금지. 숫자 주장은 impacts에 기록한다.")
    evidence_refs: list[str] = Field(description="reference_contract.evidence_ids에서 복사한 실제 근거 ID만 사용. 품목 코드·이름·URL·JSON 경로는 ID가 아니다.")
    change_requests: list[str] = Field(description="남은 의사결정 조건·위험과 구체적인 확인/수정 요청. 근거 없는 일정·품질·지급 조건은 확인 요청으로 남긴다.")
    position: Literal["accept", "object", "needs_information"]
    recommendations: list[Rationale]


class ReviewMetric(StrictModel):
    candidate_id: str
    metric: Literal["quantity", "purchase", "transport", "storage", "testing", "disposal", "subtotal", "total"] = Field(description="이 역할 판단에 중요한 지표 이름만 고른다. 값은 서버가 impact_contract에서 채운다.")


class ReviewTurn(StrictModel):
    """Reviewer output: only judgment. The server adds identity fields and exact metric values."""
    position: Literal["accept", "object", "needs_information"]
    candidate_ids: list[str] = Field(description="이 역할이 우선하거나 조건부로 수용하는 등록 후보 ID. 전체 나열 금지.")
    summary: str = Field(description="자기 역할의 독립 검토 결론 또는 판단 보류. 첫 병렬 회차에서 다른 AI 제안을 수용했다고 표현하지 않는다.")
    reasons: list[str] = Field(description="역할 관점에서 등록 대안 간 장단점·트레이드오프를 비교한 간결한 근거. 공통 안전 안내 반복 금지.")
    change_requests: list[str] = Field(description="남은 의사결정 조건·위험과 구체적인 확인/수정 요청. 근거 없는 일정·품질·지급 조건은 확인 요청으로 남긴다.")
    evidence_refs: list[str] = Field(description="reference_contract.evidence_ids에서 복사한 핵심 근거 ID만 사용.")
    metrics: list[ReviewMetric] = Field(description="판단에 결정적인 후보별 지표만, 보통 두세 개.")


class Login(StrictModel):
    email: str
    password: str


class DiscussionInput(StrictModel):
    expected_revision: int
    alert_id: str | None = None


class ApprovalInput(StrictModel):
    decision_reason: str | None = Field(default=None, max_length=2000)
    expected_revision: int
    acknowledge_unverified: bool
    budget_approval_reason: str | None = None
    budget_approval_amount: str | None = None


class QuoteScheduleLine(StrictModel):
    production_id: str = Field(min_length=1, max_length=80)
    needed_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    quantity: int = Field(ge=1, le=10000)


class SMTPConnectInput(StrictModel):
    app_password: SecretStr


class QuoteEmailInput(StrictModel):
    delivery_mode: Literal["simulation", "smtp", "gmail_mcp"] = "smtp"
    expected_revision: int | None = None
    source_stamp: str = ""
    final_confirmation: bool = False
    case_id: str = Field(min_length=1, max_length=100)
    vendor_id: str = Field(min_length=1, max_length=100)
    vendor_name: str = Field(min_length=1, max_length=200)
    sender_email: str = Field(min_length=3, max_length=254)
    recipient_email: str = Field(min_length=3, max_length=254)
    subject: str = Field(min_length=2, max_length=250)
    body: str = Field(min_length=10, max_length=12000)
    material_code: str = Field(min_length=1, max_length=100)
    material_name: str = Field(min_length=1, max_length=200)
    unit: str = Field(min_length=1, max_length=40)
    required_quantity: int = Field(ge=1, le=10000)
    safety_stock: int = Field(ge=0, le=10000)
    schedule: list[QuoteScheduleLine] = Field(min_length=1, max_length=24)
