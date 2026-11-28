"""登録申請（選挙・政治団体）と年度のロック解除申請の審査 API（Hub 管理者専用、/api/admin/*）

- 承認・却下できるのは審査中（pending）の申請だけ
- 選挙・政治団体の承認: 申請の内容でマスタの行を作る。既存の行を指定した場合は、それに紐付ける（作らない）。
  作る・紐付ける行の is_test は申請の is_test に合わせる。
  DB の関数（db/migrate-request-review.sql）で、申請の行をロックしてから 1 つのトランザクションで行う
- ロック解除の承認: 期限（unlock_expires_at）を決めて承認する。Ledger は期限内だけ年度を解除する
- 却下: 読み取ったときの状態のままなら却下する（同時の承認と競合したら 409）
"""

from datetime import timedelta
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from postgrest.exceptions import APIError
from supabase import Client

from app.core.admin_auth import AdminUser, require_admin_user
from app.database.supabase import get_admin_supabase_client_dep
from app.routers.ledger_requests import (
    ELECTION_REQUESTS,
    ORGANIZATION_REQUESTS,
    UNLOCK_REQUESTS,
    server_error,
)
from app.schemas.ledger_request import (
    ApproveElectionRequest,
    ApproveOrganizationRequest,
    ApproveUnlockRequest,
    RejectRequest,
)
from app.services.verification import utc_now

router = APIRouter()

StatusFilter = Literal["pending", "approved", "rejected"]

# 承認の DB 関数が返すエラー（RAISE EXCEPTION のメッセージ）と応答
APPROVE_ERRORS = {
    "request_not_found": (status.HTTP_404_NOT_FOUND, "申請が見つかりません"),
    "request_not_pending": (status.HTTP_409_CONFLICT, "審査中の申請ではありません"),
    "election_not_found": (status.HTTP_404_NOT_FOUND, "指定した選挙が見つかりません"),
    "organization_not_found": (status.HTTP_404_NOT_FOUND, "指定した政治団体が見つかりません"),
}

STATE_CHANGED = "申請の状態が変わりました。画面を再読み込みしてください"


def _list(
    supabase: Client, table: str, status_filter: Optional[str], is_test: Optional[bool]
) -> dict:
    try:
        query = supabase.table(table).select("*")
        if status_filter:
            query = query.eq("status", status_filter)
        if is_test is not None:
            query = query.eq("is_test", is_test)
        rows = query.order("created_at", desc=True).limit(200).execute().data
    except Exception as e:
        raise server_error("申請の取得に失敗しました", e) from e
    return {"data": rows}


def _get(supabase: Client, table: str, request_id: UUID) -> dict:
    try:
        rows = (
            supabase.table(table).select("*").eq("id", str(request_id)).limit(1).execute().data
        )
    except Exception as e:
        raise server_error("申請の取得に失敗しました", e) from e
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="申請が見つかりません")
    return rows[0]


def _require_pending(row: dict, action: str) -> None:
    if row.get("status") != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"審査中の申請だけを{action}できます",
        )


def _update_if_pending(supabase: Client, table: str, row: dict, fields: dict) -> dict:
    """読み取ったときと同じく審査中なら更新する。同時に審査されて変わっていたら 409"""
    try:
        rows = (
            supabase.table(table)
            .update(fields)
            .eq("id", row["id"])
            .eq("status", "pending")
            .execute()
            .data
        )
    except Exception as e:
        raise server_error("申請の更新に失敗しました", e) from e
    if not rows:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=STATE_CHANGED)
    return rows[0]


def _approve_with_function(supabase: Client, function: str, params: dict) -> dict:
    """承認の DB 関数を呼ぶ（マスタの行の作成と申請の更新を 1 つのトランザクションで行う）"""
    try:
        data = supabase.rpc(function, params).execute().data
    except APIError as e:
        known = APPROVE_ERRORS.get(e.message or "")
        if known:
            raise HTTPException(status_code=known[0], detail=known[1]) from e
        raise server_error("承認に失敗しました", e) from e
    except Exception as e:
        raise server_error("承認に失敗しました", e) from e
    row = data[0] if isinstance(data, list) else data
    if not row:
        raise server_error("承認に失敗しました", Exception(f"{function} returned no row"))
    return {"data": row}


def _reject_master_request(
    supabase: Client, table: str, request_id: UUID, body: RejectRequest, admin: AdminUser
) -> dict:
    row = _get(supabase, table, request_id)
    _require_pending(row, "却下")
    now = utc_now().isoformat()
    updated = _update_if_pending(
        supabase,
        table,
        row,
        {
            "status": "rejected",
            "rejection_reason": body.rejection_reason.strip(),
            "reviewed_by": admin.id,
            "reviewed_at": now,
            "updated_at": now,
        },
    )
    return {"data": updated}


# ============================================
# 選挙の登録申請
# ============================================


@router.get("/election-requests")
def list_election_requests(
    status_filter: Optional[StatusFilter] = Query(None, alias="status"),
    is_test: Optional[bool] = None,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    _admin: AdminUser = Depends(require_admin_user),
):
    """選挙の登録申請の一覧（新しい順、最大 200 件）"""
    return _list(supabase, ELECTION_REQUESTS, status_filter, is_test)


@router.get("/election-requests/{request_id}")
def get_election_request(
    request_id: UUID,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    _admin: AdminUser = Depends(require_admin_user),
):
    return {"data": _get(supabase, ELECTION_REQUESTS, request_id)}


@router.post("/election-requests/{request_id}/approve")
def approve_election_request(
    request_id: UUID,
    body: Optional[ApproveElectionRequest] = None,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    admin: AdminUser = Depends(require_admin_user),
):
    """承認する。選挙を作る（election_id を指定したら既存の選挙に紐付ける）"""
    election_id = body.election_id if body else None
    return _approve_with_function(
        supabase,
        "approve_election_request",
        {
            "p_request_id": str(request_id),
            "p_reviewer_id": admin.id,
            "p_election_id": str(election_id) if election_id else None,
        },
    )


@router.post("/election-requests/{request_id}/reject")
def reject_election_request(
    request_id: UUID,
    body: RejectRequest,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    admin: AdminUser = Depends(require_admin_user),
):
    return _reject_master_request(supabase, ELECTION_REQUESTS, request_id, body, admin)


# ============================================
# 政治団体の登録申請
# ============================================


@router.get("/organization-requests")
def list_organization_requests(
    status_filter: Optional[StatusFilter] = Query(None, alias="status"),
    is_test: Optional[bool] = None,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    _admin: AdminUser = Depends(require_admin_user),
):
    """政治団体の登録申請の一覧（新しい順、最大 200 件）"""
    return _list(supabase, ORGANIZATION_REQUESTS, status_filter, is_test)


@router.get("/organization-requests/{request_id}")
def get_organization_request(
    request_id: UUID,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    _admin: AdminUser = Depends(require_admin_user),
):
    return {"data": _get(supabase, ORGANIZATION_REQUESTS, request_id)}


@router.post("/organization-requests/{request_id}/approve")
def approve_organization_request(
    request_id: UUID,
    body: Optional[ApproveOrganizationRequest] = None,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    admin: AdminUser = Depends(require_admin_user),
):
    """承認する。政治団体を作る（organization_id を指定したら既存の団体に紐付ける）"""
    organization_id = body.organization_id if body else None
    return _approve_with_function(
        supabase,
        "approve_organization_request",
        {
            "p_request_id": str(request_id),
            "p_reviewer_id": admin.id,
            "p_organization_id": str(organization_id) if organization_id else None,
        },
    )


@router.post("/organization-requests/{request_id}/reject")
def reject_organization_request(
    request_id: UUID,
    body: RejectRequest,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    admin: AdminUser = Depends(require_admin_user),
):
    return _reject_master_request(supabase, ORGANIZATION_REQUESTS, request_id, body, admin)


# ============================================
# 年度のロック解除申請
# ============================================


@router.get("/unlock-requests")
def list_unlock_requests(
    status_filter: Optional[StatusFilter] = Query(None, alias="status"),
    is_test: Optional[bool] = None,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    _admin: AdminUser = Depends(require_admin_user),
):
    """ロック解除の申請の一覧（新しい順、最大 200 件）"""
    return _list(supabase, UNLOCK_REQUESTS, status_filter, is_test)


@router.get("/unlock-requests/{request_id}")
def get_unlock_request(
    request_id: UUID,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    _admin: AdminUser = Depends(require_admin_user),
):
    return {"data": _get(supabase, UNLOCK_REQUESTS, request_id)}


@router.post("/unlock-requests/{request_id}/approve")
def approve_unlock_request(
    request_id: UUID,
    body: Optional[ApproveUnlockRequest] = None,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    admin: AdminUser = Depends(require_admin_user),
):
    """承認する。unlock_hours（既定 7 日）の間、年度のロックを解除する"""
    hours = (body or ApproveUnlockRequest()).unlock_hours
    row = _get(supabase, UNLOCK_REQUESTS, request_id)
    _require_pending(row, "承認")
    now = utc_now()
    updated = _update_if_pending(
        supabase,
        UNLOCK_REQUESTS,
        row,
        {
            "status": "approved",
            "approved_at": now.isoformat(),
            "approved_by": admin.id,
            "unlock_expires_at": (now + timedelta(hours=hours)).isoformat(),
            "updated_at": now.isoformat(),
        },
    )
    return {"data": updated}


@router.post("/unlock-requests/{request_id}/reject")
def reject_unlock_request(
    request_id: UUID,
    body: RejectRequest,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    _admin: AdminUser = Depends(require_admin_user),
):
    row = _get(supabase, UNLOCK_REQUESTS, request_id)
    _require_pending(row, "却下")
    updated = _update_if_pending(
        supabase,
        UNLOCK_REQUESTS,
        row,
        {
            "status": "rejected",
            "rejection_reason": body.rejection_reason.strip(),
            "updated_at": utc_now().isoformat(),
        },
    )
    return {"data": updated}
