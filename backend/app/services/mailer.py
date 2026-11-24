"""メール送信（Resend）

本人確認の確認コードを送るために使う。RESEND_API_KEY と MAIL_FROM の両方が設定されていなければ送信しない
（MailNotConfiguredError）。MAIL_FROM のドメインは Resend で認証（DNS 設定）しておく必要がある。
"""

import httpx

from app.config import settings

RESEND_URL = "https://api.resend.com/emails"


class MailNotConfiguredError(Exception):
    """メール送信の設定が無い"""


class MailSendError(Exception):
    """メール送信に失敗した"""


def is_mail_configured() -> bool:
    return bool(settings.resend_api_key and settings.mail_from)


def send_mail(to: str, subject: str, text: str) -> None:
    """テキストメールを 1 通送る"""
    if not is_mail_configured():
        raise MailNotConfiguredError()

    try:
        response = httpx.post(
            RESEND_URL,
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={
                "from": settings.mail_from,
                "to": [to],
                "subject": subject,
                "text": text,
            },
            timeout=10,
        )
    except httpx.HTTPError as e:
        raise MailSendError(f"Resend への接続に失敗しました: {e}") from e

    if response.status_code >= 300:
        # 応答本文には宛先などが含まれうるので、ステータスだけを残す
        raise MailSendError(f"Resend がエラーを返しました（{response.status_code}）")
