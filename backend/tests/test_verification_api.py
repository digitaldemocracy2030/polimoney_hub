"""本人確認 API（Ledger 向け）と審査 API（管理者向け）のテスト

Supabase には接続しない。行を保持して select / insert / update / upsert をまねる簡易な DB に差し替える。
メール送信と DNS の問い合わせもモックにする。
"""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.routers.verifications as verifications_router
from app.config import settings
from app.core.admin_auth import AdminUser, require_admin_user
from app.database.supabase import get_admin_supabase_client_dep
from app.main import app
from app.services import dns_txt, verification
from app.services.mailer import MailNotConfiguredError

PROD = {"X-API-Key": "test-prod-key"}
DEV = {"X-API-Key": "test-dev-key"}
USER_ID = "11111111-1111-1111-1111-111111111111"
OTHER_USER_ID = "22222222-2222-2222-2222-222222222222"
ADMIN_ID = "99999999-9999-9999-9999-999999999999"


# ============================================
# 簡易 DB
# ============================================


class FakeQuery:
    def __init__(self, db, table):
        self.db = db
        self.table = table
        self.op = "select"
        self.payload = None
        self.on_conflict = None
        self.filters = []
        self.limit_n = None

    # --- 操作 ---
    def select(self, *_args, **_kwargs):
        return self

    def insert(self, payload):
        self.op, self.payload = "insert", payload
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def upsert(self, payload, on_conflict=None):
        self.op, self.payload, self.on_conflict = "upsert", payload, on_conflict
        return self

    # --- 絞り込み ---
    def eq(self, column, value):
        self.filters.append(lambda r: r.get(column) == value)
        return self

    def in_(self, column, values):
        self.filters.append(lambda r: r.get(column) in values)
        return self

    def or_(self, expression):
        # apply_test_scope の "is_test.is.null,is_test.eq.false" だけに対応
        assert expression == "is_test.is.null,is_test.eq.false", expression
        self.filters.append(lambda r: r.get("is_test") in (None, False))
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, n):
        self.limit_n = n
        return self

    def execute(self):
        rows = self.db.rows.setdefault(self.table, [])
        if self.op == "insert":
            row = {"id": str(uuid.uuid4()), "created_at": "2026-11-24T00:00:00+00:00", **self.payload}
            rows.append(row)
            return SimpleNamespace(data=[dict(row)])
        if self.op == "upsert":
            keys = self.on_conflict.split(",")
            for row in rows:
                if all(row.get(k) == self.payload[k] for k in keys):
                    row.update(self.payload)
                    return SimpleNamespace(data=[dict(row)])
            row = {"id": str(uuid.uuid4()), **self.payload}
            rows.append(row)
            return SimpleNamespace(data=[dict(row)])
        matched = [r for r in rows if all(f(r) for f in self.filters)]
        if self.op == "update":
            for row in matched:
                row.update(self.payload)
        if self.limit_n is not None:
            matched = matched[: self.limit_n]
        return SimpleNamespace(data=[dict(r) for r in matched])


class FakeDB:
    def __init__(self, **tables):
        self.rows = {name: [dict(r) for r in rows] for name, rows in tables.items()}
        self.auth = SimpleNamespace(get_user=self._get_user)
        self.tokens = {}

    def table(self, name):
        return FakeQuery(self, name)

    def _get_user(self, token):
        if token not in self.tokens:
            raise Exception("invalid token")
        return SimpleNamespace(user=SimpleNamespace(id=self.tokens[token]))

    def all(self, table):
        return self.rows.get(table, [])


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "ledger_sync_api_key_prod", "test-prod-key")
    monkeypatch.setattr(settings, "ledger_sync_api_key_dev", "test-dev-key")
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def sent_mail(monkeypatch):
    mails = []
    monkeypatch.setattr(
        verifications_router,
        "send_mail",
        lambda to, subject, text: mails.append({"to": to, "subject": subject, "text": text}),
    )
    return mails


def use(db, admin=True):
    app.dependency_overrides[get_admin_supabase_client_dep] = lambda: db
    if admin:
        app.dependency_overrides[require_admin_user] = lambda: AdminUser(
            id=ADMIN_ID, email="admin@example.org", name="管理者", role="admin"
        )
    return db


def politician_body(**overrides):
    body = {
        "ledger_user_id": USER_ID,
        "ledger_user_email": "user@example.org",
        "name": "山田 太郎",
        "official_email": "yamada@city.example.lg.jp",
        "party": "無所属",
        "official_url": "https://yamada.example.jp",
        "political_fund_report_info": {
            "organization_name": "山田太郎後援会",
            "representative_name": "山田 太郎",
            "registration_authority": "東京都選挙管理委員会",
        },
    }
    body.update(overrides)
    return body


def org_body(**overrides):
    body = {
        "ledger_user_id": USER_ID,
        "ledger_user_email": "user@example.org",
        "organization_name": "山田太郎後援会",
        "official_email": "info@yamada-koenkai.example.jp",
        "political_fund_report_info": {
            "organization_name": "山田太郎後援会",
            "representative_name": "山田 太郎",
            "registration_authority": "東京都選挙管理委員会",
        },
    }
    body.update(overrides)
    return body


def minutes_ago(minutes):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


# ============================================
# 申請
# ============================================


def test_create_lg_jp_uses_email_method(client):
    db = use(FakeDB())
    res = client.post("/api/v1/politician-verifications", json=politician_body(), headers=PROD)
    assert res.status_code == 201
    data = res.json()["data"]
    assert data["verification_method"] == "email"
    assert data["is_lg_domain"] is True
    assert data["official_domain"] == "city.example.lg.jp"
    assert data["dns_txt_token"] is None
    assert data["status"] == "pending"
    assert "verification_code" not in data
    row = db.all("politician_verifications")[0]
    assert row["politician_name"] == "山田 太郎"
    assert row["official_url"] == "https://yamada.example.jp"
    assert row["is_test"] is False


def test_create_other_domain_uses_dns_method(client):
    use(FakeDB())
    res = client.post(
        "/api/v1/politician-verifications",
        json=politician_body(official_email="taro@yamada.example.jp"),
        headers=PROD,
    )
    assert res.status_code == 201
    data = res.json()["data"]
    assert data["verification_method"] == "dns_txt"
    assert data["dns_txt_token"]


def test_create_rejects_free_mail(client):
    db = use(FakeDB())
    res = client.post(
        "/api/v1/politician-verifications",
        json=politician_body(official_email="yamada@gmail.com"),
        headers=PROD,
    )
    assert res.status_code == 400
    assert db.all("politician_verifications") == []


def test_create_requires_registration_info(client):
    use(FakeDB())
    body = politician_body()
    del body["political_fund_report_info"]
    res = client.post("/api/v1/politician-verifications", json=body, headers=PROD)
    assert res.status_code == 400


def test_create_conflicts_with_active_request(client):
    use(FakeDB(politician_verifications=[
        {"id": "v1", "ledger_user_id": USER_ID, "status": "email_sent", "is_test": False}
    ]))
    res = client.post("/api/v1/politician-verifications", json=politician_body(), headers=PROD)
    assert res.status_code == 409


def test_create_with_dev_key_is_test_data(client):
    db = use(FakeDB(politician_verifications=[
        # 本番データの手続き中の申請は、テストデータの申請を妨げない
        {"id": "v1", "ledger_user_id": USER_ID, "status": "email_sent", "is_test": False}
    ]))
    res = client.post("/api/v1/politician-verifications", json=politician_body(), headers=DEV)
    assert res.status_code == 201
    assert db.all("politician_verifications")[-1]["is_test"] is True


def test_list_by_user_is_scoped_and_hides_code(client):
    use(FakeDB(politician_verifications=[
        {"id": "v1", "ledger_user_id": USER_ID, "status": "email_sent", "is_test": False,
         "verification_code": "hash", "verification_attempts": 1},
        {"id": "v2", "ledger_user_id": USER_ID, "status": "pending", "is_test": True},
        {"id": "v3", "ledger_user_id": OTHER_USER_ID, "status": "pending", "is_test": False},
    ]))
    res = client.get(f"/api/v1/politician-verifications/user/{USER_ID}", headers=PROD)
    assert res.status_code == 200
    data = res.json()["data"]
    assert [d["id"] for d in data] == ["v1"]
    assert "verification_code" not in data[0]
    assert "verification_attempts" not in data[0]


# ============================================
# メール認証
# ============================================


def _email_verification(**overrides):
    row = {
        "id": str(uuid.uuid4()),
        "ledger_user_id": USER_ID,
        "official_email": "yamada@city.example.lg.jp",
        "official_domain": "city.example.lg.jp",
        "verification_method": "email",
        "status": "pending",
        "is_test": False,
        "verification_attempts": 0,
    }
    row.update(overrides)
    return row


def test_send_code_emails_hashed_code(client, sent_mail):
    row = _email_verification()
    db = use(FakeDB(politician_verifications=[row]))
    res = client.post(
        f"/api/v1/politician-verifications/{row['id']}/send-verification",
        json={"ledger_user_id": USER_ID},
        headers=PROD,
    )
    assert res.status_code == 200
    assert "code" not in res.json()
    assert len(sent_mail) == 1 and sent_mail[0]["to"] == row["official_email"]
    code = sent_mail[0]["text"].split("確認コード: ")[1][:6]
    stored = db.all("politician_verifications")[0]
    assert stored["status"] == "email_sent"
    assert stored["verification_code"] == verification.hash_code(code)
    assert stored["verification_code"] != code


def test_send_code_with_dev_key_returns_code_without_mail(client, sent_mail):
    row = _email_verification(is_test=True)
    use(FakeDB(politician_verifications=[row]))
    res = client.post(
        f"/api/v1/politician-verifications/{row['id']}/send-verification",
        json={"ledger_user_id": USER_ID},
        headers=DEV,
    )
    assert res.status_code == 200
    assert len(res.json()["code"]) == 6
    assert sent_mail == []


def test_send_code_requires_owner(client, sent_mail):
    row = _email_verification()
    use(FakeDB(politician_verifications=[row]))
    res = client.post(
        f"/api/v1/politician-verifications/{row['id']}/send-verification",
        json={"ledger_user_id": OTHER_USER_ID},
        headers=PROD,
    )
    assert res.status_code == 404
    assert sent_mail == []


def test_send_code_dev_key_cannot_touch_production_request(client, sent_mail):
    row = _email_verification(is_test=False)
    use(FakeDB(politician_verifications=[row]))
    res = client.post(
        f"/api/v1/politician-verifications/{row['id']}/send-verification",
        json={"ledger_user_id": USER_ID},
        headers=DEV,
    )
    assert res.status_code == 404


def test_send_code_rate_limited(client, sent_mail):
    row = _email_verification(status="email_sent", verification_code_sent_at=minutes_ago(0))
    use(FakeDB(politician_verifications=[row]))
    res = client.post(
        f"/api/v1/politician-verifications/{row['id']}/send-verification",
        json={"ledger_user_id": USER_ID},
        headers=PROD,
    )
    assert res.status_code == 429


def test_send_code_503_when_mail_not_configured(client, monkeypatch):
    def not_configured(*_args):
        raise MailNotConfiguredError()

    monkeypatch.setattr(verifications_router, "send_mail", not_configured)
    row = _email_verification()
    use(FakeDB(politician_verifications=[row]))
    res = client.post(
        f"/api/v1/politician-verifications/{row['id']}/send-verification",
        json={"ledger_user_id": USER_ID},
        headers=PROD,
    )
    assert res.status_code == 503


def test_send_code_rejected_for_dns_request(client, sent_mail):
    row = _email_verification(verification_method="dns_txt")
    use(FakeDB(politician_verifications=[row]))
    res = client.post(
        f"/api/v1/politician-verifications/{row['id']}/send-verification",
        json={"ledger_user_id": USER_ID},
        headers=PROD,
    )
    assert res.status_code == 400


def _sent(code="123456", **overrides):
    return _email_verification(
        status="email_sent",
        verification_code=verification.hash_code(code),
        verification_code_sent_at=minutes_ago(1),
        **overrides,
    )


def test_verify_email_success(client):
    row = _sent()
    db = use(FakeDB(politician_verifications=[row]))
    res = client.post(
        f"/api/v1/politician-verifications/{row['id']}/verify-email",
        json={"ledger_user_id": USER_ID, "code": "123456"},
        headers=PROD,
    )
    assert res.status_code == 200
    stored = db.all("politician_verifications")[0]
    assert stored["status"] == "email_verified"
    assert stored["verification_code"] is None
    assert stored["verification_code_verified_at"]


def test_verify_email_wrong_code_counts_attempts(client):
    row = _sent()
    db = use(FakeDB(politician_verifications=[row]))
    res = client.post(
        f"/api/v1/politician-verifications/{row['id']}/verify-email",
        json={"ledger_user_id": USER_ID, "code": "000000"},
        headers=PROD,
    )
    assert res.status_code == 400
    stored = db.all("politician_verifications")[0]
    assert stored["status"] == "email_sent"
    assert stored["verification_attempts"] == 1


def test_verify_email_locked_after_max_attempts(client):
    row = _sent(verification_attempts=verification.MAX_CODE_ATTEMPTS)
    use(FakeDB(politician_verifications=[row]))
    res = client.post(
        f"/api/v1/politician-verifications/{row['id']}/verify-email",
        json={"ledger_user_id": USER_ID, "code": "123456"},
        headers=PROD,
    )
    assert res.status_code == 429


def test_verify_email_expired(client):
    row = _sent()
    row["verification_code_sent_at"] = minutes_ago(31)
    use(FakeDB(politician_verifications=[row]))
    res = client.post(
        f"/api/v1/politician-verifications/{row['id']}/verify-email",
        json={"ledger_user_id": USER_ID, "code": "123456"},
        headers=PROD,
    )
    assert res.status_code == 400


# ============================================
# DNS 認証
# ============================================


def _dns_verification(**overrides):
    row = _email_verification(
        official_email="taro@yamada.example.jp",
        official_domain="yamada.example.jp",
        verification_method="dns_txt",
        dns_txt_token="token-abc",
    )
    row.update(overrides)
    return row


def test_verify_dns_success(client, monkeypatch):
    seen = []
    monkeypatch.setattr(
        verifications_router,
        "lookup_txt",
        lambda domain: seen.append(domain) or ["v=spf1 -all", "polimoney-verify=token-abc"],
    )
    row = _dns_verification()
    db = use(FakeDB(politician_verifications=[row]))
    res = client.post(
        f"/api/v1/politician-verifications/{row['id']}/verify-dns",
        json={"ledger_user_id": USER_ID},
        headers=PROD,
    )
    assert res.status_code == 200
    assert seen == ["yamada.example.jp"]
    stored = db.all("politician_verifications")[0]
    assert stored["status"] == "dns_verified"
    assert stored["dns_txt_verified"] is True


def test_verify_dns_record_missing(client, monkeypatch):
    monkeypatch.setattr(verifications_router, "lookup_txt", lambda domain: ["polimoney-verify=other"])
    row = _dns_verification()
    db = use(FakeDB(politician_verifications=[row]))
    res = client.post(
        f"/api/v1/politician-verifications/{row['id']}/verify-dns",
        json={"ledger_user_id": USER_ID},
        headers=PROD,
    )
    assert res.status_code == 400
    assert "polimoney-verify=token-abc" in res.json()["detail"]
    assert db.all("politician_verifications")[0]["status"] == "pending"


def test_dns_txt_value_joins_quoted_parts():
    assert dns_txt._txt_value('"polimoney-verify=" "token-abc"') == "polimoney-verify=token-abc"
    assert dns_txt._txt_value('"v=spf1 -all"') == "v=spf1 -all"


# ============================================
# 政治団体の管理者の申請
# ============================================


def test_org_manager_create_and_unknown_org(client):
    db = use(FakeDB(organizations=[{"id": "org-test", "is_test": True}]))
    res = client.post("/api/v1/organization-manager-verifications", json=org_body(), headers=PROD)
    assert res.status_code == 201
    assert res.json()["data"]["verification_method"] == "dns_txt"
    assert db.all("organization_manager_verifications")[0]["organization_id"] is None

    # テストデータの団体は PROD キーからは見えない
    res = client.post(
        "/api/v1/organization-manager-verifications",
        json=org_body(organization_id="55555555-5555-5555-5555-555555555555"),
        headers=PROD,
    )
    assert res.status_code == 404


# ============================================
# 審査（管理者）
# ============================================


def test_admin_routes_require_login(client):
    use(FakeDB(), admin=False)
    assert client.get("/api/admin/politician-verifications").status_code == 401
    assert client.get(
        "/api/admin/politician-verifications", headers={"Authorization": "Bearer bad"}
    ).status_code == 401


def test_admin_auth_checks_admin_users(client):
    db = use(FakeDB(admin_users=[
        {"id": ADMIN_ID, "email": "admin@example.org", "name": "管理者", "role": "admin", "is_active": True},
        {"id": OTHER_USER_ID, "email": "old@example.org", "name": None, "role": "admin", "is_active": False},
    ]), admin=False)
    db.tokens = {"admin-token": ADMIN_ID, "inactive-token": OTHER_USER_ID, "user-token": USER_ID}

    res = client.get("/api/admin/me", headers={"Authorization": "Bearer admin-token"})
    assert res.status_code == 200
    assert res.json()["data"]["id"] == ADMIN_ID
    for token in ("inactive-token", "user-token"):
        res = client.get("/api/admin/me", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 403


def test_admin_list_filters(client):
    use(FakeDB(politician_verifications=[
        {"id": "v1", "status": "email_verified", "is_test": False, "verification_code": None},
        {"id": "v2", "status": "pending", "is_test": False},
        {"id": "v3", "status": "email_verified", "is_test": True},
    ]))
    res = client.get("/api/admin/politician-verifications?status=email_verified&is_test=false")
    assert [d["id"] for d in res.json()["data"]] == ["v1"]


def test_approve_politician_creates_verified_politician(client):
    row = _email_verification(
        status="email_verified", politician_name="山田 太郎", party="無所属", is_lg_domain=True,
        official_url="https://yamada.example.jp",
        request_type="new", is_test=True,
    )
    db = use(FakeDB(
        politician_verifications=[row],
        # 本番データの同じユーザーの政治家は更新しない
        politicians=[{"id": "p-prod", "ledger_user_id": USER_ID, "is_test": False, "is_verified": False}],
    ))
    res = client.post(f"/api/admin/politician-verifications/{row['id']}/approve")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["status"] == "approved"
    assert data["reviewed_by"] == ADMIN_ID

    politicians = db.all("politicians")
    assert politicians[0]["is_verified"] is False
    created = politicians[1]
    assert data["approved_politician_id"] == created["id"]
    assert created["name"] == "山田 太郎"
    assert created["is_test"] is True
    assert created["is_verified"] is True
    assert created["is_lg_verified"] is True
    assert created["verified_domain"] == "city.example.lg.jp"
    assert created["official_url"] == "https://yamada.example.jp"


def test_approve_politician_updates_existing(client):
    row = _email_verification(
        status="dns_verified", politician_name="山田 太郎", request_type="domain_change",
        official_domain="new.example.jp",
    )
    db = use(FakeDB(
        politician_verifications=[row],
        politicians=[{"id": "p1", "ledger_user_id": USER_ID, "is_test": None,
                      "official_url": "https://old.example.jp"}],
    ))
    res = client.post(f"/api/admin/politician-verifications/{row['id']}/approve")
    assert res.status_code == 200
    assert res.json()["data"]["approved_politician_id"] == "p1"
    politician = db.all("politicians")[0]
    assert politician["is_verified"] is True
    assert politician["verified_domain"] == "new.example.jp"
    assert politician["official_url"] is None
    assert len(db.all("politicians")) == 1


def test_approve_requires_confirmed_status(client):
    row = _email_verification(status="email_sent")
    db = use(FakeDB(politician_verifications=[row]))
    res = client.post(f"/api/admin/politician-verifications/{row['id']}/approve")
    assert res.status_code == 409
    assert db.all("politicians") == []


def test_reject(client):
    row = _email_verification(status="pending")
    db = use(FakeDB(politician_verifications=[row]))
    res = client.post(
        f"/api/admin/politician-verifications/{row['id']}/reject",
        json={"rejection_reason": "届出の内容と一致しません"},
    )
    assert res.status_code == 200
    stored = db.all("politician_verifications")[0]
    assert stored["status"] == "rejected"
    assert stored["rejection_reason"] == "届出の内容と一致しません"

    res = client.post(
        f"/api/admin/politician-verifications/{row['id']}/reject",
        json={"rejection_reason": "再度"},
    )
    assert res.status_code == 409


def test_approve_org_manager_creates_org_and_manager(client):
    row = _dns_verification(
        status="dns_verified", organization_id=None, organization_name="山田太郎後援会",
        organization_type="support_group", request_type="new",
    )
    db = use(FakeDB(organization_manager_verifications=[row]))
    res = client.post(f"/api/admin/organization-manager-verifications/{row['id']}/approve")
    assert res.status_code == 200
    org = db.all("organizations")[0]
    assert org["name"] == "山田太郎後援会"
    assert org["type"] == "support_group"
    assert org["is_verified"] is True
    assert org["is_test"] is False
    manager = db.all("organization_managers")[0]
    assert manager["ledger_user_id"] == USER_ID
    assert manager["organization_id"] == org["id"]
    assert manager["verified_domain"] == "yamada.example.jp"
    assert manager["is_active"] is True
    assert res.json()["data"]["organization_id"] == org["id"]


def test_approve_org_manager_existing_org_upserts_manager(client):
    row = _dns_verification(status="dns_verified", organization_id="org-1", organization_name="団体")
    db = use(FakeDB(
        organization_manager_verifications=[row],
        organizations=[{"id": "org-1", "is_test": False, "is_verified": False}],
        organization_managers=[{"id": "m1", "ledger_user_id": USER_ID, "organization_id": "org-1",
                                "is_active": False}],
    ))
    res = client.post(f"/api/admin/organization-manager-verifications/{row['id']}/approve")
    assert res.status_code == 200
    assert db.all("organizations")[0]["is_verified"] is True
    managers = db.all("organization_managers")
    assert len(managers) == 1 and managers[0]["is_active"] is True


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/politician-verifications",
        f"/api/v1/politician-verifications/{USER_ID}/send-verification",
        "/api/v1/organization-manager-verifications",
        f"/api/v1/organization-manager-verifications/{USER_ID}/verify-dns",
    ],
)
def test_ledger_routes_require_api_key(client, path):
    db = use(FakeDB())
    res = client.post(path, json={}, headers={"X-API-Key": "wrong"})
    assert res.status_code == 401
    assert db.rows == {}


def test_create_rejects_non_http_url(client):
    use(FakeDB())
    res = client.post(
        "/api/v1/politician-verifications",
        json=politician_body(official_url="javascript:alert(1)"),
        headers=PROD,
    )
    assert res.status_code == 400


def test_org_manager_create_stores_role(client):
    db = use(FakeDB())
    res = client.post(
        "/api/v1/organization-manager-verifications",
        json=org_body(role_in_organization="事務局長"),
        headers=PROD,
    )
    assert res.status_code == 201
    assert db.all("organization_manager_verifications")[0]["role_in_organization"] == "事務局長"
