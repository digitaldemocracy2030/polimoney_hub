"""登録申請（選挙・政治団体）と年度のロック解除申請の API（Ledger 専用）

- Hub に無い選挙・政治団体を、Ledger のユーザーが登録申請する。Hub の管理者が審査する
  （app/routers/admin_ledger_requests.py）
- アーカイブ済み（ロック済み）の年度の修正のため、Ledger の台帳の年度のロック解除を申請する。
  承認されると期限付きで解除される。Ledger は解除状態を GET /unlock-requests/check/{ledger_id} で確かめる
- DEV キーの申請はテストデータ（is_test = true）として扱う
- Hub は Ledger の台帳のメンバーを知らないので、台帳（ledger_id）への権限の確認は Ledger の API が
  呼び出す前に行う（この API は Ledger 専用キーでだけ呼べる）。解除状態の照会は、
  申請者のメールアドレスなどを含めず、解除状態の判断に必要な項目だけを返す
- 「申請中は 1 件まで」は DB の部分一意インデックスで守る（db/migrate-request-review.sql）。違反は 409
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from postgrest.exceptions import APIError
from supabase import Client

from app.core.api_key import LedgerApiCaller, require_ledger_api_key
from app.database.supabase import get_admin_supabase_client_dep
from app.schemas.ledger_request import (
    ElectionRequestCreate,
    OrganizationRequestCreate,
    UnlockRequestCreate,
)
from app.services.verification import parse_timestamp
from app.utils.test_scope import apply_test_scope

router = APIRouter()

ELECTION_REQUESTS = "election_requests"
ORGANIZATION_REQUESTS = "organization_requests"
UNLOCK_REQUESTS = "unlock_requests"

# PostgreSQL の一意制約違反
UNIQUE_VIOLATION = "23505"


def server_error(message: str, e: Exception) -> HTTPException:
    print(f"[Requests] {message}: {e}")
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=message
    )


def insert_request(supabase: Client, table: str, record: dict, duplicate_message: str) -> dict:
    """申請を作る。申請中の同じ申請があれば（一意制約違反）409"""
    try:
        return supabase.table(table).insert(record).execute().data[0]
    except APIError as e:
        if e.code == UNIQUE_VIOLATION:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=duplicate_message
            ) from e
        raise server_error("申請の作成に失敗しました", e) from e
    except Exception as e:
        raise server_error("申請の作成に失敗しました", e) from e


def _check_politician(
    supabase: Client,
    politician_id: Optional[UUID],
    ledger_user_id: UUID,
    caller: LedgerApiCaller,
) -> Optional[str]:
    """申請者の政治家（本人の Ledger ユーザーに紐付いたもの）なら ID を返す。

    他人の政治家・別の範囲（本番 / テスト）の政治家・存在しない政治家は区別せず 404
    """
    if politician_id is None:
        return None
    try:
        query = (
            supabase.table("politicians")
            .select("id")
            .eq("id", str(politician_id))
            .eq("ledger_user_id", str(ledger_user_id))
        )
        rows = apply_test_scope(query, caller).limit(1).execute().data
    except Exception as e:
        raise server_error("申請者の政治家の確認に失敗しました", e) from e
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="申請者の政治家が見つかりません",
        )
    return str(politician_id)


def _optional(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value or None


# ============================================
# 選挙・政治団体の登録申請
# ============================================


@router.post("/election-requests", status_code=status.HTTP_201_CREATED)
def create_election_request(
    body: ElectionRequestCreate,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    caller: LedgerApiCaller = Depends(require_ledger_api_key),
):
    """選挙の登録申請"""
    name = body.name.strip()
    election_type = body.type.strip()
    if not name or not election_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="選挙名と選挙種別は必須です"
        )
    record = {
        "ledger_user_id": str(body.ledger_user_id),
        "name": name,
        "type": election_type,
        "area_description": _optional(body.area_description),
        "election_date": body.election_date.isoformat(),
        "requested_by_politician_id": _check_politician(
            supabase, body.requested_by_politician_id, body.ledger_user_id, caller
        ),
        "requested_by_email": _optional(body.requested_by_email),
        "evidence_url": _optional(body.evidence_url),
        "notes": _optional(body.notes),
        "status": "pending",
        "is_test": caller.is_test_key,
    }
    row = insert_request(
        supabase,
        ELECTION_REQUESTS,
        record,
        "同じ選挙の登録申請が審査中です。審査の結果をお待ちください",
    )
    return {"data": row}


@router.post("/organization-requests", status_code=status.HTTP_201_CREATED)
def create_organization_request(
    body: OrganizationRequestCreate,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    caller: LedgerApiCaller = Depends(require_ledger_api_key),
):
    """政治団体の登録申請"""
    name = body.name.strip()
    organization_type = body.type.strip()
    if not name or not organization_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="政治団体名と団体種別は必須です"
        )
    if not body.evidence_file_url.startswith("https://"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="証明書類の URL は https:// で始めてください",
        )
    record = {
        "ledger_user_id": str(body.ledger_user_id),
        "name": name,
        "type": organization_type,
        "registration_authority": _optional(body.registration_authority),
        "requested_by_politician_id": _check_politician(
            supabase, body.requested_by_politician_id, body.ledger_user_id, caller
        ),
        "requested_by_email": _optional(body.requested_by_email),
        "evidence_type": body.evidence_type.strip(),
        "evidence_file_url": body.evidence_file_url,
        "evidence_file_path": _optional(body.evidence_file_path),
        "evidence_file_name": _optional(body.evidence_file_name),
        "notes": _optional(body.notes),
        "status": "pending",
        "is_test": caller.is_test_key,
    }
    row = insert_request(
        supabase,
        ORGANIZATION_REQUESTS,
        record,
        "同じ政治団体の登録申請が審査中です。審査の結果をお待ちください",
    )
    return {"data": row}


# ============================================
# 年度のロック解除
# ============================================


@router.post("/unlock-requests", status_code=status.HTTP_201_CREATED)
def create_unlock_request(
    body: UnlockRequestCreate,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    caller: LedgerApiCaller = Depends(require_ledger_api_key),
):
    """年度のロック解除の申請。同じ台帳の同じ年度で申請中のものがあれば 409"""
    reason = body.reason.strip()
    if len(reason) < 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="理由は10文字以上で入力してください",
        )
    record = {
        "ledger_id": str(body.ledger_id),
        "ledger_type": body.ledger_type,
        "fiscal_year": body.fiscal_year,
        "requested_by_user_id": str(body.requested_by_user_id),
        "requested_by_email": body.requested_by_email.strip(),
        "reason": reason,
        "status": "pending",
        "is_test": caller.is_test_key,
    }
    row = insert_request(
        supabase,
        UNLOCK_REQUESTS,
        record,
        "この年度のロック解除は申請中です。審査の結果をお待ちください",
    )
    return {"data": row}


# 解除状態の照会で返す承認済みの申請の列
UNLOCK_REQUEST_FIELDS = ("id", "status", "fiscal_year", "approved_at", "unlock_expires_at")


def unlock_status(
    latest_approved: Optional[dict], latest_pending: Optional[dict], now: datetime
) -> dict:
    """期限が最も遅い承認と、最新の申請中の申請から、解除中かどうかを求める"""
    active = None
    if latest_approved:
        expires_at = parse_timestamp(latest_approved.get("unlock_expires_at"))
        if expires_at and expires_at > now:
            active = latest_approved
    pending = latest_pending
    result: dict = {
        "is_unlocked": active is not None,
        "pending_request": (
            {
                "id": pending["id"],
                "created_at": pending.get("created_at"),
                "reason": pending.get("reason"),
                "fiscal_year": pending.get("fiscal_year"),
            }
            if pending
            else None
        ),
    }
    if active:
        result["unlock_request"] = {key: active.get(key) for key in UNLOCK_REQUEST_FIELDS}
        result["expires_at"] = active["unlock_expires_at"]
    return result


@router.get("/unlock-requests/check/{ledger_id}")
def check_unlock_status(
    ledger_id: UUID,
    fiscal_year: Optional[int] = Query(None, ge=1900, le=2999),
    supabase: Client = Depends(get_admin_supabase_client_dep),
    caller: LedgerApiCaller = Depends(require_ledger_api_key),
):
    """台帳（と年度）のロック解除の状態。承認済みで期限内の申請があれば解除中

    fiscal_year を指定しなければ、台帳のすべての年度の申請から求める。
    承認と申請中の申請は別々に取得する（却下の履歴の件数に左右されないように）。
    """

    now = datetime.now(timezone.utc)

    def latest(status_value: str, order_column: str) -> Optional[dict]:
        query = (
            supabase.table(UNLOCK_REQUESTS)
            .select("*")
            .eq("ledger_id", str(ledger_id))
            .eq("status", status_value)
        )
        if status_value == "approved":
            # 期限内の承認だけ（期限が NULL の行は降順で先頭に来るので除く）
            query = query.gt("unlock_expires_at", now.isoformat())
        if fiscal_year is not None:
            query = query.eq("fiscal_year", fiscal_year)
        rows = (
            apply_test_scope(query, caller)
            .order(order_column, desc=True)
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None

    try:
        latest_approved = latest("approved", "unlock_expires_at")
        latest_pending = latest("pending", "created_at")
    except Exception as e:
        raise server_error("ロック解除の状態の取得に失敗しました", e) from e
    return unlock_status(latest_approved, latest_pending, now)
