"""選挙資金レスポンス組み立てユーティリティ

public_ledgers と public_journals から ElectionFundsResponse を生成する。
"""

from datetime import datetime
from uuid import UUID

from fastapi import HTTPException, status
from supabase import Client

from app import schemas
from app.models.public_journals import PublicJournal
from app.models.public_ledgers import PublicLedger
from app.utils.category import (
    derive_category,
    get_category_name,
    get_election_type_name,
)


def is_positive_public_expense(amount: int | None) -> bool:
    """公費負担額が正の値かどうかを判定する

    Args:
        amount: 公費負担額

    Returns:
        bool: 正の値なら True
    """
    return amount is not None and amount > 0


def normalize_public_expense_amount(amount: int | None) -> int | None:
    """レスポンス用に公費負担額を正規化する

    Args:
        amount: 公費負担額

    Returns:
        int | None: 正の値のみ返却、それ以外は None
    """
    if is_positive_public_expense(amount):
        return amount
    return None


def sum_public_expense_by_ledger(journals_data: list[dict]) -> dict[str, int]:
    """仕訳データから台帳ごとの公費負担合計を算出する

    Args:
        journals_data: public_journals の行リスト

    Returns:
        dict[str, int]: ledger_id をキーとした公費負担合計
    """
    totals: dict[str, int] = {}
    for journal in journals_data:
        ledger_id = journal.get("ledger_id")
        amount = journal.get("public_expense_amount")
        if not ledger_id or not is_positive_public_expense(amount):
            continue
        totals[ledger_id] = totals.get(ledger_id, 0) + amount
    return totals


def assert_election_exists(supabase: Client, election_id: UUID) -> None:
    """選挙が存在することを確認する

    Args:
        supabase: Supabaseクライアント
        election_id: 選挙ID

    Raises:
        HTTPException: 選挙が見つからない場合（404）
    """
    election_response = (
        supabase.table("elections")
        .select("id")
        .eq("id", str(election_id))
        .maybe_single()
        .execute()
    )

    if not election_response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="選挙情報が見つかりません",
        )


def fetch_election_ledger_or_raise(
    supabase: Client,
    ledger_id: UUID,
    *,
    not_found_detail: str = "台帳が見つかりません",
    non_election_detail: str = "選挙台帳以外は非対応です",
) -> PublicLedger:
    """台帳を取得し、選挙台帳であることを確認する

    Args:
        supabase: Supabaseクライアント
        ledger_id: 台帳ID
        not_found_detail: 台帳不存在時のエラーメッセージ
        non_election_detail: 非選挙台帳時のエラーメッセージ

    Returns:
        PublicLedger: 選挙台帳

    Raises:
        HTTPException: 台帳が存在しない（404）、または選挙台帳でない（400）
    """
    ledger_response = (
        supabase.table("public_ledgers")
        .select("*")
        .eq("id", str(ledger_id))
        .maybe_single()
        .execute()
    )

    if not ledger_response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=not_found_detail,
        )

    if ledger_response.data.get("ledger_type") != "election_fund":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=non_election_detail,
        )

    return PublicLedger(**ledger_response.data)


def derive_type_from_classification(classification: str | None) -> str:
    """classificationからtypeを導出する

    Args:
        classification: 活動区分（campaign/pre-campaign）

    Returns:
        str: 種別（選挙運動/立候補準備）
    """
    if classification == "campaign":
        return "選挙運動"
    if classification == "pre-campaign":
        return "立候補準備"
    return "選挙運動"


def build_election_funds_response_for_ledger(
    supabase: Client,
    ledger_id: UUID,
    ledger: PublicLedger,
) -> schemas.ElectionFundsResponse:
    """取得済みの選挙台帳から選挙資金レスポンスを組み立てる

    Args:
        supabase: Supabaseクライアント
        ledger_id: 台帳ID（public_ledgers.id）
        ledger: 選挙台帳（politician_election_id が設定済みであること）

    Returns:
        schemas.ElectionFundsResponse: 選挙資金データ

    Raises:
        HTTPException: 関連データが見つからない場合（404）
    """
    # 中間テーブル経由で政治家・選挙情報を取得
    pol_elec_response = (
        supabase.table("politician_elections")
        .select(
            """
            id,
            politicians:politician_id(id, name, name_kana),
            elections:election_id(id, name, type, election_date, district_id)
            """
        )
        .eq("id", str(ledger.politician_election_id))
        .maybe_single()
        .execute()
    )

    if not pol_elec_response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="政治家・選挙情報が見つかりません",
        )

    pol_elec_data = pol_elec_response.data
    politician_data = pol_elec_data.get("politicians")
    election_data = pol_elec_data.get("elections")

    if not politician_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="政治家情報が見つかりません",
        )

    politician = schemas.PoliticianInfo(**politician_data)

    if not election_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="選挙情報が見つかりません",
        )

    district_response = (
        supabase.table("districts")
        .select("id, name")
        .eq("id", str(election_data["district_id"]))
        .maybe_single()
        .execute()
    )

    if not district_response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="選挙区情報が見つかりません",
        )

    district_data = district_response.data

    election_type_name = get_election_type_name(election_data["type"])
    election_type_response = (
        supabase.table("election_types")
        .select("code, name")
        .eq("code", election_data["type"])
        .maybe_single()
        .execute()
    )

    if election_type_response.data:
        election_type_name = election_type_response.data.get("name", election_type_name)

    election = schemas.ElectionInfo(
        id=UUID(election_data["id"]),
        name=election_data["name"],
        type=election_data["type"],
        type_name=election_type_name,
        district_id=UUID(district_data["id"]),
        district_name=district_data["name"],
        election_date=election_data["election_date"],
    )

    journals_response = (
        supabase.table("public_journals")
        .select("*")
        .eq("ledger_id", str(ledger_id))
        .order("date", desc=False)
        .execute()
    )

    journals_data = journals_response.data or []

    account_codes_list = [
        journal_data.get("account_code")
        for journal_data in journals_data
        if journal_data.get("account_code")
    ]
    account_codes_map: dict[str, str] = {}
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

    data_items: list[schemas.ElectionFundsDataItem] = []
    public_expense_totals = sum_public_expense_by_ledger(journals_data)
    public_expense_total = public_expense_totals.get(str(ledger_id), 0)

    for journal_data in journals_data:
        journal = PublicJournal(**journal_data)

        category = derive_category(journal.account_code)
        category_name = get_category_name(category)

        if journal.account_code and journal.account_code in account_codes_map:
            category_name = account_codes_map[journal.account_code]

        journal_type = derive_type_from_classification(journal.classification)
        public_expense_amount = normalize_public_expense_amount(
            journal.public_expense_amount
        )

        data_items.append(
            schemas.ElectionFundsDataItem(
                id=journal.id,
                date=journal.date,
                amount=journal.amount,
                category=category,
                category_name=category_name,
                type=journal_type,
                purpose=journal.description,
                non_monetary_basis=journal.non_monetary_basis,
                note=journal.note,
                public_expense_amount=public_expense_amount,
            )
        )

    summary = schemas.ElectionFundsSummary(
        total_income=ledger.total_income,
        total_expense=ledger.total_expense,
        balance=ledger.total_income - ledger.total_expense,
        public_expense_total=public_expense_total,
        journal_count=ledger.journal_count,
    )

    meta = schemas.ElectionFundsMeta(
        api_version="v1",
        politician=politician,
        election=election,
        summary=summary,
        generated_at=datetime.now(),
    )

    return schemas.ElectionFundsResponse(meta=meta, data=data_items)


def fetch_election_ledger_for_response(
    supabase: Client,
    ledger_id: UUID,
) -> PublicLedger:
    """選挙資金レスポンス用に台帳を取得する

    存在しない台帳・非選挙台帳はいずれも404として扱う。

    Args:
        supabase: Supabaseクライアント
        ledger_id: 台帳ID

    Returns:
        PublicLedger: 選挙台帳

    Raises:
        HTTPException: 台帳が見つからない、または選挙台帳でない場合（404）
    """
    ledger_response = (
        supabase.table("public_ledgers")
        .select("*")
        .eq("id", str(ledger_id))
        .eq("ledger_type", "election_fund")
        .maybe_single()
        .execute()
    )

    if not ledger_response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="選挙資金の台帳が見つかりません",
        )

    return PublicLedger(**ledger_response.data)


def build_election_funds_response(
    supabase: Client,
    ledger_id: UUID,
) -> schemas.ElectionFundsResponse:
    """台帳IDから選挙資金レスポンスを組み立てる

    Args:
        supabase: Supabaseクライアント
        ledger_id: 台帳ID（public_ledgers.id）

    Returns:
        schemas.ElectionFundsResponse: 選挙資金データ

    Raises:
        HTTPException: 台帳・関連データが見つからない場合（404）
    """
    ledger = fetch_election_ledger_for_response(supabase, ledger_id)
    return build_election_funds_response_for_ledger(supabase, ledger_id, ledger)
