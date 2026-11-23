"""同期 API の Ledger 専用 API キー認証のテスト

Supabase には接続しない（クライアントはモックに差し替える）。
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.database.supabase import get_admin_supabase_client_dep
from app.main import app

PROD_KEY = "test-prod-key"
DEV_KEY = "test-dev-key"

LEDGER_BODY = {
    "ledger": {
        "ledger_source_id": "ledger-1",
        "ledger_type": "political_fund",
        "politician_organization_id": "po-1",
        "fiscal_year": 2025,
        "total_income": 100,
        "total_expense": 50,
        "journal_count": 2,
        "is_test": False,
    }
}


def _fake_supabase(existing_ledger=None):
    """public_ledgers の検索結果と書き込み内容を記録するモック"""
    client = MagicMock()
    table = client.table.return_value
    select_chain = table.select.return_value.eq.return_value.maybe_single.return_value
    select_chain.execute.return_value = MagicMock(data=existing_ledger)
    table.insert.return_value.select.return_value.single.return_value.execute.return_value = MagicMock(
        data={"id": "hub-ledger-1"}
    )
    return client


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setattr(settings, "ledger_sync_api_key_prod", PROD_KEY)
    monkeypatch.setattr(settings, "ledger_sync_api_key_dev", DEV_KEY)


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


def _use_supabase(fake):
    app.dependency_overrides[get_admin_supabase_client_dep] = lambda: fake


@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/api/v1/sync/contacts"),
        ("post", "/api/v1/sync/journals"),
        ("post", "/api/v1/sync/ledger"),
        ("post", "/api/v1/sync/change-log"),
        ("get", "/api/v1/sync/status"),
    ],
)
def test_requires_api_key(keys, client, method, path):
    _use_supabase(_fake_supabase())
    res = getattr(client, method)(path)
    assert res.status_code == 401


def test_rejects_wrong_key(keys, client):
    _use_supabase(_fake_supabase())
    res = client.post("/api/v1/sync/ledger", json=LEDGER_BODY, headers={"X-API-Key": "wrong"})
    assert res.status_code == 401


def test_unconfigured_keys_fail_closed(monkeypatch, client):
    monkeypatch.setattr(settings, "ledger_sync_api_key_prod", None)
    monkeypatch.setattr(settings, "ledger_sync_api_key_dev", None)
    _use_supabase(_fake_supabase())
    res = client.post("/api/v1/sync/ledger", json=LEDGER_BODY, headers={"X-API-Key": "anything"})
    assert res.status_code == 503


def test_health_does_not_require_api_key(keys, client):
    # /health だけは API キーなしで呼べる
    res = client.get("/health")
    assert res.status_code != 401


def test_prod_key_keeps_is_test(keys, client):
    fake = _fake_supabase()
    _use_supabase(fake)
    res = client.post("/api/v1/sync/ledger", json=LEDGER_BODY, headers={"X-API-Key": PROD_KEY})
    assert res.status_code == 200
    assert res.json()["data"]["is_test"] is False


def test_dev_key_forces_is_test(keys, client):
    fake = _fake_supabase()
    _use_supabase(fake)
    res = client.post("/api/v1/sync/ledger", json=LEDGER_BODY, headers={"X-API-Key": DEV_KEY})
    assert res.status_code == 200
    assert res.json()["data"]["is_test"] is True
    inserted = fake.table.return_value.insert.call_args.args[0]
    assert inserted["is_test"] is True


def test_dev_key_cannot_overwrite_production_ledger(keys, client):
    fake = _fake_supabase(existing_ledger={"id": "hub-ledger-1", "is_test": False})
    _use_supabase(fake)
    res = client.post("/api/v1/sync/ledger", json=LEDGER_BODY, headers={"X-API-Key": DEV_KEY})
    assert res.status_code == 403
    fake.table.return_value.update.assert_not_called()


def test_dev_key_can_update_test_ledger(keys, client):
    fake = _fake_supabase(existing_ledger={"id": "hub-ledger-1", "is_test": True})
    _use_supabase(fake)
    res = client.post("/api/v1/sync/ledger", json=LEDGER_BODY, headers={"X-API-Key": DEV_KEY})
    assert res.status_code == 200
    assert res.json()["action"] == "updated"
