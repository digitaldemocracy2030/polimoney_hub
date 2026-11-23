"""政治家 API（Ledger 専用）

Ledger が自分のユーザーに紐づく政治家を引くための読み取り API。
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from supabase import Client

from app.core.api_key import LedgerApiCaller, require_ledger_api_key
from app.database.supabase import get_admin_supabase_client_dep
from app.schemas.hub_master import PoliticiansResponse
from app.utils.test_scope import apply_test_scope

router = APIRouter()

POLITICIAN_COLUMNS = (
    "id, name, name_kana, created_at, updated_at, ledger_user_id, official_url, "
    "party, photo_url, is_verified, verified_at, verified_domain, is_test, "
    "sns_x, sns_instagram, sns_facebook, sns_tiktok, is_lg_verified, title, image_url"
)


@router.get("/politicians", response_model=PoliticiansResponse)
async def list_politicians(
    ledger_user_id: UUID = Query(..., description="Ledger のユーザー ID"),
    supabase: Client = Depends(get_admin_supabase_client_dep),
    caller: LedgerApiCaller = Depends(require_ledger_api_key),
):
    """ledger_user_id が一致する政治家の一覧を返す"""
    query = (
        supabase.table("politicians")
        .select(POLITICIAN_COLUMNS)
        .eq("ledger_user_id", str(ledger_user_id))
    )
    query = apply_test_scope(query, caller).order("created_at")

    try:
        result = query.execute()
    except Exception as e:
        print(f"[Politicians] Error fetching politicians: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="政治家の取得に失敗しました",
        )

    return {"data": result.data or []}
