"""本人確認（政治家・政治団体の管理者）API のスキーマ"""

from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class PoliticianVerificationCreate(BaseModel):
    """政治家の本人確認の申請（Ledger から）"""

    ledger_user_id: UUID
    ledger_user_email: str = Field(..., min_length=1, max_length=320)
    name: str = Field(..., min_length=1, max_length=100)
    official_email: str = Field(..., min_length=3, max_length=320)
    official_url: Optional[str] = Field(None, max_length=500)
    party: Optional[str] = Field(None, max_length=100)
    request_type: Literal["new", "domain_change"] = "new"
    previous_domain: Optional[str] = Field(None, max_length=253)
    # どちらか一方は必須（立候補届出 / 政治資金収支報告書）
    candidate_registration_info: Optional[dict[str, Any]] = None
    political_fund_report_info: Optional[dict[str, Any]] = None


class OrganizationManagerVerificationCreate(BaseModel):
    """政治団体の管理者の本人確認の申請（Ledger から）"""

    ledger_user_id: UUID
    ledger_user_email: str = Field(..., min_length=1, max_length=320)
    # Hub に登録済みの団体なら指定する。無ければ承認時に団体を作る
    organization_id: Optional[UUID] = None
    organization_name: str = Field(..., min_length=1, max_length=200)
    organization_type: Optional[str] = Field(None, max_length=50)
    official_email: str = Field(..., min_length=3, max_length=320)
    role_in_organization: Optional[str] = Field(None, max_length=100)
    request_type: Literal["new", "domain_change"] = "new"
    previous_domain: Optional[str] = Field(None, max_length=253)
    political_fund_report_info: dict[str, Any]


class VerificationOwnerRequest(BaseModel):
    """申請を操作する Ledger ユーザー（申請者本人であること）"""

    ledger_user_id: UUID


class VerifyCodeRequest(VerificationOwnerRequest):
    code: str = Field(..., min_length=1, max_length=20)


class RejectVerificationRequest(BaseModel):
    rejection_reason: str = Field(..., min_length=1, max_length=1000)
