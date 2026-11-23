"""Ledger 専用 API キー認証

一般公開用の API キーの仕組みができるまで、/api/v1/* の API はすべて Ledger 専用とする
（main.py で全ルーターに require_ledger_api_key を指定。/health だけは認証不要）。
Ledger は X-API-Key ヘッダーにキーを付けて呼ぶ。

- LEDGER_SYNC_API_KEY_PROD: 本番データ用。is_test が false / NULL の行だけを扱う
- LEDGER_SYNC_API_KEY_DEV: テストデータ用。is_test=true の行だけを扱う。
  同期 API ではこのキーで送られたデータは常に is_test=true として扱い、
  本番データ（is_test=false）の上書きは拒否する

環境変数名は同期 API 専用だった頃の名前のまま（本番に設定済みのため変えない）。
どちらも未設定の場合は、設定漏れで API が開いたままにならないよう 503 を返す。
将来の一般公開用 API キーとは別のキーとして扱う。
"""

import hmac
from dataclasses import dataclass
from typing import Optional

from fastapi import Header, HTTPException, status

from app.config import settings


@dataclass(frozen=True)
class LedgerApiCaller:
    """認証済みの Ledger 呼び出し元"""

    is_test_key: bool


def _matches(provided: str, expected: Optional[str]) -> bool:
    if not expected:
        return False
    return hmac.compare_digest(provided.encode(), expected.encode())


def require_ledger_api_key(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> LedgerApiCaller:
    """X-API-Key を検証し、呼び出し元の種別を返す FastAPI 依存関数"""
    prod_key = settings.ledger_sync_api_key_prod
    dev_key = settings.ledger_sync_api_key_dev

    if not prod_key and not dev_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ledger 用の API キーが設定されていません",
        )

    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API キーが必要です",
        )

    # 両方と比較して、どちらに一致したかで処理時間が変わらないようにする
    is_prod = _matches(x_api_key, prod_key)
    is_dev = _matches(x_api_key, dev_key)

    if is_prod:
        return LedgerApiCaller(is_test_key=False)
    if is_dev:
        return LedgerApiCaller(is_test_key=True)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="API キーが正しくありません",
    )
