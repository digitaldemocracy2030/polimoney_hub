"""登録申請（選挙・政治団体）と年度のロック解除申請の API のスキーマ

文字列の長さの上限は Hub DB の列（varchar）に合わせる（超えると DB で失敗して 500 になるため）。
"""

from datetime import date
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ElectionRequestCreate(BaseModel):
    """選挙の登録申請（Ledger から）"""

    ledger_user_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    # 選挙種別のコード（HR / HC / PG / PA / GM / CM など）
    type: str = Field(..., min_length=1, max_length=10)
    area_description: Optional[str] = Field(None, max_length=500)
    election_date: date
    # 申請者が Hub で本人確認済みの政治家なら、その政治家の ID
    requested_by_politician_id: Optional[UUID] = None
    requested_by_email: Optional[str] = Field(None, max_length=255)
    evidence_url: Optional[str] = Field(None, max_length=1000)
    notes: Optional[str] = Field(None, max_length=2000)


class OrganizationRequestCreate(BaseModel):
    """政治団体の登録申請（Ledger から）"""

    ledger_user_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    type: str = Field(..., min_length=1, max_length=50)
    registration_authority: Optional[str] = Field(None, max_length=100)
    requested_by_politician_id: Optional[UUID] = None
    requested_by_email: Optional[str] = Field(None, max_length=255)
    evidence_type: str = Field(..., min_length=1, max_length=50)
    # 審査用の署名付き URL（期限あり）
    evidence_file_url: str = Field(..., min_length=1, max_length=2000)
    # Ledger Storage 上のパス（URL の期限切れ後の再発行に使う）
    evidence_file_path: Optional[str] = Field(None, max_length=1000)
    evidence_file_name: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = Field(None, max_length=2000)


class UnlockRequestCreate(BaseModel):
    """年度のロック解除申請（Ledger から）"""

    # Ledger の台帳の ID
    ledger_id: UUID
    ledger_type: Literal["election", "organization"]
    fiscal_year: Optional[int] = Field(None, ge=1900, le=2999)
    requested_by_user_id: UUID
    requested_by_email: str = Field(..., min_length=1, max_length=255)
    reason: str = Field(..., min_length=10, max_length=2000)


class ApproveElectionRequest(BaseModel):
    """選挙の登録申請の承認。election_id を指定すると既存の選挙に紐付ける（作らない）"""

    election_id: Optional[UUID] = None


class ApproveOrganizationRequest(BaseModel):
    """政治団体の登録申請の承認。organization_id を指定すると既存の団体に紐付ける（作らない）"""

    organization_id: Optional[UUID] = None


class ApproveUnlockRequest(BaseModel):
    """ロック解除の承認。解除しておく時間（既定 7 日、最大 30 日）"""

    unlock_hours: int = Field(168, ge=1, le=720)


class RejectRequest(BaseModel):
    rejection_reason: str = Field(..., min_length=1, max_length=1000)
