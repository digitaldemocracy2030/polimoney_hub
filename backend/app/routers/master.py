"""マスタデータ API

勘定科目などの共通マスタを返す読み取り専用 API。
一般公開するまでは Ledger 専用 API キーが必要（main.py で require_ledger_sync_key を指定）。
Ledger は仕訳入力と Hub 同期でこの勘定科目を使う。
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from supabase import Client

from app.database.supabase import get_supabase_client_dep
from app.schemas.master import (
    AccountCodeResponse,
    AccountCodesResponse,
    AccountLedgerType,
    AccountType,
)

router = APIRouter(prefix="/master")

ACCOUNT_CODE_COLUMNS = (
    "code, name, name_kana, type, report_category, ledger_type, "
    "is_public_subsidy_eligible, display_order, polimoney_category, "
    "parent_code, description"
)


@router.get("/account-codes", response_model=AccountCodesResponse)
async def list_account_codes(
    ledger_type: Optional[AccountLedgerType] = None,
    type: Optional[AccountType] = None,
    report_category: Optional[str] = None,
    supabase: Client = Depends(get_supabase_client_dep),
):
    """有効な勘定科目の一覧を表示順で返す

    Args:
        ledger_type: 'organization' / 'election' を指定すると、その台帳で使える科目
            （ledger_type が指定値または both のもの）に絞る。'both' は絞り込まない
        type: 勘定科目の種類で絞る
        report_category: 報告書の区分で絞る
    """
    query = (
        supabase.table("account_codes")
        .select(ACCOUNT_CODE_COLUMNS)
        .eq("is_active", True)
        .order("display_order")
    )
    if ledger_type and ledger_type != "both":
        query = query.in_("ledger_type", ["both", ledger_type])
    if type:
        query = query.eq("type", type)
    if report_category:
        query = query.eq("report_category", report_category)

    try:
        result = query.execute()
    except Exception as e:
        print(f"[Master] Error fetching account codes: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="勘定科目の取得に失敗しました",
        )

    return {"data": result.data or []}


@router.get("/account-codes/{code}", response_model=AccountCodeResponse)
async def get_account_code(
    code: str,
    supabase: Client = Depends(get_supabase_client_dep),
):
    """勘定科目を 1 件返す

    過去の仕訳が参照している可能性があるため、無効（is_active=false）の科目も返す。
    """
    try:
        result = (
            supabase.table("account_codes")
            .select(ACCOUNT_CODE_COLUMNS)
            .eq("code", code)
            .limit(1)
            .execute()
        )
    except Exception as e:
        print(f"[Master] Error fetching account code {code}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="勘定科目の取得に失敗しました",
        )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="勘定科目が見つかりません",
        )
    return {"data": result.data[0]}
