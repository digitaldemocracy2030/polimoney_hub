"""本人確認 API（Ledger 専用）

政治家と政治団体の管理者の本人確認の申請・確認コードの送信・メール / DNS の確認。
承認・却下は管理者 API（app/routers/admin_verifications.py）で行う。

- 申請の操作には申請者本人の ledger_user_id が必要（違えば 404）
- DEV キーの申請はテストデータ（is_test = true）として扱う。確認コードはメールで送らず応答に含める
"""

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from supabase import Client

from app.core.api_key import LedgerApiCaller, require_ledger_api_key
from app.database.supabase import get_admin_supabase_client_dep
from app.schemas.verification import (
    OrganizationManagerVerificationCreate,
    PoliticianVerificationCreate,
    VerificationOwnerRequest,
    VerifyCodeRequest,
)
from app.services.dns_txt import DnsLookupError, lookup_txt
from app.services.mailer import MailNotConfiguredError, MailSendError, send_mail
from app.services.verification import (
    ACTIVE_STATUSES,
    CODE_TTL,
    MAX_CODE_ATTEMPTS,
    RESEND_INTERVAL,
    code_matches,
    email_domain,
    expected_dns_txt,
    generate_code,
    generate_dns_token,
    hash_code,
    is_free_mail,
    is_lg_jp,
    parse_timestamp,
    public_view,
    utc_now,
)
from app.utils.test_scope import apply_test_scope

router = APIRouter()


@dataclass(frozen=True)
class VerificationKind:
    table: str
    label: str


POLITICIAN = VerificationKind("politician_verifications", "政治家")
ORGANIZATION_MANAGER = VerificationKind(
    "organization_manager_verifications", "政治団体の管理者"
)


def _server_error(message: str, e: Exception) -> HTTPException:
    print(f"[Verifications] {message}: {e}")
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=message
    )


def _bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)


def _common_fields(body, caller: LedgerApiCaller) -> dict:
    """申請の共通の列（メールのドメインから認証方式を決める）"""
    domain = email_domain(body.official_email)
    if not domain:
        raise _bad_request("公式メールアドレスの形式が正しくありません")
    lg = is_lg_jp(domain)
    if not lg and is_free_mail(domain):
        raise _bad_request(
            "フリーメールアドレスは使用できません。公式ドメインのメールアドレスを入力してください"
        )
    official_url = getattr(body, "official_url", None)
    if official_url and not official_url.startswith(("https://", "http://")):
        raise _bad_request("公式サイトの URL は http:// または https:// で始めてください")
    if body.request_type == "domain_change" and not body.previous_domain:
        raise _bad_request("ドメイン変更の申請には変更前のドメインが必要です")

    method = "email" if lg else "dns_txt"
    return {
        "ledger_user_id": str(body.ledger_user_id),
        "ledger_user_email": body.ledger_user_email,
        "official_email": body.official_email.strip(),
        "official_domain": domain,
        "request_type": body.request_type,
        "previous_domain": body.previous_domain,
        "verification_method": method,
        "is_lg_domain": lg,
        "dns_txt_token": generate_dns_token() if method == "dns_txt" else None,
        "status": "pending",
        "is_test": caller.is_test_key,
    }


def _ensure_no_active(supabase: Client, kind: VerificationKind, query_filters, caller):
    try:
        query = supabase.table(kind.table).select("id").in_("status", ACTIVE_STATUSES)
        for column, value in query_filters:
            query = query.eq(column, value)
        active = apply_test_scope(query, caller).limit(1).execute().data
    except Exception as e:
        raise _server_error("申請の確認に失敗しました", e)
    if active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="手続き中の申請があります。完了するか却下されるまで新しい申請はできません",
        )


def _insert(supabase: Client, kind: VerificationKind, record: dict) -> dict:
    try:
        return supabase.table(kind.table).insert(record).execute().data[0]
    except Exception as e:
        raise _server_error("申請の作成に失敗しました", e)


def _list_by_user(
    supabase: Client, kind: VerificationKind, ledger_user_id: UUID, caller
) -> dict:
    try:
        query = (
            supabase.table(kind.table)
            .select("*")
            .eq("ledger_user_id", str(ledger_user_id))
        )
        rows = (
            apply_test_scope(query, caller)
            .order("created_at", desc=True)
            .execute()
            .data
        )
    except Exception as e:
        raise _server_error("申請の取得に失敗しました", e)
    return {"data": [public_view(row) for row in rows]}


def _get_owned(
    supabase: Client,
    kind: VerificationKind,
    verification_id: UUID,
    ledger_user_id: UUID,
    caller: LedgerApiCaller,
) -> dict:
    try:
        query = (
            supabase.table(kind.table)
            .select("*")
            .eq("id", str(verification_id))
            .eq("ledger_user_id", str(ledger_user_id))
        )
        rows = apply_test_scope(query, caller).limit(1).execute().data
    except Exception as e:
        raise _server_error("申請の取得に失敗しました", e)
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="申請が見つかりません"
        )
    return rows[0]


def _update(
    supabase: Client,
    kind: VerificationKind,
    verification: dict,
    fields: dict,
    expected_statuses: list[str],
) -> Optional[dict]:
    """状態が変わっていなければ更新する（同時に操作された場合は None）"""
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
    return rows[0] if rows else None


def _conflict() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="申請の状態が変わりました。画面を再読み込みしてください",
    )


def _send_code(
    supabase: Client,
    kind: VerificationKind,
    verification_id: UUID,
    body: VerificationOwnerRequest,
    caller: LedgerApiCaller,
) -> dict:
    verification = _get_owned(supabase, kind, verification_id, body.ledger_user_id, caller)

    if verification["verification_method"] != "email":
        raise _bad_request("この申請は DNS 認証です。確認コードは送信できません")
    if verification["status"] not in ("pending", "email_sent"):
        raise _bad_request("この申請には確認コードを送信できません")

    now = utc_now()
    sent_at = parse_timestamp(verification.get("verification_code_sent_at"))
    if sent_at and now - sent_at < RESEND_INTERVAL:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="確認コードの再送信は 1 分ほど待ってから行ってください",
        )

    code = generate_code()
    updated = _update(
        supabase,
        kind,
        verification,
        {
            "verification_code": hash_code(code),
            "verification_code_sent_at": now.isoformat(),
            "verification_attempts": 0,
            "status": "email_sent",
        },
        ["pending", "email_sent"],
    )
    if not updated:
        raise _conflict()

    # テストデータ（DEV キー）はメールを送らず、コードを応答で返す
    if caller.is_test_key:
        return {"message": "確認コードを発行しました（テストデータのため送信していません）", "code": code}

    try:
        send_mail(
            verification["official_email"],
            "【Polimoney】本人確認の確認コード",
            (
                f"Polimoney の{kind.label}の本人確認の確認コードです。\n\n"
                f"確認コード: {code}\n\n"
                f"有効期限は {int(CODE_TTL.total_seconds() // 60)} 分です。\n"
                "このメールに心当たりが無い場合は破棄してください。\n"
            ),
        )
    except MailNotConfiguredError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="メール送信が設定されていないため、確認コードを送れません",
        )
    except MailSendError as e:
        print(f"[Verifications] メール送信に失敗しました: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="確認コードのメール送信に失敗しました。時間をおいて再送信してください",
        )

    return {"message": "確認コードを送信しました"}


def _verify_email(
    supabase: Client,
    kind: VerificationKind,
    verification_id: UUID,
    body: VerifyCodeRequest,
    caller: LedgerApiCaller,
) -> dict:
    verification = _get_owned(supabase, kind, verification_id, body.ledger_user_id, caller)

    if verification["status"] != "email_sent":
        raise _bad_request("確認コードを送信していない申請です")
    attempts = verification.get("verification_attempts") or 0
    if attempts >= MAX_CODE_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="確認コードを続けて間違えたため無効になりました。再送信してください",
        )
    sent_at = parse_timestamp(verification.get("verification_code_sent_at"))
    if not sent_at or utc_now() - sent_at > CODE_TTL:
        raise _bad_request("確認コードの有効期限が切れています。再送信してください")

    if not code_matches(body.code, verification.get("verification_code")):
        _update(
            supabase,
            kind,
            verification,
            {"verification_attempts": attempts + 1},
            ["email_sent"],
        )
        raise _bad_request("確認コードが正しくありません")

    updated = _update(
        supabase,
        kind,
        verification,
        {
            "status": "email_verified",
            "verification_code": None,
            "verification_code_verified_at": utc_now().isoformat(),
        },
        ["email_sent"],
    )
    if not updated:
        raise _conflict()
    return {"message": "メールアドレスを確認しました。管理者の審査をお待ちください"}


def _verify_dns(
    supabase: Client,
    kind: VerificationKind,
    verification_id: UUID,
    body: VerificationOwnerRequest,
    caller: LedgerApiCaller,
) -> dict:
    verification = _get_owned(supabase, kind, verification_id, body.ledger_user_id, caller)

    if verification["verification_method"] != "dns_txt":
        raise _bad_request("この申請はメール認証です")
    if verification["status"] != "pending":
        raise _bad_request("この申請は DNS の確認ができる状態ではありません")
    token = verification.get("dns_txt_token")
    if not token:
        raise _server_error("申請に DNS 確認用のトークンがありません", Exception(verification["id"]))

    domain = verification["official_domain"]
    expected = expected_dns_txt(token)
    try:
        records = lookup_txt(domain)
    except DnsLookupError as e:
        print(f"[Verifications] {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="DNS の確認に失敗しました。時間をおいて再度お試しください",
        )

    if expected not in records:
        raise _bad_request(
            f"DNS TXT レコードが見つかりません。{domain} に TXT レコード「{expected}」を設定してください"
            "（反映まで時間がかかることがあります）"
        )

    now = utc_now().isoformat()
    updated = _update(
        supabase,
        kind,
        verification,
        {"status": "dns_verified", "dns_txt_verified": True, "dns_txt_verified_at": now},
        ["pending"],
    )
    if not updated:
        raise _conflict()
    return {"message": "DNS を確認しました。管理者の審査をお待ちください"}


# ============================================
# 政治家の本人確認
# ============================================


@router.post("/politician-verifications", status_code=status.HTTP_201_CREATED)
async def create_politician_verification(
    body: PoliticianVerificationCreate,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    caller: LedgerApiCaller = Depends(require_ledger_api_key),
):
    """政治家の本人確認を申請する（1 ユーザーにつき手続き中の申請は 1 件まで）"""
    if not body.candidate_registration_info and not body.political_fund_report_info:
        raise _bad_request("立候補届出情報または政治資金収支報告書情報のいずれかを入力してください")

    record = _common_fields(body, caller)
    _ensure_no_active(supabase, POLITICIAN, [("ledger_user_id", record["ledger_user_id"])], caller)
    record.update(
        {
            "politician_name": body.name.strip(),
            "official_url": body.official_url or None,
            "party": body.party,
            "candidate_registration_info": body.candidate_registration_info,
            "political_fund_report_info": body.political_fund_report_info,
        }
    )
    return {"data": public_view(_insert(supabase, POLITICIAN, record))}


@router.get("/politician-verifications/user/{ledger_user_id}")
async def list_politician_verifications(
    ledger_user_id: UUID,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    caller: LedgerApiCaller = Depends(require_ledger_api_key),
):
    """ユーザーの政治家の本人確認の申請（新しい順）"""
    return _list_by_user(supabase, POLITICIAN, ledger_user_id, caller)


@router.post("/politician-verifications/{verification_id}/send-verification")
async def send_politician_verification_code(
    verification_id: UUID,
    body: VerificationOwnerRequest,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    caller: LedgerApiCaller = Depends(require_ledger_api_key),
):
    """確認コードを公式メールアドレスに送る（メール認証の申請のみ）"""
    return _send_code(supabase, POLITICIAN, verification_id, body, caller)


@router.post("/politician-verifications/{verification_id}/verify-email")
async def verify_politician_email(
    verification_id: UUID,
    body: VerifyCodeRequest,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    caller: LedgerApiCaller = Depends(require_ledger_api_key),
):
    """確認コードを確かめる"""
    return _verify_email(supabase, POLITICIAN, verification_id, body, caller)


@router.post("/politician-verifications/{verification_id}/verify-dns")
async def verify_politician_dns(
    verification_id: UUID,
    body: VerificationOwnerRequest,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    caller: LedgerApiCaller = Depends(require_ledger_api_key),
):
    """ドメインの DNS TXT レコードを確かめる（DNS 認証の申請のみ）"""
    return _verify_dns(supabase, POLITICIAN, verification_id, body, caller)


# ============================================
# 政治団体の管理者の本人確認
# ============================================


@router.post("/organization-manager-verifications", status_code=status.HTTP_201_CREATED)
async def create_organization_manager_verification(
    body: OrganizationManagerVerificationCreate,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    caller: LedgerApiCaller = Depends(require_ledger_api_key),
):
    """政治団体の管理者の本人確認を申請する（同じ団体について手続き中の申請は 1 件まで）"""
    record = _common_fields(body, caller)

    organization_id = str(body.organization_id) if body.organization_id else None
    if organization_id:
        try:
            query = supabase.table("organizations").select("id").eq("id", organization_id)
            found = apply_test_scope(query, caller).limit(1).execute().data
        except Exception as e:
            raise _server_error("政治団体の取得に失敗しました", e)
        if not found:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="政治団体が見つかりません"
            )
        same_org = ("organization_id", organization_id)
    else:
        same_org = ("organization_name", body.organization_name.strip())

    _ensure_no_active(
        supabase,
        ORGANIZATION_MANAGER,
        [("ledger_user_id", record["ledger_user_id"]), same_org],
        caller,
    )
    record.update(
        {
            "organization_id": organization_id,
            "organization_name": body.organization_name.strip(),
            "organization_type": body.organization_type,
            "role_in_organization": body.role_in_organization,
            "political_fund_report_info": body.political_fund_report_info,
        }
    )
    return {"data": public_view(_insert(supabase, ORGANIZATION_MANAGER, record))}


@router.get("/organization-manager-verifications/user/{ledger_user_id}")
async def list_organization_manager_verifications(
    ledger_user_id: UUID,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    caller: LedgerApiCaller = Depends(require_ledger_api_key),
):
    """ユーザーの政治団体の管理者の本人確認の申請（新しい順）"""
    return _list_by_user(supabase, ORGANIZATION_MANAGER, ledger_user_id, caller)


@router.post("/organization-manager-verifications/{verification_id}/send-verification")
async def send_organization_manager_verification_code(
    verification_id: UUID,
    body: VerificationOwnerRequest,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    caller: LedgerApiCaller = Depends(require_ledger_api_key),
):
    return _send_code(supabase, ORGANIZATION_MANAGER, verification_id, body, caller)


@router.post("/organization-manager-verifications/{verification_id}/verify-email")
async def verify_organization_manager_email(
    verification_id: UUID,
    body: VerifyCodeRequest,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    caller: LedgerApiCaller = Depends(require_ledger_api_key),
):
    return _verify_email(supabase, ORGANIZATION_MANAGER, verification_id, body, caller)


@router.post("/organization-manager-verifications/{verification_id}/verify-dns")
async def verify_organization_manager_dns(
    verification_id: UUID,
    body: VerificationOwnerRequest,
    supabase: Client = Depends(get_admin_supabase_client_dep),
    caller: LedgerApiCaller = Depends(require_ledger_api_key),
):
    return _verify_dns(supabase, ORGANIZATION_MANAGER, verification_id, body, caller)
