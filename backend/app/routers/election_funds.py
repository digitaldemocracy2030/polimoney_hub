"""選挙運動費用収支報告書のAPIエンドポイント

public_journalsとpublic_ledgersテーブルから選挙資金データを取得する。
"""

from uuid import UUID

from fastapi import APIRouter, Depends
from supabase import Client

from app import schemas
from app.database.supabase import get_admin_supabase_client_dep
from app.utils.election_funds_response import build_election_funds_response

router = APIRouter()


@router.get(
    "/election-funds/{ledger_id}",
    response_model=schemas.ElectionFundsResponse,
)
async def get_election_funds_by_ledger_id(
    ledger_id: UUID,
    supabase: Client = Depends(get_admin_supabase_client_dep),
):
    """指定した台帳IDの選挙資金データを取得する

    public_ledgersのIDを指定して、関連するpublic_journalsと
    選挙情報、政治家情報を取得する。

    Args:
        ledger_id: 台帳ID（public_ledgers.id）
        supabase: Supabaseクライアント

    Returns:
        schemas.ElectionFundsResponse: 選挙資金データ

    Raises:
        HTTPException: 指定されたデータが見つからない場合
            - 404: 台帳が存在しない場合、または選挙運動の台帳でない場合
    """
    return build_election_funds_response(supabase, ledger_id)
