"""Ledger 専用 API キー認証

同期 API（/api/v1/sync/*）は公開データを書き込むため、Ledger からの呼び出しだけを受け付ける。
Ledger は X-API-Key ヘッダーにキーを付けて呼ぶ。

- LEDGER_SYNC_API_KEY_PROD: 本番データ用
- LEDGER_SYNC_API_KEY_DEV: テストデータ用。このキーで送られたデータは常に is_test=true として扱い、
  本番データ（is_test=false）の上書きは拒否する

どちらも未設定の場合は、設定漏れで書き込み口が開いたままにならないよう 503 を返す。
公開の読み取り API とは別のキーとして扱う（読み取り API には付けない）。
"""

import hmac
from dataclasses import dataclass
from typing import Optional

from fastapi import Header, HTTPException, status

from app.config import settings


@dataclass(frozen=True)
class LedgerSyncCaller:
    """認証済みの同期呼び出し元"""

    is_test_key: bool


def _matches(provided: str, expected: Optional[str]) -> bool:
    if not expected:
        return False
    return hmac.compare_digest(provided.encode(), expected.encode())


def require_ledger_sync_key(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> LedgerSyncCaller:
    """X-API-Key を検証し、呼び出し元の種別を返す FastAPI 依存関数"""
    prod_key = settings.ledger_sync_api_key_prod
    dev_key = settings.ledger_sync_api_key_dev

    if not prod_key and not dev_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="同期用の API キーが設定されていません",
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
        return LedgerSyncCaller(is_test_key=False)
    if is_dev:
        return LedgerSyncCaller(is_test_key=True)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="API キーが正しくありません",
    )
