"""本人確認（政治家・政治団体の管理者）の共通処理

流れ:
  1. Ledger から申請（status: pending）
     - 公式メールのドメインが lg.jp なら メール認証、それ以外は DNS TXT 認証
  2. メール認証: 確認コードを送信（email_sent）→ コードを入力（email_verified）
     DNS 認証:   ドメインに TXT レコード「polimoney-verify=<トークン>」を設定 → 確認（dns_verified）
  3. Hub の管理者が審査して承認（approved）または却下（rejected）
"""

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

ACTIVE_STATUSES = ["pending", "email_sent", "email_verified", "dns_verified"]
CONFIRMED_STATUSES = ["email_verified", "dns_verified"]
CLOSED_STATUSES = ["approved", "rejected"]

CODE_TTL = timedelta(minutes=30)
RESEND_INTERVAL = timedelta(seconds=60)
MAX_CODE_ATTEMPTS = 5

DNS_TXT_PREFIX = "polimoney-verify="

# lg.jp 以外では DNS 認証になるため、本人が DNS を設定できないフリーメールは受け付けない
FREE_MAIL_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "yahoo.co.jp",
    "yahoo.com",
    "hotmail.com",
    "hotmail.co.jp",
    "outlook.com",
    "outlook.jp",
    "live.jp",
    "icloud.com",
    "me.com",
    "docomo.ne.jp",
    "softbank.ne.jp",
    "i.softbank.jp",
    "ezweb.ne.jp",
    "au.com",
}

# 応答に含めない列（確認コードのハッシュと失敗回数）
HIDDEN_COLUMNS = {"verification_code", "verification_attempts"}

_EMAIL = re.compile(r"^[^@\s]+@([A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+)$")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def email_domain(email: str) -> Optional[str]:
    """メールアドレスのドメイン（小文字）。形式が正しくなければ None"""
    match = _EMAIL.match(email.strip())
    return match.group(1).lower() if match else None


def is_lg_jp(domain: str) -> bool:
    return domain == "lg.jp" or domain.endswith(".lg.jp")


def is_free_mail(domain: str) -> bool:
    return domain in FREE_MAIL_DOMAINS


def generate_code() -> str:
    return f"{secrets.randbelow(10**6):06d}"


def generate_dns_token() -> str:
    return secrets.token_urlsafe(24)


def hash_code(code: str) -> str:
    return hashlib.sha256(code.strip().encode()).hexdigest()


def code_matches(code: str, stored_hash: Optional[str]) -> bool:
    if not stored_hash:
        return False
    return hmac.compare_digest(hash_code(code), stored_hash)


def expected_dns_txt(token: str) -> str:
    return f"{DNS_TXT_PREFIX}{token}"


def public_view(row: dict) -> dict:
    """応答用に、確認コードのハッシュなどを除いた申請を返す"""
    return {k: v for k, v in row.items() if k not in HIDDEN_COLUMNS}
