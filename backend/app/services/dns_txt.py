"""DNS TXT レコードの取得（DNS over HTTPS）

本人確認の DNS 認証で、申請者のドメインに確認用の TXT レコードがあるかを調べる。
追加のライブラリを入れずに済むよう、Cloudflare の DNS over HTTPS（JSON 形式）を使う。
"""

import re

import httpx

DOH_URL = "https://cloudflare-dns.com/dns-query"
TXT_TYPE = 16
_QUOTED = re.compile(r'"((?:[^"\\]|\\.)*)"')


class DnsLookupError(Exception):
    """DNS の問い合わせに失敗した"""


def _txt_value(data: str) -> str:
    """'"part1" "part2"' の形の TXT データを 1 つの文字列にする"""
    parts = _QUOTED.findall(data)
    return "".join(parts) if parts else data


def lookup_txt(domain: str) -> list[str]:
    """ドメインの TXT レコードの値の一覧を返す（無ければ空）"""
    try:
        response = httpx.get(
            DOH_URL,
            params={"name": domain, "type": "TXT"},
            headers={"Accept": "application/dns-json"},
            timeout=10,
        )
        response.raise_for_status()
        answers = response.json().get("Answer") or []
    except (httpx.HTTPError, ValueError) as e:
        raise DnsLookupError(f"DNS の問い合わせに失敗しました: {e}") from e

    return [
        _txt_value(answer.get("data", ""))
        for answer in answers
        if answer.get("type") == TXT_TYPE
    ]
