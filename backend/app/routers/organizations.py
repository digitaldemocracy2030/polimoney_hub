"""政治団体 API（Ledger 専用）"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from supabase import Client

from app.core.api_key import LedgerApiCaller, require_ledger_api_key
from app.database.supabase import get_admin_supabase_client_dep
from app.schemas.hub_master import (
    ManagedOrganizationsResponse,
    OrganizationResponse,
    OrganizationsResponse,
)
from app.utils.test_scope import apply_test_scope

router = APIRouter(prefix="/organizations")

ORGANIZATION_COLUMNS = (
    "id, name, type, is_active, created_at, updated_at, official_url, "
    "registration_authority, established_date, office_address, representative_name, "
    "accountant_name, contact_email, description, sns_x, sns_instagram, sns_facebook, "
    "sns_tiktok, is_verified, verified_at, is_test, is_lg_verified"
)


def _fetch_error(e: Exception) -> HTTPException:
    print(f"[Organizations] Error fetching organizations: {e}")
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="政治団体の取得に失敗しました",
    )


@router.get("", response_model=OrganizationsResponse)
async def list_organizations(
    supabase: Client = Depends(get_admin_supabase_client_dep),
    caller: LedgerApiCaller = Depends(require_ledger_api_key),
):
    """有効な政治団体の一覧を名前順で返す"""
    query = (
        supabase.table("organizations")
        .select(ORGANIZATION_COLUMNS)
        .eq("is_active", True)
    )
    query = apply_test_scope(query, caller).order("name")

    try:
        result = query.execute()
    except Exception as e:
        raise _fetch_error(e)

    return {"data": result.data or []}


# /{organization_id} より前に宣言する（"managed" が ID として扱われないように）
@router.get("/managed", response_model=ManagedOrganizationsResponse)
async def list_managed_organizations(
    ledger_user_id: UUID = Query(..., description="Ledger のユーザー ID"),
    supabase: Client = Depends(get_admin_supabase_client_dep),
    caller: LedgerApiCaller = Depends(require_ledger_api_key),
):
    """Ledger ユーザーが管理者（organization_managers.is_active）になっている政治団体の一覧を返す

    各団体に管理者としての認証日時・認証ドメイン（manager_verified_at / manager_verified_domain）を付ける。
    """
    try:
        managers_query = (
            supabase.table("organization_managers")
            .select("organization_id, verified_at, verified_domain")
            .eq("ledger_user_id", str(ledger_user_id))
            .eq("is_active", True)
        )
        managers = apply_test_scope(managers_query, caller).execute().data or []
        if not managers:
            return {"data": []}

        org_ids = list(dict.fromkeys(m["organization_id"] for m in managers))
        orgs_query = (
            supabase.table("organizations")
            .select(ORGANIZATION_COLUMNS)
            .in_("id", org_ids)
        )
        orgs = apply_test_scope(orgs_query, caller).order("name").execute().data or []
    except Exception as e:
        raise _fetch_error(e)

    manager_by_org = {}
    for m in managers:
        manager_by_org.setdefault(m["organization_id"], m)

    data = []
    for org in orgs:
        manager = manager_by_org.get(org["id"])
        if not manager:
            continue
        data.append(
            {
                **org,
                "manager_verified_at": manager.get("verified_at"),
                "manager_verified_domain": manager.get("verified_domain"),
            }
        )
    return {"data": data}


@router.get("/{organization_id}", response_model=OrganizationResponse)
async def get_organization(
    organization_id: UUID,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    caller: LedgerApiCaller = Depends(require_ledger_api_key),
):
    """政治団体を 1 件返す（無効な団体も返す）"""
    query = (
        supabase.table("organizations")
        .select(ORGANIZATION_COLUMNS)
        .eq("id", str(organization_id))
    )
    try:
        result = apply_test_scope(query, caller).limit(1).execute()
    except Exception as e:
        raise _fetch_error(e)

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="政治団体が見つかりません",
        )
    return {"data": result.data[0]}
