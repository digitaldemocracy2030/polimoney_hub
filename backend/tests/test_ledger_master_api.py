"""Ledger 向けマスタ API（政治家・政治団体・選挙・紐付け）と API キー必須化のテスト

Supabase には接続しない（クライアントはテーブルごとに決まった行を返すモックに差し替える）。
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from postgrest import APIError

from app.config import settings
from app.database.supabase import get_admin_supabase_client_dep
from app.main import app

PROD_KEY = "test-prod-key"
DEV_KEY = "test-dev-key"
PROD = {"X-API-Key": PROD_KEY}
DEV = {"X-API-Key": DEV_KEY}

USER_ID = "11111111-1111-1111-1111-111111111111"
OTHER_USER_ID = "22222222-2222-2222-2222-222222222222"
POLITICIAN_ID = "33333333-3333-3333-3333-333333333333"
ELECTION_ID = "44444444-4444-4444-4444-444444444444"
ORG_ID = "55555555-5555-5555-5555-555555555555"
LINK_ID = "77777777-7777-7777-7777-777777777777"
LEDGER_ID = "88888888-8888-8888-8888-888888888888"

PROD_SCOPE = ("or_", ("is_test.is.null,is_test.eq.false",))
DEV_SCOPE = ("eq", ("is_test", True))


class Calls:
    """呼び出しごとに異なる結果を返す（行のリスト、または送出する例外）"""

    def __init__(self, *results):
        self.results = list(results)


class FakeQuery:
    """呼ばれたメソッドを記録し、execute() で決まった行を返すクエリ"""

    def __init__(self, name, result):
        self.name = name
        self.result = result
        self.calls = []
        self.kwargs = []

    def __getattr__(self, method):
        def record(*args, **kwargs):
            self.calls.append((method, args))
            self.kwargs.append((method, kwargs))
            return self

        return record

    def execute(self):
        if isinstance(self.result, Exception):
            raise self.result
        return MagicMock(data=self.result)


class FakeSupabase:
    """テーブル名ごとに結果を返す Supabase クライアントのモック"""

    def __init__(self, tables):
        self.tables = tables
        self.queries = []

    def table(self, name):
        result = self.tables.get(name, [])
        if isinstance(result, Calls):
            result = result.results.pop(0)
        query = FakeQuery(name, result)
        self.queries.append(query)
        return query

    def queries_for(self, name):
        return [q for q in self.queries if q.name == name]

    def inserted(self, name):
        return [
            args[0]
            for q in self.queries_for(name)
            for method, args in q.calls
            if method == "insert"
        ]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "ledger_sync_api_key_prod", PROD_KEY)
    monkeypatch.setattr(settings, "ledger_sync_api_key_dev", DEV_KEY)
    yield TestClient(app)
    app.dependency_overrides.clear()


def _use(tables):
    fake = FakeSupabase(tables)
    app.dependency_overrides[get_admin_supabase_client_dep] = lambda: fake
    return fake


# ============================================
# API キー必須
# ============================================


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", f"/api/v1/political-funds/{LEDGER_ID}"),
        ("get", f"/api/v1/election-funds/{LEDGER_ID}"),
        ("get", "/api/v1/polimoney/politicians"),
        ("get", "/api/v1/polimoney/elections"),
        ("get", "/api/v1/master/account-codes"),
        ("get", "/api/v1/sync/status"),
        ("get", f"/api/v1/politicians?ledger_user_id={USER_ID}"),
        ("get", "/api/v1/organizations"),
        ("get", f"/api/v1/organizations/managed?ledger_user_id={USER_ID}"),
        ("get", f"/api/v1/organizations/{ORG_ID}"),
        ("get", "/api/v1/elections"),
        ("post", "/api/v1/politician-elections"),
        ("post", "/api/v1/politician-organizations/resolve"),
    ],
)
@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong"}])
def test_all_v1_routes_require_api_key(client, method, path, headers):
    fake = _use({})
    res = getattr(client, method)(path, headers=headers)
    assert res.status_code == 401
    assert fake.queries == []


def test_health_is_open(client):
    assert client.get("/health").status_code != 401


# ============================================
# GET /politicians
# ============================================

POLITICIAN = {
    "id": POLITICIAN_ID,
    "name": "山田 太郎",
    "ledger_user_id": USER_ID,
    "is_verified": True,
    "is_test": False,
}


def test_politicians_by_ledger_user_prod_scope(client):
    fake = _use({"politicians": [POLITICIAN]})
    res = client.get(f"/api/v1/politicians?ledger_user_id={USER_ID}", headers=PROD)
    assert res.status_code == 200
    data = res.json()["data"]
    assert len(data) == 1 and data[0]["id"] == POLITICIAN_ID
    calls = fake.queries_for("politicians")[0].calls
    assert ("eq", ("ledger_user_id", USER_ID)) in calls
    assert PROD_SCOPE in calls
    assert DEV_SCOPE not in calls


def test_politicians_dev_scope(client):
    fake = _use({"politicians": []})
    res = client.get(f"/api/v1/politicians?ledger_user_id={USER_ID}", headers=DEV)
    assert res.status_code == 200
    calls = fake.queries_for("politicians")[0].calls
    assert DEV_SCOPE in calls
    assert PROD_SCOPE not in calls


@pytest.mark.parametrize("query", ["", "?ledger_user_id=not-a-uuid"])
def test_politicians_requires_valid_ledger_user_id(client, query):
    _use({})
    res = client.get(f"/api/v1/politicians{query}", headers=PROD)
    assert res.status_code == 422


# ============================================
# /organizations
# ============================================

ORG = {"id": ORG_ID, "name": "山田太郎後援会", "type": "support_group", "is_active": True}


@pytest.mark.parametrize("headers,scope", [(PROD, PROD_SCOPE), (DEV, DEV_SCOPE)])
def test_list_organizations(client, headers, scope):
    fake = _use({"organizations": [ORG]})
    res = client.get("/api/v1/organizations", headers=headers)
    assert res.status_code == 200
    assert res.json()["data"][0]["id"] == ORG_ID
    calls = fake.queries_for("organizations")[0].calls
    assert ("eq", ("is_active", True)) in calls
    assert ("order", ("name",)) in calls
    assert scope in calls


def test_managed_organizations(client):
    fake = _use(
        {
            "organization_managers": [
                {
                    "organization_id": ORG_ID,
                    "verified_at": "2026-01-01T00:00:00+00:00",
                    "verified_domain": "example.jp",
                }
            ],
            "organizations": [ORG],
        }
    )
    res = client.get(
        f"/api/v1/organizations/managed?ledger_user_id={USER_ID}", headers=DEV
    )
    assert res.status_code == 200
    data = res.json()["data"]
    assert len(data) == 1
    assert data[0]["id"] == ORG_ID
    assert data[0]["manager_verified_at"] == "2026-01-01T00:00:00+00:00"
    assert data[0]["manager_verified_domain"] == "example.jp"

    manager_calls = fake.queries_for("organization_managers")[0].calls
    assert ("eq", ("ledger_user_id", USER_ID)) in manager_calls
    assert ("eq", ("is_active", True)) in manager_calls
    assert DEV_SCOPE in manager_calls
    org_calls = fake.queries_for("organizations")[0].calls
    assert ("in_", ("id", [ORG_ID])) in org_calls
    assert DEV_SCOPE in org_calls


def test_managed_organizations_none(client):
    fake = _use({"organization_managers": []})
    res = client.get(
        f"/api/v1/organizations/managed?ledger_user_id={USER_ID}", headers=PROD
    )
    assert res.status_code == 200
    assert res.json() == {"data": []}
    assert fake.queries_for("organizations") == []


def test_managed_organizations_requires_ledger_user_id(client):
    _use({})
    res = client.get("/api/v1/organizations/managed", headers=PROD)
    assert res.status_code == 422


def test_get_organization(client):
    fake = _use({"organizations": [ORG]})
    res = client.get(f"/api/v1/organizations/{ORG_ID}", headers=PROD)
    assert res.status_code == 200
    assert res.json()["data"]["id"] == ORG_ID
    calls = fake.queries_for("organizations")[0].calls
    assert ("eq", ("id", ORG_ID)) in calls
    assert PROD_SCOPE in calls


def test_get_organization_not_found(client):
    _use({"organizations": []})
    res = client.get(f"/api/v1/organizations/{ORG_ID}", headers=PROD)
    assert res.status_code == 404


def test_get_organization_rejects_bad_id(client):
    _use({})
    res = client.get("/api/v1/organizations/not-a-uuid", headers=PROD)
    assert res.status_code == 422


# ============================================
# GET /elections
# ============================================


@pytest.mark.parametrize("headers,scope", [(PROD, PROD_SCOPE), (DEV, DEV_SCOPE)])
def test_list_elections(client, headers, scope):
    election = {
        "id": ELECTION_ID,
        "name": "2026年 ○○市長選挙",
        "type": "mayor",
        "district_id": None,
        "election_date": "2026-04-01",
        "is_active": True,
    }
    fake = _use({"elections": [election]})
    res = client.get("/api/v1/elections", headers=headers)
    assert res.status_code == 200
    assert res.json()["data"][0]["id"] == ELECTION_ID
    calls = fake.queries_for("elections")[0].calls
    assert ("eq", ("is_active", True)) in calls
    assert ("order", ("election_date",)) in calls
    assert ("order", {"desc": True}) in fake.queries_for("elections")[0].kwargs
    assert scope in calls


# ============================================
# POST /politician-elections
# ============================================

PE_BODY = {
    "ledger_user_id": USER_ID,
    "politician_id": POLITICIAN_ID,
    "election_id": ELECTION_ID,
}
ELECTION_ROW = {"id": ELECTION_ID, "is_active": True}
PE_ROW = {"id": LINK_ID, "politician_id": POLITICIAN_ID, "election_id": ELECTION_ID}


def test_politician_election_created(client):
    fake = _use(
        {
            "politicians": [POLITICIAN],
            "elections": [ELECTION_ROW],
            "politician_elections": Calls([], [{**PE_ROW, "created_at": "x"}]),
        }
    )
    res = client.post("/api/v1/politician-elections", json=PE_BODY, headers=PROD)
    assert res.status_code == 201
    assert res.json() == {"data": PE_ROW, "action": "created"}
    assert fake.inserted("politician_elections") == [
        {"politician_id": POLITICIAN_ID, "election_id": ELECTION_ID}
    ]
    assert PROD_SCOPE in fake.queries_for("politicians")[0].calls
    assert PROD_SCOPE in fake.queries_for("elections")[0].calls


def test_politician_election_existing(client):
    fake = _use(
        {
            "politicians": [{**POLITICIAN, "is_test": True}],
            "elections": [ELECTION_ROW],
            "politician_elections": [PE_ROW],
        }
    )
    res = client.post("/api/v1/politician-elections", json=PE_BODY, headers=DEV)
    assert res.status_code == 200
    assert res.json() == {"data": PE_ROW, "action": "existing"}
    assert fake.inserted("politician_elections") == []
    assert DEV_SCOPE in fake.queries_for("politicians")[0].calls
    assert DEV_SCOPE in fake.queries_for("elections")[0].calls


def test_politician_election_race_returns_existing(client):
    conflict = APIError({"code": "23505", "message": "duplicate key"})
    _use(
        {
            "politicians": [POLITICIAN],
            "elections": [ELECTION_ROW],
            "politician_elections": Calls([], conflict, [PE_ROW]),
        }
    )
    res = client.post("/api/v1/politician-elections", json=PE_BODY, headers=PROD)
    assert res.status_code == 200
    assert res.json() == {"data": PE_ROW, "action": "existing"}


@pytest.mark.parametrize(
    "politicians",
    [
        [{**POLITICIAN, "ledger_user_id": OTHER_USER_ID}],
        [{**POLITICIAN, "is_verified": False}],
        [],
    ],
    ids=["other-user", "not-verified", "not-found"],
)
def test_politician_election_forbidden(client, politicians):
    fake = _use(
        {
            "politicians": politicians,
            "elections": [ELECTION_ROW],
            "politician_elections": [],
        }
    )
    res = client.post("/api/v1/politician-elections", json=PE_BODY, headers=PROD)
    assert res.status_code == 403
    assert fake.inserted("politician_elections") == []


@pytest.mark.parametrize("elections", [[], [{**ELECTION_ROW, "is_active": False}]])
def test_politician_election_election_not_found(client, elections):
    fake = _use({"politicians": [POLITICIAN], "elections": elections})
    res = client.post("/api/v1/politician-elections", json=PE_BODY, headers=PROD)
    assert res.status_code == 404
    assert fake.inserted("politician_elections") == []


def test_politician_election_rejects_bad_body(client):
    _use({})
    res = client.post(
        "/api/v1/politician-elections",
        json={**PE_BODY, "election_id": "nope"},
        headers=PROD,
    )
    assert res.status_code == 422


# ============================================
# POST /politician-organizations/resolve
# ============================================

RESOLVE_BODY = {"ledger_user_id": USER_ID, "organization_id": ORG_ID}
REP_LINK = {
    "id": LINK_ID,
    "politician_id": POLITICIAN_ID,
    "organization_id": ORG_ID,
    "role": "representative",
}


def test_resolve_as_manager(client):
    fake = _use(
        {
            "organizations": [{"id": ORG_ID}],
            "politician_organizations": [REP_LINK],
            "organization_managers": [{"id": "m-1"}],
        }
    )
    res = client.post(
        "/api/v1/politician-organizations/resolve", json=RESOLVE_BODY, headers=DEV
    )
    assert res.status_code == 200
    assert res.json() == {"data": REP_LINK}
    link_calls = fake.queries_for("politician_organizations")[0].calls
    assert ("eq", ("role", "representative")) in link_calls
    assert ("eq", ("is_active", True)) in link_calls
    assert not any(m == "insert" for m, _ in link_calls)
    assert DEV_SCOPE in fake.queries_for("organizations")[0].calls
    assert DEV_SCOPE in fake.queries_for("organization_managers")[0].calls


def test_resolve_as_representative_politician(client):
    fake = _use(
        {
            "organizations": [{"id": ORG_ID}],
            "politician_organizations": [REP_LINK],
            "organization_managers": [],
            "politicians": [{"id": POLITICIAN_ID}],
        }
    )
    res = client.post(
        "/api/v1/politician-organizations/resolve", json=RESOLVE_BODY, headers=PROD
    )
    assert res.status_code == 200
    assert res.json() == {"data": REP_LINK}
    rep_calls = fake.queries_for("politicians")[0].calls
    assert ("in_", ("id", [POLITICIAN_ID])) in rep_calls
    assert ("eq", ("ledger_user_id", USER_ID)) in rep_calls
    assert PROD_SCOPE in rep_calls


def test_resolve_forbidden_when_not_manager_nor_representative(client):
    _use(
        {
            "organizations": [{"id": ORG_ID}],
            "politician_organizations": [REP_LINK],
            "organization_managers": [],
            "politicians": [],
        }
    )
    res = client.post(
        "/api/v1/politician-organizations/resolve", json=RESOLVE_BODY, headers=PROD
    )
    assert res.status_code == 403


def test_resolve_no_representative(client):
    _use(
        {
            "organizations": [{"id": ORG_ID}],
            "politician_organizations": [],
            "organization_managers": [{"id": "m-1"}],
        }
    )
    res = client.post(
        "/api/v1/politician-organizations/resolve", json=RESOLVE_BODY, headers=PROD
    )
    assert res.status_code == 409
    assert "代表者の紐付けがありません" in res.json()["detail"]


def test_resolve_multiple_representatives(client):
    _use(
        {
            "organizations": [{"id": ORG_ID}],
            "politician_organizations": [REP_LINK, {**REP_LINK, "id": "other-link"}],
            "organization_managers": [{"id": "m-1"}],
        }
    )
    res = client.post(
        "/api/v1/politician-organizations/resolve", json=RESOLVE_BODY, headers=PROD
    )
    assert res.status_code == 409
    assert "複数" in res.json()["detail"]


def test_resolve_organization_not_found(client):
    _use({"organizations": []})
    res = client.post(
        "/api/v1/politician-organizations/resolve", json=RESOLVE_BODY, headers=PROD
    )
    assert res.status_code == 404
