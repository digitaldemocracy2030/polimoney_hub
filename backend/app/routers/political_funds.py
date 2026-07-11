"""政治資金収支報告書のAPIエンドポイント

public_journalsとpublic_ledgersテーブルから政治資金データを取得する。
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from supabase import Client

from app import schemas
from app.database.supabase import get_supabase_client_dep
from app.models.public_journals import PublicJournal
from app.models.public_ledgers import PublicLedger
from app.utils.category import derive_category, get_category_name

router = APIRouter()


@router.get(
    "/political-funds/{ledger_id}",
    response_model=schemas.PoliticalFundsResponse,
)
async def get_political_funds_by_ledger_id(
    ledger_id: UUID,
    supabase: Client = Depends(get_supabase_client_dep),
):
    """指定した台帳IDの政治資金データを取得する

    public_ledgersのIDを指定して、関連するpublic_journalsと
    政治団体情報、政治家情報を取得する。

    Args:
        ledger_id: 台帳ID（public_ledgers.id）
        supabase: Supabaseクライアント

    Returns:
        schemas.PoliticalFundsResponse: 政治資金データ

    Raises:
        HTTPException: 指定されたデータが見つからない場合
            - 404: 台帳が存在しない場合、または政治団体の台帳でない場合
    """
    # 1. public_ledgersを取得（ledger_type='political_fund' であること）
    ledger_response = (
        supabase.table("public_ledgers")
        .select("*")
        .eq("id", str(ledger_id))
        .eq("ledger_type", "political_fund")
        .maybe_single()
        .execute()
    )

    if not ledger_response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="政治資金の台帳が見つかりません",
        )

    ledger = PublicLedger(**ledger_response.data)

    # 2. 中間テーブル経由で政治家情報と政治団体情報を取得
    pol_org_response = (
        supabase.table("politician_organizations")
        .select(
            """
            id,
            politicians:politician_id(id, name, name_kana),
            organizations:organization_id(id, name, type)
            """
        )
        .eq("id", str(ledger.politician_organization_id))
        .maybe_single()
        .execute()
    )

    if not pol_org_response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="政治家・政治団体情報が見つかりません",
        )

    pol_org_data = pol_org_response.data
    politician_data = pol_org_data.get("politicians")
    organization_data = pol_org_data.get("organizations")

    if not politician_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="政治家情報が見つかりません",
        )

    if not organization_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="政治団体情報が見つかりません",
        )

    politician = schemas.PoliticianInfo(**politician_data)
    organization = schemas.OrganizationInfo(**organization_data)

    # 3. public_journalsを取得
    journals_response = (
        supabase.table("public_journals")
        .select("*")
        .eq("ledger_id", str(ledger_id))
        .order("date", desc=False)
        .execute()
    )

    if not journals_response.data:
        journals_data = []
    else:
        journals_data = journals_response.data

    # 4. account_codesを一括取得（必要なaccount_codeのリストを作成）
    account_codes_list = [
        journal_data.get("account_code")
        for journal_data in journals_data
        if journal_data.get("account_code")
    ]
    account_codes_map = {}
    if account_codes_list:
        account_codes_response = (
            supabase.table("account_codes")
            .select("code, name")
            .in_("code", account_codes_list)
            .execute()
        )
        if account_codes_response.data:
            account_codes_map = {
                item["code"]: item["name"] for item in account_codes_response.data
            }

    # 5. データを変換
    data_items = []
    for journal_data in journals_data:
        journal = PublicJournal(**journal_data)

        # account_codeからcategoryを導出
        category = derive_category(journal.account_code)
        category_name = get_category_name(category)

        # account_codesテーブルから取得した名前があれば使用
        if journal.account_code and journal.account_code in account_codes_map:
            category_name = account_codes_map[journal.account_code]

        # public_expense_amountが0の場合はNoneにする
        public_expense_amount = journal.public_expense_amount
        if public_expense_amount == 0:
            public_expense_amount = None

        data_item = schemas.PoliticalFundsDataItem(
            id=journal.id,
            date=journal.date,
            amount=journal.amount,
            category=category,
            category_name=category_name,
            type="政治活動",
            purpose=journal.description,
            non_monetary_basis=journal.non_monetary_basis,
            note=journal.note,
            public_expense_amount=public_expense_amount,
        )
        data_items.append(data_item)

    # 6. サマリー情報を作成
    summary = schemas.PoliticalFundsSummary(
        total_income=ledger.total_income,
        total_expense=ledger.total_expense,
        balance=ledger.total_income - ledger.total_expense,
        journal_count=ledger.journal_count,
    )

    # 7. メタ情報を作成
    meta = schemas.PoliticalFundsMeta(
        api_version="v1",
        politician=politician,
        organization=organization,
        summary=summary,
        generated_at=datetime.now(),
    )

    # 8. レスポンスを作成
    return schemas.PoliticalFundsResponse(meta=meta, data=data_items)
