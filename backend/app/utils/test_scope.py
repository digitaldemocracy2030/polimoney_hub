"""テストデータの絞り込み

Ledger の API キーの種類で、扱う行を本番データかテストデータのどちらかに限定する。

- DEV キー（テストデータ用）: is_test = true の行だけ
- PROD キー（本番データ用）: is_test が false または NULL の行だけ
"""

from app.core.api_key import LedgerApiCaller


def apply_test_scope(query, caller: LedgerApiCaller, column: str = "is_test"):
    """Supabase のクエリに呼び出し元のテストデータ範囲のフィルタを付ける"""
    if caller.is_test_key:
        return query.eq(column, True)
    return query.or_(f"{column}.is.null,{column}.eq.false")
