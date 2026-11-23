"""Ledger 向けマスタ API（政治家・政治団体・選挙・紐付け）のスキーマ定義"""

from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel

# ============================================
# 政治家
# ============================================


class Politician(BaseModel):
    """政治家"""

    id: str
    name: str
    name_kana: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    ledger_user_id: Optional[str] = None
    official_url: Optional[str] = None
    party: Optional[str] = None
    photo_url: Optional[str] = None
    is_verified: Optional[bool] = None
    verified_at: Optional[str] = None
    verified_domain: Optional[str] = None
    is_test: Optional[bool] = None
    sns_x: Optional[str] = None
    sns_instagram: Optional[str] = None
    sns_facebook: Optional[str] = None
    sns_tiktok: Optional[str] = None
    is_lg_verified: Optional[bool] = None
    title: Optional[str] = None
    image_url: Optional[str] = None


class PoliticiansResponse(BaseModel):
    """政治家一覧のレスポンス"""

    data: list[Politician]


# ============================================
# 政治団体
# ============================================


class Organization(BaseModel):
    """政治団体"""

    id: str
    name: str
    type: Optional[str] = None
    is_active: Optional[bool] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    official_url: Optional[str] = None
    registration_authority: Optional[str] = None
    established_date: Optional[str] = None
    office_address: Optional[str] = None
    representative_name: Optional[str] = None
    accountant_name: Optional[str] = None
    contact_email: Optional[str] = None
    description: Optional[str] = None
    sns_x: Optional[str] = None
    sns_instagram: Optional[str] = None
    sns_facebook: Optional[str] = None
    sns_tiktok: Optional[str] = None
    is_verified: Optional[bool] = None
    verified_at: Optional[str] = None
    is_test: Optional[bool] = None
    is_lg_verified: Optional[bool] = None


class ManagedOrganization(Organization):
    """Ledger ユーザーが管理する政治団体（管理者としての認証情報付き）"""

    manager_verified_at: Optional[str] = None
    manager_verified_domain: Optional[str] = None


class OrganizationsResponse(BaseModel):
    """政治団体一覧のレスポンス"""

    data: list[Organization]


class ManagedOrganizationsResponse(BaseModel):
    """管理している政治団体一覧のレスポンス"""

    data: list[ManagedOrganization]


class OrganizationResponse(BaseModel):
    """政治団体 1 件のレスポンス"""

    data: Organization


# ============================================
# 選挙
# ============================================


class Election(BaseModel):
    """選挙"""

    id: str
    name: str
    type: Optional[str] = None
    district_id: Optional[str] = None
    election_date: Optional[str] = None
    is_active: Optional[bool] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ElectionsResponse(BaseModel):
    """選挙一覧のレスポンス"""

    data: list[Election]


# ============================================
# 紐付け（政治家 ↔ 選挙 / 政治家 ↔ 政治団体）
# ============================================


class PoliticianElectionRequest(BaseModel):
    """政治家と選挙の紐付けを取得・作成するリクエスト"""

    ledger_user_id: UUID
    politician_id: UUID
    election_id: UUID


class PoliticianElection(BaseModel):
    """政治家と選挙の紐付け"""

    id: str
    politician_id: str
    election_id: str


class PoliticianElectionResponse(BaseModel):
    """政治家と選挙の紐付けのレスポンス"""

    data: PoliticianElection
    action: Literal["existing", "created"]


class PoliticianOrganizationResolveRequest(BaseModel):
    """政治団体の代表者の紐付けを引くリクエスト"""

    ledger_user_id: UUID
    organization_id: UUID


class PoliticianOrganization(BaseModel):
    """政治家と政治団体の紐付け"""

    id: str
    politician_id: str
    organization_id: str
    role: Optional[str] = None


class PoliticianOrganizationResponse(BaseModel):
    """政治家と政治団体の紐付けのレスポンス"""

    data: PoliticianOrganization
