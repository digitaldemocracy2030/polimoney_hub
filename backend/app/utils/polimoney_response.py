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


def build_politicians_list_response(
    supabase: Client,
) -> schemas.PoliticiansListResponse:
    """収支データ公開済み政治家一覧レスポンスを組み立てる

    public_ledgers（is_test=false）に紐づく政治家を重複なく返却する。
    政党名は organizations（type='political_party'）から、
    選挙区は最新の選挙から取得する。

    Args:
        supabase: Supabaseクライアント

    Returns:
        schemas.PoliticiansListResponse: 政治家一覧

    Raises:
        HTTPException: データ取得に失敗した場合
    """
    # 選挙台帳から政治家IDを収集
    election_ledgers_response = (
        supabase.table("public_ledgers")
        .select(
            """
            id,
            politician_elections:politician_election_id(
                politician_id,
                elections:election_id(
                    election_date,
                    district:districts(name)
                )
            )
            """
        )
        .eq("ledger_type", "election_fund")
        .eq("is_test", False)
        .execute()
    )

    # 政治資金台帳から政治家IDを収集
    political_ledgers_response = (
        supabase.table("public_ledgers")
        .select(
            """
            id,
            politician_organizations:politician_organization_id(
                politician_id
            )
            """
        )
        .eq("ledger_type", "political_fund")
        .eq("is_test", False)
        .execute()
    )

    # 政治家ごとの情報を集約
    # politician_id -> { ledger_count, latest_district, latest_election_date }
    politician_info: dict[str, dict] = {}

    for ledger in (election_ledgers_response.data or []):
        pol_elec = ledger.get("politician_elections")
        if not pol_elec:
            continue
        pid = pol_elec.get("politician_id")
        if not pid:
            continue

        info = politician_info.setdefault(pid, {
            "ledger_count": 0,
            "latest_district": None,
            "latest_election_date": None,
        })
        info["ledger_count"] += 1

        election_data = pol_elec.get("elections")
        if election_data:
            election_date = election_data.get("election_date")
            if election_date and (
                info["latest_election_date"] is None
                or election_date > info["latest_election_date"]
            ):
                info["latest_election_date"] = election_date
                district_data = election_data.get("district")
                info["latest_district"] = (
                    district_data.get("name") if district_data else None
                )

    for ledger in (political_ledgers_response.data or []):
        pol_org = ledger.get("politician_organizations")
        if not pol_org:
            continue
        pid = pol_org.get("politician_id")
        if not pid:
            continue

        info = politician_info.setdefault(pid, {
            "ledger_count": 0,
            "latest_district": None,
            "latest_election_date": None,
        })
        info["ledger_count"] += 1

    if not politician_info:
        return schemas.PoliticiansListResponse(data=[], total_count=0)

    politician_ids = list(politician_info.keys())

    # 政治家情報を取得
    politicians_response = (
        supabase.table("politicians")
        .select("id, name, name_kana, title, image_url")
        .in_("id", politician_ids)
        .execute()
    )

    if politicians_response.data is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="政治家一覧の取得に失敗しました",
        )

    # 政党名を取得（politician_organizations -> organizations）
    # is_active=true のみ取得し、updated_at DESC で最新の所属を優先する
    pol_orgs_response = (
        supabase.table("politician_organizations")
        .select(
            """
            politician_id,
            updated_at,
            organizations:organization_id(name, type)
            """
        )
        .in_("politician_id", politician_ids)
        .eq("is_active", True)
        .order("updated_at", desc=True)
        .execute()
    )

    party_map: dict[str, str] = {}
    for po in (pol_orgs_response.data or []):
        pid = po.get("politician_id")
        org = po.get("organizations")
        # updated_at DESC でソート済みなので、最初に見つかったものが最新の所属
        if pid and org and org.get("type") == "political_party" and pid not in party_map:
            party_map[pid] = org["name"]

    # レスポンス組み立て
    items: list[schemas.PoliticianListItem] = []
    for pol in politicians_response.data:
        pid = pol["id"]
        info = politician_info.get(pid, {})
        items.append(
            schemas.PoliticianListItem(
                id=UUID(pid),
                name=pol["name"],
                name_kana=pol.get("name_kana"),
                title=pol.get("title"),
                image_url=pol.get("image_url"),
                party=party_map.get(pid),
                district=info.get("latest_district"),
                ledger_count=info.get("ledger_count", 0),
            )
        )

    # 名前順でソート
    items.sort(key=lambda p: p.name)

    return schemas.PoliticiansListResponse(
        data=items,
        total_count=len(items),
    )

