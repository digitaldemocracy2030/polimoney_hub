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
    # supabase-py の insert() の戻り値は execute() しか持たない（.select() を呼ぶと失敗する）
    table.insert.return_value = MagicMock(spec=["execute"])
    table.insert.return_value.execute.return_value = MagicMock(
        data=[{"id": "hub-ledger-1"}]
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


# ============================================
# 変更ログ（ledger_change_logs は public_ledgers.id に紐付く）
# ============================================

CHANGE_LOG_BODY = {
    "ledger_source_id": "ledger-1",
    "change_summary": "仕訳 2 件を同期",
    "change_details": {"journals": 2},
}


def _fake_change_log_supabase(ledgers):
    client = MagicMock()
    tables = {"public_ledgers": MagicMock(), "ledger_change_logs": MagicMock()}
    client.table.side_effect = lambda name: tables[name]
    select = tables["public_ledgers"].select.return_value.eq.return_value.limit.return_value
    select.execute.return_value = MagicMock(data=ledgers)
    return client, tables


def test_change_log_records_with_public_ledger_id(keys, client):
    fake, tables = _fake_change_log_supabase([{"id": "hub-ledger-1", "is_test": False}])
    _use_supabase(fake)
    res = client.post("/api/v1/sync/change-log", json=CHANGE_LOG_BODY, headers={"X-API-Key": PROD_KEY})
    assert res.status_code == 200
    inserted = tables["ledger_change_logs"].insert.call_args.args[0]
    assert inserted["ledger_id"] == "hub-ledger-1"
    assert inserted["changed_at"]
    assert inserted["change_summary"] == "仕訳 2 件を同期"
    assert "ledger_source_id" not in inserted


def test_change_log_404_when_ledger_not_synced(keys, client):
    fake, tables = _fake_change_log_supabase([])
    _use_supabase(fake)
    res = client.post("/api/v1/sync/change-log", json=CHANGE_LOG_BODY, headers={"X-API-Key": PROD_KEY})
    assert res.status_code == 404
    tables["ledger_change_logs"].insert.assert_not_called()


def test_change_log_dev_key_cannot_write_production_ledger(keys, client):
    fake, tables = _fake_change_log_supabase([{"id": "hub-ledger-1", "is_test": False}])
    _use_supabase(fake)
    res = client.post("/api/v1/sync/change-log", json=CHANGE_LOG_BODY, headers={"X-API-Key": DEV_KEY})
    assert res.status_code == 403
    tables["ledger_change_logs"].insert.assert_not_called()


# ============================================
# 関係者（public_contacts は is_test を持たないので、紐付く公開台帳で判定する）
# ============================================


def _contact(ledger_id="hub-ledger-test"):
    return {
        "contact_source_id": "contact-1",
        "ledger_id": ledger_id,
        "contact_type": "person",
        "name": "寄附 太郎",
    }


def _fake_contacts_supabase(existing_contact, ledgers):
    """public_contacts の既存行と public_ledgers の is_test を返すモック"""
    client = MagicMock()
    tables = {"public_contacts": MagicMock(), "public_ledgers": MagicMock()}
    client.table.side_effect = lambda name: tables[name]
    contacts = tables["public_contacts"]
    contacts.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = (
        MagicMock(data=existing_contact)
    )
    contacts.insert.return_value = MagicMock(spec=["execute"])
    contacts.insert.return_value.execute.return_value = MagicMock(data=[{"id": "hub-contact-1"}])

    def ledger_query(_column, ledger_id):
        query = MagicMock()
        rows = [{"is_test": ledgers[ledger_id]}] if ledger_id in ledgers else []
        query.limit.return_value.execute.return_value = MagicMock(data=rows)
        return query

    tables["public_ledgers"].select.return_value.eq.side_effect = ledger_query
    return client, tables


LEDGERS = {"hub-ledger-test": True, "hub-ledger-prod": False}


def test_dev_key_creates_contact_on_test_ledger(keys, client):
    fake, tables = _fake_contacts_supabase(None, LEDGERS)
    _use_supabase(fake)
    res = client.post("/api/v1/sync/contacts", json=[_contact()], headers={"X-API-Key": DEV_KEY})
    assert res.status_code == 200
    assert res.json()["errors"] == []
    assert res.json()["data"][0]["action"] == "created"


def test_dev_key_cannot_create_contact_on_production_ledger(keys, client):
    fake, tables = _fake_contacts_supabase(None, LEDGERS)
    _use_supabase(fake)
    res = client.post(
        "/api/v1/sync/contacts", json=[_contact("hub-ledger-prod")], headers={"X-API-Key": DEV_KEY}
    )
    assert res.status_code == 200
    assert res.json()["data"] == []
    assert len(res.json()["errors"]) == 1
    tables["public_contacts"].insert.assert_not_called()


def test_dev_key_cannot_overwrite_production_contact(keys, client):
    # 既存の関係者は本番の台帳に紐付く。送られてきた ledger_id がテストでも更新しない
    fake, tables = _fake_contacts_supabase(
        {"id": "hub-contact-1", "ledger_id": "hub-ledger-prod"}, LEDGERS
    )
    _use_supabase(fake)
    res = client.post("/api/v1/sync/contacts", json=[_contact()], headers={"X-API-Key": DEV_KEY})
    assert res.status_code == 200
    assert len(res.json()["errors"]) == 1
    tables["public_contacts"].update.assert_not_called()


def test_dev_key_cannot_use_unknown_ledger(keys, client):
    fake, tables = _fake_contacts_supabase(None, LEDGERS)
    _use_supabase(fake)
    res = client.post(
        "/api/v1/sync/contacts", json=[_contact("missing")], headers={"X-API-Key": DEV_KEY}
    )
    assert len(res.json()["errors"]) == 1
    tables["public_contacts"].insert.assert_not_called()


def test_prod_key_updates_contact_without_ledger_check(keys, client):
    fake, tables = _fake_contacts_supabase(
        {"id": "hub-contact-1", "ledger_id": "hub-ledger-prod"}, LEDGERS
    )
    _use_supabase(fake)
    res = client.post(
        "/api/v1/sync/contacts", json=[_contact("hub-ledger-prod")], headers={"X-API-Key": PROD_KEY}
    )
    assert res.status_code == 200
    assert res.json()["data"][0]["action"] == "updated"
    tables["public_ledgers"].select.assert_not_called()
