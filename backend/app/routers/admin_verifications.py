"""本人確認の審査 API（Hub 管理者専用、/api/admin/*）

- 承認できるのは、メールまたは DNS の確認が済んだ申請（email_verified / dns_verified）だけ
- 政治家の承認: 申請者（ledger_user_id）の政治家があれば認証済みに更新し、無ければ作る
- 政治団体の管理者の承認: 団体を認証済みにし（無ければ作る）、organization_managers に登録する
- 作る・更新する行の is_test は申請の is_test に合わせる（テストデータは本番データと混ざらない）
"""

from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from supabase import Client

from app.core.admin_auth import AdminUser, require_admin_user
from app.core.api_key import LedgerApiCaller
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
    CONFIRMED_STATUSES,
    public_view,
    utc_now,
)
from app.utils.test_scope import apply_test_scope

router = APIRouter()

StatusFilter = Literal[
    "pending", "email_sent", "email_verified", "dns_verified", "approved", "rejected"
]


@router.get("/me")
async def get_me(admin: AdminUser = Depends(require_admin_user)):
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
        raise _server_error("申請の取得に失敗しました", e)
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
        raise _server_error("申請の取得に失敗しました", e)
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="申請が見つかりません")
    return rows[0]


def _close(
    supabase: Client,
    kind: VerificationKind,
    verification: dict,
    fields: dict,
    expected_statuses: list[str],
) -> dict:
    """申請を承認・却下にする。その間に状態が変わっていたら 409"""
    try:
        rows = (
            supabase.table(kind.table)
            .update({**fields, "updated_at": utc_now().isoformat()})
            .eq("id", verification["id"])
            .in_("status", expected_statuses)
            .execute()
            .data
        )
    except Exception as e:
        raise _server_error("申請の更新に失敗しました", e)
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="申請の状態が変わりました。画面を再読み込みしてください",
        )
    return {"data": public_view(rows[0])}


def _require_confirmed(verification: dict):
    if verification["status"] not in CONFIRMED_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="メールまたは DNS の確認が済んでいない申請は承認できません",
        )


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
    return _close(
        supabase,
        kind,
        verification,
        {
            "status": "rejected",
            "rejection_reason": body.rejection_reason.strip(),
            "reviewed_by": admin.id,
            "reviewed_at": utc_now().isoformat(),
        },
        [verification["status"]],
    )


def _scope(verification: dict) -> LedgerApiCaller:
    """申請の is_test に合わせて、本番データかテストデータの一方だけを扱う"""
    return LedgerApiCaller(is_test_key=bool(verification.get("is_test")))


# ============================================
# 政治家の本人確認
# ============================================


@router.get("/politician-verifications")
async def list_politician_verifications(
    status_filter: Optional[StatusFilter] = Query(None, alias="status"),
    is_test: Optional[bool] = None,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    _admin: AdminUser = Depends(require_admin_user),
):
    """政治家の本人確認の申請一覧（新しい順、最大 200 件）"""
    return _list(supabase, POLITICIAN, status_filter, is_test)


@router.get("/politician-verifications/{verification_id}")
async def get_politician_verification(
    verification_id: UUID,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    _admin: AdminUser = Depends(require_admin_user),
):
    return {"data": public_view(_get(supabase, POLITICIAN, verification_id))}


@router.post("/politician-verifications/{verification_id}/approve")
async def approve_politician_verification(
    verification_id: UUID,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    admin: AdminUser = Depends(require_admin_user),
):
    """承認する。申請者の政治家を認証済みにする（無ければ作る）"""
    verification = _get(supabase, POLITICIAN, verification_id)
    _require_confirmed(verification)

    now = utc_now().isoformat()
    is_test = bool(verification.get("is_test"))
    fields = {
        "is_verified": True,
        "verified_at": now,
        "verified_domain": verification["official_domain"],
        "is_lg_verified": bool(verification.get("is_lg_domain")),
        "updated_at": now,
    }
    if verification.get("party"):
        fields["party"] = verification["party"]
    if verification.get("official_url"):
        fields["official_url"] = verification["official_url"]
    elif verification.get("request_type") == "domain_change":
        # ドメインが変わるので、古いドメインの公式サイトの URL は外す
        fields["official_url"] = None

    try:
        query = (
            supabase.table("politicians")
            .select("id")
            .eq("ledger_user_id", verification["ledger_user_id"])
        )
        existing = (
            apply_test_scope(query, _scope(verification))
            .order("created_at")
            .limit(1)
            .execute()
            .data
        )
        if existing:
            politician_id = existing[0]["id"]
            supabase.table("politicians").update(fields).eq("id", politician_id).execute()
        else:
            created = (
                supabase.table("politicians")
                .insert(
                    {
                        **fields,
                        "name": verification["politician_name"],
                        "ledger_user_id": verification["ledger_user_id"],
                        "is_test": is_test,
                    }
                )
                .execute()
                .data
            )
            politician_id = created[0]["id"]
    except Exception as e:
        raise _server_error("政治家の登録に失敗しました", e)

    return _close(
        supabase,
        POLITICIAN,
        verification,
        {
            "status": "approved",
            "approved_politician_id": politician_id,
            "reviewed_by": admin.id,
            "reviewed_at": now,
        },
        CONFIRMED_STATUSES,
    )


@router.post("/politician-verifications/{verification_id}/reject")
async def reject_politician_verification(
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
async def list_organization_manager_verifications(
    status_filter: Optional[StatusFilter] = Query(None, alias="status"),
    is_test: Optional[bool] = None,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    _admin: AdminUser = Depends(require_admin_user),
):
    """政治団体の管理者の本人確認の申請一覧（新しい順、最大 200 件）"""
    return _list(supabase, ORGANIZATION_MANAGER, status_filter, is_test)


@router.get("/organization-manager-verifications/{verification_id}")
async def get_organization_manager_verification(
    verification_id: UUID,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    _admin: AdminUser = Depends(require_admin_user),
):
    return {"data": public_view(_get(supabase, ORGANIZATION_MANAGER, verification_id))}


@router.post("/organization-manager-verifications/{verification_id}/approve")
async def approve_organization_manager_verification(
    verification_id: UUID,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    admin: AdminUser = Depends(require_admin_user),
):
    """承認する。団体を認証済みにし（無ければ作る）、申請者を団体の管理者にする"""
    verification = _get(supabase, ORGANIZATION_MANAGER, verification_id)
    _require_confirmed(verification)

    now = utc_now().isoformat()
    is_test = bool(verification.get("is_test"))
    org_fields = {
        "is_verified": True,
        "verified_at": now,
        "is_lg_verified": bool(verification.get("is_lg_domain")),
        "updated_at": now,
    }
    if verification.get("request_type") == "domain_change":
        org_fields["official_url"] = None

    organization_id = verification.get("organization_id")
    try:
        if organization_id:
            query = supabase.table("organizations").select("id").eq("id", organization_id)
            if not apply_test_scope(query, _scope(verification)).limit(1).execute().data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="申請の政治団体が見つかりません",
                )
            supabase.table("organizations").update(org_fields).eq("id", organization_id).execute()
        else:
            created = (
                supabase.table("organizations")
                .insert(
                    {
                        **org_fields,
                        "name": verification["organization_name"],
                        "type": verification.get("organization_type") or "other",
                        "is_test": is_test,
                    }
                )
                .execute()
                .data
            )
            organization_id = created[0]["id"]

        supabase.table("organization_managers").upsert(
            {
                "ledger_user_id": verification["ledger_user_id"],
                "organization_id": organization_id,
                "verified_email": verification["official_email"],
                "verified_domain": verification["official_domain"],
                "verified_at": now,
                "is_active": True,
                "is_test": is_test,
                "updated_at": now,
            },
            on_conflict="ledger_user_id,organization_id",
        ).execute()
    except HTTPException:
        raise
    except Exception as e:
        raise _server_error("政治団体の管理者の登録に失敗しました", e)

    return _close(
        supabase,
        ORGANIZATION_MANAGER,
        verification,
        {
            "status": "approved",
            "organization_id": organization_id,
            "reviewed_by": admin.id,
            "reviewed_at": now,
        },
        CONFIRMED_STATUSES,
    )


@router.post("/organization-manager-verifications/{verification_id}/reject")
async def reject_organization_manager_verification(
    verification_id: UUID,
    body: RejectVerificationRequest,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    admin: AdminUser = Depends(require_admin_user),
):
    return _reject(supabase, ORGANIZATION_MANAGER, verification_id, body, admin)
