"""Polimoney APIレスポンス組み立てユーティリティ

公開選挙一覧・候補者一覧・台帳解決など、Polimoney向けAPIのビジネスロジック。
"""

from uuid import UUID

from fastapi import HTTPException, status
from supabase import Client

from app import schemas
from app.utils.election_funds_response import (
    assert_election_exists,
    sum_public_expense_by_ledger,
)


class MultipleCandidatesException(Exception):
    """同一選挙に複数候補者が存在し politician_id が未指定の場合の例外

    Attributes:
        error: エラーレスポンス本体
    """

    def __init__(self, error: schemas.MultipleCandidatesError):
        self.error = error


def build_election_list_item(election_data: dict) -> schemas.ElectionListItem:
    """Supabaseの選挙データを一覧用レスポンスに変換する

    Args:
        election_data: elections テーブルの行（district ネスト含む）

    Returns:
        schemas.ElectionListItem: 選挙一覧の1件
    """
    district = election_data.get("district") or {}
    district_id = district.get("id")
    district_name = district.get("name")

    return schemas.ElectionListItem(
        id=UUID(election_data["id"]),
        name=election_data["name"],
        type=election_data["type"],
        election_date=election_data["election_date"],
        district_id=UUID(district_id) if district_id else None,
        district_name=district_name,
    )


def build_candidate_list_item(
    ledger_data: dict,
    public_expense_total: int,
) -> schemas.CandidateListItem | None:
    """Supabaseの台帳データを候補者一覧用レスポンスに変換する

    Args:
        ledger_data: public_ledgers の行（politician_elections ネスト含む）
        public_expense_total: 公費負担合計

    Returns:
        schemas.CandidateListItem | None: 候補者一覧の1件。政治家情報が欠落時は None
    """
    pol_elec_data = ledger_data.get("politician_elections")
    if not pol_elec_data:
        return None

    politician_data = pol_elec_data.get("politicians")
    if not politician_data:
        return None

    total_income = ledger_data.get("total_income") or 0
    total_expense = ledger_data.get("total_expense") or 0

    return schemas.CandidateListItem(
        ledger_id=UUID(ledger_data["id"]),
        politician=politician_data,
        summary=schemas.ElectionFundsSummary(
            total_income=total_income,
            total_expense=total_expense,
            balance=total_income - total_expense,
            public_expense_total=public_expense_total,
            journal_count=ledger_data.get("journal_count") or 0,
        ),
    )


def build_elections_list_response(supabase: Client) -> schemas.ElectionsListResponse:
    """公開済み選挙一覧レスポンスを組み立てる

    Args:
        supabase: Supabaseクライアント

    Returns:
        schemas.ElectionsListResponse: 公開済み選挙一覧

    Raises:
        HTTPException: データ取得に失敗した場合
    """
    # 選挙台帳から中間テーブル経由で選挙情報を取得
    ledgers_response = (
        supabase.table("public_ledgers")
        .select(
            """
            politician_election_id,
            politician_elections:politician_election_id(
                election_id,
                elections:election_id(
                    id,
                    name,
                    type,
                    election_date,
                    district:districts(id, name)
                )
            )
            """
        )
        .eq("ledger_type", "election_fund")
        .execute()
    )

    if ledgers_response.data is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="選挙一覧の取得に失敗しました",
        )

    election_map: dict[str, dict] = {}
    for ledger in ledgers_response.data:
        pol_elec = ledger.get("politician_elections")
        if not pol_elec:
            continue
        election_data = pol_elec.get("elections")
        if election_data and election_data["id"] not in election_map:
            election_map[election_data["id"]] = election_data

    elections = [
        build_election_list_item(election_data)
        for election_data in election_map.values()
    ]
    elections.sort(key=lambda e: e.election_date, reverse=True)

    return schemas.ElectionsListResponse(
        data=elections,
        total_count=len(elections),
    )


def resolve_ledger_for_election(
    supabase: Client,
    election_id: UUID,
    politician_id: UUID | None,
) -> UUID:
    """選挙IDから対象台帳IDを解決する

    Args:
        supabase: Supabaseクライアント
        election_id: 選挙ID
        politician_id: 政治家ID（複数候補時は必須）

    Returns:
        UUID: 解決された台帳ID

    Raises:
        HTTPException: 選挙・台帳が見つからない場合（404）
        MultipleCandidatesException: 複数候補者かつ politician_id 未指定（400）
    """
    assert_election_exists(supabase, election_id)

    # 中間テーブルから該当する politician_election_id を検索
    pe_query = (
        supabase.table("politician_elections")
        .select("id, politician_id")
        .eq("election_id", str(election_id))
    )

    if politician_id is not None:
        pe_query = pe_query.eq("politician_id", str(politician_id))

    pe_response = pe_query.execute()

    if not pe_response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="選挙資金の台帳が見つかりません",
        )

    pe_ids = [pe["id"] for pe in pe_response.data]

    # public_ledgers から該当する台帳を取得
    ledger_query = (
        supabase.table("public_ledgers")
        .select("id, politician_election_id")
        .in_("politician_election_id", pe_ids)
        .eq("ledger_type", "election_fund")
    )

    ledgers_response = ledger_query.execute()

    if ledgers_response.data is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="選挙収支データの取得に失敗しました",
        )

    ledgers = ledgers_response.data

    if len(ledgers) == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="選挙資金の台帳が見つかりません",
        )

    if len(ledgers) > 1 and politician_id is None:
        # 複数候補者の politician_id を取得
        pe_map = {pe["id"]: pe["politician_id"] for pe in pe_response.data}
        raise MultipleCandidatesException(
            schemas.MultipleCandidatesError(
                error="同一選挙に複数候補者が存在します。politician_id を指定してください。",
                candidates=[
                    schemas.CandidateRef(
                        politician_id=UUID(pe_map[ledger["politician_election_id"]]),
                        ledger_id=UUID(ledger["id"]),
                    )
                    for ledger in ledgers
                    if ledger["politician_election_id"] in pe_map
                ],
            )
        )

    return UUID(ledgers[0]["id"])


def build_election_candidates_response(
    supabase: Client,
    election_id: UUID,
) -> schemas.ElectionCandidatesResponse:
    """選挙候補者一覧レスポンスを組み立てる

    Args:
        supabase: Supabaseクライアント
        election_id: 選挙ID

    Returns:
        schemas.ElectionCandidatesResponse: 候補者一覧

    Raises:
        HTTPException: 候補者が見つからない、またはデータ取得に失敗した場合
    """
    assert_election_exists(supabase, election_id)

    # 中間テーブルから該当する politician_election を取得
    pe_response = (
        supabase.table("politician_elections")
        .select("id")
        .eq("election_id", str(election_id))
        .execute()
    )

    if not pe_response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="該当選挙の候補者が見つかりません",
        )

    pe_ids = [pe["id"] for pe in pe_response.data]

    # public_ledgers から中間テーブル経由で政治家情報も取得
    ledgers_response = (
        supabase.table("public_ledgers")
        .select(
            """
            id,
            total_income,
            total_expense,
            journal_count,
            politician_elections:politician_election_id(
                id,
                politician_id,
                politicians:politician_id(id, name, name_kana)
            )
            """
        )
        .in_("politician_election_id", pe_ids)
        .eq("ledger_type", "election_fund")
        .execute()
    )

    if ledgers_response.data is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="候補者一覧の取得に失敗しました",
        )

    ledgers = ledgers_response.data
    if len(ledgers) == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="該当選挙の候補者が見つかりません",
        )

    ledger_ids = [ledger["id"] for ledger in ledgers]
    journals_response = (
        supabase.table("public_journals")
        .select("ledger_id, public_expense_amount")
        .in_("ledger_id", ledger_ids)
        .execute()
    )

    if journals_response.data is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="候補者一覧の取得に失敗しました",
        )

    public_expense_totals = sum_public_expense_by_ledger(journals_response.data)

    candidates: list[schemas.CandidateListItem] = []
    for ledger in ledgers:
        item = build_candidate_list_item(
            ledger,
            public_expense_totals.get(ledger["id"], 0),
        )
        if item is not None:
            candidates.append(item)

    if len(candidates) == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="該当選挙の候補者が見つかりません",
        )

    return schemas.ElectionCandidatesResponse(
        election_id=election_id,
        data=candidates,
        total_count=len(candidates),
    )
