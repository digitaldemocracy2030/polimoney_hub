"""選挙 API（Ledger 専用）"""

from fastapi import APIRouter, Depends, HTTPException, status
from supabase import Client

from app.core.api_key import LedgerApiCaller, require_ledger_api_key
from app.database.supabase import get_admin_supabase_client_dep
from app.schemas.hub_master import ElectionsResponse
from app.utils.test_scope import apply_test_scope

router = APIRouter()

ELECTION_COLUMNS = (
    "id, name, type, district_id, election_date, is_active, created_at, updated_at"
)


@router.get("/elections", response_model=ElectionsResponse)
async def list_elections(
    supabase: Client = Depends(get_admin_supabase_client_dep),
    caller: LedgerApiCaller = Depends(require_ledger_api_key),
):
    """有効な選挙の一覧を投票日の新しい順で返す"""
    query = supabase.table("elections").select(ELECTION_COLUMNS).eq("is_active", True)
    query = apply_test_scope(query, caller).order("election_date", desc=True)

    try:
        result = query.execute()
    except Exception as e:
        print(f"[Elections] Error fetching elections: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="選挙の取得に失敗しました",
        )

    return {"data": result.data or []}
