"""本人確認の審査 API（Hub 管理者専用、/api/admin/*）

- 承認できるのは、メールまたは DNS の確認が済んだ申請（email_verified / dns_verified）だけ
- 政治家の承認: 申請者（ledger_user_id）の政治家があれば認証済みに更新し、無ければ作る
- 政治団体の管理者の承認: 団体を認証済みにし（無ければ作る）、organization_managers に登録する
- 作る・更新する行の is_test は申請の is_test に合わせる（テストデータは本番データと混ざらない）
- 承認は DB の関数（db/migrate-verification-test-and-attempts.sql）で 1 つのトランザクションとして行う。
  申請の行をロックしてから状態を確かめるので、同時の却下と競合しても、途中で失敗しても、
  政治家・団体だけが認証済みになって残ることはない
"""

from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from postgrest.exceptions import APIError
from supabase import Client

from app.core.admin_auth import AdminUser, require_admin_user
from app.database.supabase import get_admin_supabase_client_dep
from app.routers.verifications import (
    ORGANIZATION_MANAGER,
    POLITICIAN,
    VerificationKind,
    _server_error,
)
from app.schemas.verification import RejectVerificationRequest
from app.services.verification import (
    CLOSED_STATUSES,
    public_view,
    utc_now,
)

router = APIRouter()

StatusFilter = Literal[
    "pending", "email_sent", "email_verified", "dns_verified", "approved", "rejected"
]

# 承認の DB 関数が返すエラー（RAISE EXCEPTION のメッセージ）と応答
APPROVE_ERRORS = {
    "verification_not_found": (status.HTTP_404_NOT_FOUND, "申請が見つかりません"),
    "verification_not_confirmed": (
        status.HTTP_409_CONFLICT,
        "メールまたは DNS の確認が済んでいない申請は承認できません",
    ),
    "organization_not_found": (status.HTTP_404_NOT_FOUND, "申請の政治団体が見つかりません"),
}


@router.get("/me")
def get_me(admin: AdminUser = Depends(require_admin_user)):
    """ログイン中の管理者"""
    return {"data": {"id": admin.id, "email": admin.email, "name": admin.name, "role": admin.role}}


def _list(
    supabase: Client,
    kind: VerificationKind,
    status_filter: Optional[str],
    is_test: Optional[bool],
) -> dict:
    try:
        query = supabase.table(kind.table).select("*")
        if status_filter:
            query = query.eq("status", status_filter)
        if is_test is not None:
            query = query.eq("is_test", is_test)
        rows = query.order("created_at", desc=True).limit(200).execute().data
    except Exception as e:
        raise _server_error("申請の取得に失敗しました", e) from e
    return {"data": [public_view(row) for row in rows]}


def _get(supabase: Client, kind: VerificationKind, verification_id: UUID) -> dict:
    try:
        rows = (
            supabase.table(kind.table)
            .select("*")
            .eq("id", str(verification_id))
            .limit(1)
            .execute()
            .data
        )
    except Exception as e:
        raise _server_error("申請の取得に失敗しました", e) from e
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="申請が見つかりません")
    return rows[0]


def _approve(
    supabase: Client, function: str, verification_id: UUID, admin: AdminUser
) -> dict:
    """承認の DB 関数を呼ぶ（関連行の登録と申請の更新を 1 つのトランザクションで行う）"""
    try:
        data = (
            supabase.rpc(
                function,
                {"p_verification_id": str(verification_id), "p_reviewer_id": admin.id},
            )
            .execute()
            .data
        )
    except APIError as e:
        known = APPROVE_ERRORS.get(e.message or "")
        if known:
            raise HTTPException(status_code=known[0], detail=known[1]) from e
        raise _server_error("承認に失敗しました", e) from e
    except Exception as e:
        raise _server_error("承認に失敗しました", e) from e
    row = data[0] if isinstance(data, list) else data
    if not row:
        raise _server_error("承認に失敗しました", Exception(f"{function} returned no row"))
    return {"data": public_view(row)}


def _reject(
    supabase: Client,
    kind: VerificationKind,
    verification_id: UUID,
    body: RejectVerificationRequest,
    admin: AdminUser,
) -> dict:
    verification = _get(supabase, kind, verification_id)
    if verification["status"] in CLOSED_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="承認済み・却下済みの申請は却下できません",
        )
    now = utc_now().isoformat()
    try:
        # 読み取ったときの状態のままなら却下する（承認と同時なら、承認の DB 関数が持つ
        # 行ロックが外れるのを待ってから判定されるので、承認済みの申請を却下にはしない）
        rows = (
            supabase.table(kind.table)
            .update(
                {
                    "status": "rejected",
                    "rejection_reason": body.rejection_reason.strip(),
                    "reviewed_by": admin.id,
                    "reviewed_at": now,
                    "updated_at": now,
                }
            )
            .eq("id", verification["id"])
            .eq("status", verification["status"])
            .execute()
            .data
        )
    except Exception as e:
        raise _server_error("申請の更新に失敗しました", e) from e
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="申請の状態が変わりました。画面を再読み込みしてください",
        )
    return {"data": public_view(rows[0])}


# ============================================
# 政治家の本人確認
# ============================================


@router.get("/politician-verifications")
def list_politician_verifications(
    status_filter: Optional[StatusFilter] = Query(None, alias="status"),
    is_test: Optional[bool] = None,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    _admin: AdminUser = Depends(require_admin_user),
):
    """政治家の本人確認の申請一覧（新しい順、最大 200 件）"""
    return _list(supabase, POLITICIAN, status_filter, is_test)


@router.get("/politician-verifications/{verification_id}")
def get_politician_verification(
    verification_id: UUID,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    _admin: AdminUser = Depends(require_admin_user),
):
    return {"data": public_view(_get(supabase, POLITICIAN, verification_id))}


@router.post("/politician-verifications/{verification_id}/approve")
def approve_politician_verification(
    verification_id: UUID,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    admin: AdminUser = Depends(require_admin_user),
):
    """承認する。申請者の政治家を認証済みにする（無ければ作る）"""
    return _approve(supabase, "approve_politician_verification", verification_id, admin)


@router.post("/politician-verifications/{verification_id}/reject")
def reject_politician_verification(
    verification_id: UUID,
    body: RejectVerificationRequest,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    admin: AdminUser = Depends(require_admin_user),
):
    return _reject(supabase, POLITICIAN, verification_id, body, admin)


# ============================================
# 政治団体の管理者の本人確認
# ============================================


@router.get("/organization-manager-verifications")
def list_organization_manager_verifications(
    status_filter: Optional[StatusFilter] = Query(None, alias="status"),
    is_test: Optional[bool] = None,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    _admin: AdminUser = Depends(require_admin_user),
):
    """政治団体の管理者の本人確認の申請一覧（新しい順、最大 200 件）"""
    return _list(supabase, ORGANIZATION_MANAGER, status_filter, is_test)


@router.get("/organization-manager-verifications/{verification_id}")
def get_organization_manager_verification(
    verification_id: UUID,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    _admin: AdminUser = Depends(require_admin_user),
):
    return {"data": public_view(_get(supabase, ORGANIZATION_MANAGER, verification_id))}


@router.post("/organization-manager-verifications/{verification_id}/approve")
def approve_organization_manager_verification(
    verification_id: UUID,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    admin: AdminUser = Depends(require_admin_user),
):
    """承認する。団体を認証済みにし（無ければ作る）、申請者を団体の管理者にする"""
    return _approve(
        supabase, "approve_organization_manager_verification", verification_id, admin
    )


@router.post("/organization-manager-verifications/{verification_id}/reject")
def reject_organization_manager_verification(
    verification_id: UUID,
    body: RejectVerificationRequest,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    admin: AdminUser = Depends(require_admin_user),
):
    return _reject(supabase, ORGANIZATION_MANAGER, verification_id, body, admin)
