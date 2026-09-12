"""Polimoney APIエンドポイント

公開済み選挙データの一覧取得など、Polimoney向けAPIを提供する。
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from supabase import Client

from app import schemas
from app.database.supabase import get_supabase_client_dep
from app.utils.election_funds_response import (
    build_election_funds_response,
    build_election_funds_response_for_ledger,
    fetch_election_ledger_or_raise,
)
from app.utils.polimoney_response import (
    build_election_candidates_response,
    build_elections_list_response,
    build_politicians_list_response,
    resolve_ledger_for_election,
)

router = APIRouter(prefix="/polimoney")


@router.get(
    "/politicians",
    response_model=schemas.PoliticiansListResponse,
)
async def get_polimoney_politicians(
    supabase: Client = Depends(get_supabase_client_dep),
):
    """収支データが公開されている政治家の一覧を取得する

    public_ledgers（is_test=false）に紐づく政治家のみ返却する。
    政党名・選挙区名・公開台帳数を含む。

    Args:
        supabase: Supabaseクライアント

    Returns:
        schemas.PoliticiansListResponse: 政治家一覧

    Raises:
        HTTPException: データ取得に失敗した場合
    """
    return build_politicians_list_response(supabase)


@router.get(
    "/elections",
    response_model=schemas.ElectionsListResponse,
)
async def get_polimoney_elections(
    supabase: Client = Depends(get_supabase_client_dep),
):
    """収支データが公開されている選挙の一覧を取得する

    public_ledgers に election_id が設定されている選挙のみ返却する。
    同一選挙に複数候補者の台帳がある場合は重複を除去する。

    Args:
        supabase: Supabaseクライアント

    Returns:
        schemas.ElectionsListResponse: 公開済み選挙一覧

    Raises:
        HTTPException: データ取得に失敗した場合
    """
    return build_elections_list_response(supabase)


@router.get(
    "/elections/{election_id}/journals",
    response_model=schemas.ElectionFundsResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": schemas.MultipleCandidatesError},
    },
)
async def get_polimoney_election_journals(
    election_id: UUID,
    politician_id: UUID | None = Query(
        default=None,
        description="政治家 ID（同じ選挙に複数候補者がいる場合は必須）",
    ),
    supabase: Client = Depends(get_supabase_client_dep),
):
    """指定選挙の収支データを Polimoney JSON 形式で取得する

    該当選挙の public_ledgers を解決し、仕訳一覧とメタ情報を返却する。
    同一選挙に複数候補者がいる場合は politician_id の指定が必須。

    Args:
        election_id: 選挙ID
        politician_id: 政治家ID（複数候補時は必須）
        supabase: Supabaseクライアント

    Returns:
        schemas.ElectionFundsResponse: 選挙収支データ

    Raises:
        HTTPException: 選挙・台帳が見つからない場合（404）
        MultipleCandidatesException: 複数候補者かつ politician_id 未指定（400）
    """
    ledger_id = resolve_ledger_for_election(supabase, election_id, politician_id)
    return build_election_funds_response(supabase, ledger_id)


@router.get(
    "/elections/{election_id}/candidates",
    response_model=schemas.ElectionCandidatesResponse,
)
async def get_polimoney_election_candidates(
    election_id: UUID,
    supabase: Client = Depends(get_supabase_client_dep),
):
    """指定選挙の候補者（収支データ公開済み）一覧を取得する

    該当選挙に紐づく public_ledgers と政治家情報を返却する。

    Args:
        election_id: 選挙ID
        supabase: Supabaseクライアント

    Returns:
        schemas.ElectionCandidatesResponse: 候補者一覧

    Raises:
        HTTPException: 候補者が見つからない、またはデータ取得に失敗した場合
    """
    return build_election_candidates_response(supabase, election_id)


@router.get(
    "/ledgers/{ledger_id}/journals",
    response_model=schemas.ElectionFundsResponse,
)
async def get_polimoney_ledger_journals(
    ledger_id: UUID,
    supabase: Client = Depends(get_supabase_client_dep),
):
    """台帳IDを指定して収支データを Polimoney JSON 形式で取得する

    選挙台帳（election_id が設定されている台帳）のみ対応する。

    Args:
        ledger_id: 台帳ID（public_ledgers.id）
        supabase: Supabaseクライアント

    Returns:
        schemas.ElectionFundsResponse: 収支データ

    Raises:
        HTTPException:
            - 404: 台帳が存在しない場合
            - 400: 選挙台帳以外の場合
    """
    ledger = fetch_election_ledger_or_raise(supabase, ledger_id)
    return build_election_funds_response_for_ledger(supabase, ledger_id, ledger)
