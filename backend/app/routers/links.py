"""政治家との紐付け API（Ledger 専用）

- 政治家 ↔ 選挙（politician_elections）: Ledger で選挙運動費用の台帳を作るときに取得・作成する
- 政治家 ↔ 政治団体（politician_organizations）: 代表者の紐付けを引くだけ。作成は Hub の管理者が行う
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from supabase import Client

from app.core.api_key import LedgerApiCaller, require_ledger_api_key
from app.database.supabase import get_admin_supabase_client_dep
from app.schemas.hub_master import (
    PoliticianElectionRequest,
    PoliticianElectionResponse,
    PoliticianOrganizationResolveRequest,
    PoliticianOrganizationResponse,
)
from app.utils.test_scope import apply_test_scope

router = APIRouter()

UNIQUE_VIOLATION = "23505"


def _server_error(message: str, e: Exception) -> HTTPException:
    print(f"[Links] {message}: {e}")
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=message,
    )


def _find_politician_election(
    supabase: Client, politician_id: str, election_id: str
) -> Optional[dict]:
    result = (
        supabase.table("politician_elections")
        .select("id, politician_id, election_id")
        .eq("politician_id", politician_id)
        .eq("election_id", election_id)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


@router.post(
    "/politician-elections",
    response_model=PoliticianElectionResponse,
    responses={201: {"model": PoliticianElectionResponse}},
)
async def get_or_create_politician_election(
    body: PoliticianElectionRequest,
    response: Response,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    caller: LedgerApiCaller = Depends(require_ledger_api_key),
):
    """政治家と選挙の紐付けを返す。無ければ作る

    - 政治家: 認証済み（is_verified）で、ledger_user_id がリクエストの ledger_user_id と一致すること（違えば 403）
    - 選挙: 存在して有効（is_active）であること（違えば 404）

    既存の紐付けを返したときは 200（action: existing）、作成したときは 201（action: created）。
    """
    politician_id = str(body.politician_id)
    election_id = str(body.election_id)

    try:
        politician_query = (
            supabase.table("politicians")
            .select("id, ledger_user_id, is_verified")
            .eq("id", politician_id)
        )
        politicians = apply_test_scope(politician_query, caller).limit(1).execute().data
    except Exception as e:
        raise _server_error("政治家の取得に失敗しました", e)

    politician = politicians[0] if politicians else None
    if (
        not politician
        or not politician.get("is_verified")
        or politician.get("ledger_user_id") != str(body.ledger_user_id)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="この政治家を選挙に紐付ける権限がありません（本人確認済みの政治家本人のみ紐付けできます）",
        )

    try:
        election_query = (
            supabase.table("elections").select("id, is_active").eq("id", election_id)
        )
        elections = apply_test_scope(election_query, caller).limit(1).execute().data
    except Exception as e:
        raise _server_error("選挙の取得に失敗しました", e)

    if not elections or not elections[0].get("is_active"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="選挙が見つかりません",
        )

    try:
        existing = _find_politician_election(supabase, politician_id, election_id)
    except Exception as e:
        raise _server_error("政治家と選挙の紐付けの取得に失敗しました", e)
    if existing:
        return {"data": existing, "action": "existing"}

    try:
        inserted = (
            supabase.table("politician_elections")
            .insert({"politician_id": politician_id, "election_id": election_id})
            .execute()
        )
        row = inserted.data[0]
    except Exception as e:
        # 同時に作成された場合（UNIQUE 制約違反）は作成済みの行を返す
        if getattr(e, "code", None) != UNIQUE_VIOLATION:
            raise _server_error("政治家と選挙の紐付けの作成に失敗しました", e)
        try:
            existing = _find_politician_election(supabase, politician_id, election_id)
        except Exception as e2:
            raise _server_error("政治家と選挙の紐付けの取得に失敗しました", e2)
        if not existing:
            raise _server_error("政治家と選挙の紐付けの作成に失敗しました", e)
        return {"data": existing, "action": "existing"}

    response.status_code = status.HTTP_201_CREATED
    return {
        "data": {
            "id": row["id"],
            "politician_id": row["politician_id"],
            "election_id": row["election_id"],
        },
        "action": "created",
    }


@router.post(
    "/politician-organizations/resolve",
    response_model=PoliticianOrganizationResponse,
)
async def resolve_politician_organization(
    body: PoliticianOrganizationResolveRequest,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    caller: LedgerApiCaller = Depends(require_ledger_api_key),
):
    """政治団体の代表者（role = 'representative'）の紐付けを返す

    Ledger ユーザーがその団体の有効な管理者（organization_managers）であるか、
    代表者の政治家本人（politicians.ledger_user_id）であること（違えば 403）。
    有効な代表者の紐付けがちょうど 1 件のときだけ返し、0 件・複数件は 409。
    紐付けはここでは作らない（Hub の管理者が設定する）。
    """
    ledger_user_id = str(body.ledger_user_id)
    organization_id = str(body.organization_id)

    try:
        org_query = supabase.table("organizations").select("id").eq("id", organization_id)
        orgs = apply_test_scope(org_query, caller).limit(1).execute().data
    except Exception as e:
        raise _server_error("政治団体の取得に失敗しました", e)
    if not orgs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="政治団体が見つかりません",
        )

    try:
        links = (
            supabase.table("politician_organizations")
            .select("id, politician_id, organization_id, role")
            .eq("organization_id", organization_id)
            .eq("role", "representative")
            .eq("is_active", True)
            .execute()
            .data
            or []
        )

        manager_query = (
            supabase.table("organization_managers")
            .select("id")
            .eq("ledger_user_id", ledger_user_id)
            .eq("organization_id", organization_id)
            .eq("is_active", True)
        )
        is_manager = bool(apply_test_scope(manager_query, caller).limit(1).execute().data)

        is_representative = False
        if not is_manager and links:
            rep_query = (
                supabase.table("politicians")
                .select("id")
                .in_("id", [link["politician_id"] for link in links])
                .eq("ledger_user_id", ledger_user_id)
            )
            is_representative = bool(
                apply_test_scope(rep_query, caller).limit(1).execute().data
            )
    except Exception as e:
        raise _server_error("政治団体の代表者の取得に失敗しました", e)

    if not is_manager and not is_representative:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="この政治団体の管理者または代表者ではありません",
        )

    if not links:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="この政治団体には代表者の紐付けがありません。Polimoney Hub の管理者に設定を依頼してください",
        )
    if len(links) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="この政治団体には代表者の紐付けが複数あります。Polimoney Hub の管理者に確認を依頼してください",
        )

    return {"data": links[0]}
