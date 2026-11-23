"""マスタデータ API（勘定科目）のテスト

Supabase には接続しない（クライアントはモックに差し替える）。
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.database.supabase import get_supabase_client_dep
from app.main import app

PROD_KEY = "test-prod-key"
AUTH = {"X-API-Key": PROD_KEY}

CASH = {
    "code": "ASSET_CASH",
    "name": "現金",
    "name_kana": None,
    "type": "asset",
    "report_category": "資産",
    "ledger_type": "both",
    "is_public_subsidy_eligible": False,
    "display_order": 1,
    "polimoney_category": None,
    "parent_code": None,
    "description": None,
}


class FakeQuery:
    """呼ばれたフィルタを記録し、execute() で決まった行を返すクエリ"""

    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def __getattr__(self, name):
        def method(*args, **kwargs):
            self.calls.append((name, args))
            return self

        return method

    def execute(self):
        return MagicMock(data=self.rows)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "ledger_sync_api_key_prod", PROD_KEY)
    monkeypatch.setattr(settings, "ledger_sync_api_key_dev", "test-dev-key")
    yield TestClient(app, headers=AUTH)
    app.dependency_overrides.clear()


def _use_rows(rows):
    query = FakeQuery(rows)
    fake = MagicMock()
    fake.table.return_value = query
    app.dependency_overrides[get_supabase_client_dep] = lambda: fake
    return query


def test_list_returns_active_codes_in_display_order(client):
    query = _use_rows([CASH])
    res = client.get("/api/v1/master/account-codes")
    assert res.status_code == 200
    assert res.json() == {"data": [CASH]}
    assert ("eq", ("is_active", True)) in query.calls
    assert ("order", ("display_order",)) in query.calls
    assert not any(name == "in_" for name, _ in query.calls)


@pytest.mark.parametrize("ledger_type", ["organization", "election"])
def test_list_filters_by_ledger_type_including_both(client, ledger_type):
    query = _use_rows([CASH])
    res = client.get(f"/api/v1/master/account-codes?ledger_type={ledger_type}")
    assert res.status_code == 200
    assert ("in_", ("ledger_type", ["both", ledger_type])) in query.calls


def test_list_both_does_not_filter(client):
    query = _use_rows([CASH])
    client.get("/api/v1/master/account-codes?ledger_type=both")
    assert not any(name == "in_" for name, _ in query.calls)


def test_list_filters_by_type_and_report_category(client):
    query = _use_rows([CASH])
    client.get("/api/v1/master/account-codes?type=expense&report_category=経常経費")
    assert ("eq", ("type", "expense")) in query.calls
    assert ("eq", ("report_category", "経常経費")) in query.calls


@pytest.mark.parametrize("param", ["ledger_type=political_fund", "type=unknown"])
def test_list_rejects_unknown_values(client, param):
    _use_rows([CASH])
    res = client.get(f"/api/v1/master/account-codes?{param}")
    assert res.status_code == 422


def test_get_one(client):
    query = _use_rows([CASH])
    res = client.get("/api/v1/master/account-codes/ASSET_CASH")
    assert res.status_code == 200
    assert res.json() == {"data": CASH}
    assert ("eq", ("code", "ASSET_CASH")) in query.calls


def test_get_one_not_found(client):
    _use_rows([])
    res = client.get("/api/v1/master/account-codes/NOPE")
    assert res.status_code == 404


@pytest.mark.parametrize(
    "path", ["/api/v1/master/account-codes", "/api/v1/master/account-codes/ASSET_CASH"]
)
@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong"}])
def test_requires_ledger_api_key(client, path, headers):
    _use_rows([CASH])
    res = TestClient(app).get(path, headers=headers)
    assert res.status_code == 401
