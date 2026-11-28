"""登録申請（選挙・政治団体）と年度のロック解除申請の API（Ledger 向け）と審査 API（管理者向け）のテスト

簡易 DB は tests/test_verification_api.py の FakeDB を使う。
承認の DB 関数（rpc）は呼び出しを記録するだけ。関数そのものは Hub DB でトランザクション内で確かめる。
"""

from datetime import datetime, timedelta, timezone

import pytest
from postgrest.exceptions import APIError

from app.routers.ledger_requests import unlock_status
from tests.test_verification_api import (  # noqa: F401（client は pytest のフィクスチャ）
    ADMIN_ID,
    DEV,
    OTHER_USER_ID,
    PROD,
    USER_ID,
    FakeDB,
    client,
    use,
)

LEDGER_ID = "33333333-3333-3333-3333-333333333333"
POLITICIAN_ID = "44444444-4444-4444-4444-444444444444"


def hours_from_now(hours):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def election_body(**overrides):
    body = {
        "ledger_user_id": USER_ID,
        "name": "2027年 東京都議会議員選挙",
        "type": "PA",
        "area_description": "新宿区",
        "election_date": "2027-07-04",
        "requested_by_email": "user@example.org",
    }
    body.update(overrides)
    return body


def organization_body(**overrides):
    body = {
        "ledger_user_id": USER_ID,
        "name": "山田太郎後援会",
        "type": "support_group",
        "registration_authority": "東京都選挙管理委員会",
        "evidence_type": "registration_notice",
        "evidence_file_url": "https://ledger.example.supabase.co/storage/v1/object/sign/evidence-files/a.pdf?token=x",
        "evidence_file_path": f"{USER_ID}/a.pdf",
        "evidence_file_name": "設立届.pdf",
    }
    body.update(overrides)
    return body


def unlock_body(**overrides):
    body = {
        "ledger_id": LEDGER_ID,
        "ledger_type": "organization",
        "fiscal_year": 2025,
        "requested_by_user_id": USER_ID,
        "requested_by_email": "user@example.org",
        "reason": "領収書の金額の入力を間違えていたため修正したい",
    }
    body.update(overrides)
    return body


def duplicate_insert(_db):
    raise APIError({"message": "duplicate key", "code": "23505"})


# ============================================
# 選挙・政治団体の登録申請（Ledger 向け）
# ============================================


def test_create_election_request(client):
    db = use(FakeDB())
    res = client.post("/api/v1/election-requests", json=election_body(), headers=PROD)
    assert res.status_code == 201
    row = db.all("election_requests")[0]
    assert row["status"] == "pending"
    assert row["is_test"] is False
    assert row["ledger_user_id"] == USER_ID
    assert row["election_date"] == "2027-07-04"
    assert row["requested_by_politician_id"] is None
    assert res.json()["data"]["id"] == row["id"]


def test_create_election_request_with_dev_key_is_test_data(client):
    db = use(FakeDB())
    res = client.post("/api/v1/election-requests", json=election_body(), headers=DEV)
    assert res.status_code == 201
    assert db.all("election_requests")[0]["is_test"] is True


def test_create_election_request_requires_api_key(client):
    use(FakeDB())
    res = client.post("/api/v1/election-requests", json=election_body())
    assert res.status_code == 401


def test_create_election_request_rejects_blank_name(client):
    db = use(FakeDB())
    res = client.post("/api/v1/election-requests", json=election_body(name="   "), headers=PROD)
    assert res.status_code == 400
    assert db.all("election_requests") == []


def test_create_election_request_duplicate_pending_is_conflict(client):
    db = use(FakeDB())
    db.before_write.append(duplicate_insert)
    res = client.post("/api/v1/election-requests", json=election_body(), headers=PROD)
    assert res.status_code == 409
    assert "審査中" in res.json()["detail"]


def test_create_election_request_accepts_own_politician(client):
    db = use(
        FakeDB(
            politicians=[{"id": POLITICIAN_ID, "ledger_user_id": USER_ID, "is_test": False}]
        )
    )
    res = client.post(
        "/api/v1/election-requests",
        json=election_body(requested_by_politician_id=POLITICIAN_ID),
        headers=PROD,
    )
    assert res.status_code == 201
    assert db.all("election_requests")[0]["requested_by_politician_id"] == POLITICIAN_ID


@pytest.mark.parametrize(
    "politician",
    [
        # 他人の政治家
        {"id": POLITICIAN_ID, "ledger_user_id": OTHER_USER_ID, "is_test": False},
        # 本番キーからテストデータの政治家
        {"id": POLITICIAN_ID, "ledger_user_id": USER_ID, "is_test": True},
    ],
)
def test_create_election_request_rejects_other_politician(client, politician):
    db = use(FakeDB(politicians=[politician]))
    res = client.post(
        "/api/v1/election-requests",
        json=election_body(requested_by_politician_id=POLITICIAN_ID),
        headers=PROD,
    )
    # 他人・別の範囲の政治家は 404（存在を明かさない）
    assert res.status_code == 404
    assert db.all("election_requests") == []


def test_create_organization_request(client):
    db = use(FakeDB())
    res = client.post("/api/v1/organization-requests", json=organization_body(), headers=DEV)
    assert res.status_code == 201
    row = db.all("organization_requests")[0]
    assert row["is_test"] is True
    assert row["evidence_file_path"] == f"{USER_ID}/a.pdf"
    assert row["status"] == "pending"


def test_create_organization_request_requires_https_evidence_url(client):
    db = use(FakeDB())
    res = client.post(
        "/api/v1/organization-requests",
        json=organization_body(evidence_file_url="http://example.org/a.pdf"),
        headers=PROD,
    )
    assert res.status_code == 400
    assert db.all("organization_requests") == []


def test_create_organization_request_duplicate_pending_is_conflict(client):
    db = use(FakeDB())
    db.before_write.append(duplicate_insert)
    res = client.post("/api/v1/organization-requests", json=organization_body(), headers=PROD)
    assert res.status_code == 409


# ============================================
# 年度のロック解除（Ledger 向け）
# ============================================


def test_create_unlock_request(client):
    db = use(FakeDB())
    res = client.post("/api/v1/unlock-requests", json=unlock_body(), headers=PROD)
    assert res.status_code == 201
    row = db.all("unlock_requests")[0]
    assert row["status"] == "pending"
    assert row["is_test"] is False
    assert row["fiscal_year"] == 2025


def test_create_unlock_request_requires_reason(client):
    db = use(FakeDB())
    res = client.post(
        "/api/v1/unlock-requests", json=unlock_body(reason="短い理由です。         "), headers=PROD
    )
    assert res.status_code == 400
    assert db.all("unlock_requests") == []


def test_create_unlock_request_duplicate_pending_is_conflict(client):
    db = use(FakeDB())
    db.before_write.append(duplicate_insert)
    res = client.post("/api/v1/unlock-requests", json=unlock_body(), headers=PROD)
    assert res.status_code == 409
    assert "申請中" in res.json()["detail"]


def test_check_unlock_status_unlocked_and_pending(client):
    use(
        FakeDB(
            unlock_requests=[
                {
                    "id": "u1", "ledger_id": LEDGER_ID, "fiscal_year": 2024, "status": "pending",
                    "reason": "修正したい理由がある", "is_test": False,
                    "created_at": "2026-11-25T00:00:00+00:00",
                },
                {
                    "id": "u2", "ledger_id": LEDGER_ID, "fiscal_year": 2025, "status": "approved",
                    "unlock_expires_at": hours_from_now(24), "is_test": False,
                },
            ]
        )
    )
    res = client.get(f"/api/v1/unlock-requests/check/{LEDGER_ID}", headers=PROD)
    assert res.status_code == 200
    data = res.json()
    assert data["is_unlocked"] is True
    assert data["unlock_request"]["id"] == "u2"
    assert data["pending_request"]["id"] == "u1"

    # 年度で絞り込む
    res = client.get(
        f"/api/v1/unlock-requests/check/{LEDGER_ID}?fiscal_year=2024", headers=PROD
    )
    data = res.json()
    assert data["is_unlocked"] is False
    assert data["pending_request"]["fiscal_year"] == 2024


def test_check_unlock_status_scoped_to_test_data(client):
    use(
        FakeDB(
            unlock_requests=[
                {
                    "id": "u1", "ledger_id": LEDGER_ID, "fiscal_year": 2025, "status": "approved",
                    "unlock_expires_at": hours_from_now(24), "is_test": True,
                },
            ]
        )
    )
    # 本番キーからはテストデータの申請は見えない
    res = client.get(f"/api/v1/unlock-requests/check/{LEDGER_ID}", headers=PROD)
    assert res.json()["is_unlocked"] is False
    res = client.get(f"/api/v1/unlock-requests/check/{LEDGER_ID}", headers=DEV)
    assert res.json()["is_unlocked"] is True


def test_unlock_status_ignores_expired():
    now = datetime.now(timezone.utc)
    expired = {"id": "a", "status": "approved", "unlock_expires_at": (now - timedelta(hours=1)).isoformat()}
    assert unlock_status(expired, None, now) == {"is_unlocked": False, "pending_request": None}


def test_check_unlock_status_not_hidden_by_many_rejections(client):
    rejected = [
        {
            "id": f"r{i}", "ledger_id": LEDGER_ID, "fiscal_year": 2025, "status": "rejected",
            "is_test": False, "created_at": "2026-11-27T00:00:00+00:00",
        }
        for i in range(60)
    ]
    approved = {
        "id": "a1", "ledger_id": LEDGER_ID, "fiscal_year": 2025, "status": "approved",
        "unlock_expires_at": hours_from_now(24), "is_test": False,
        "requested_by_email": "user@example.org", "reason": "修正したい理由がある",
        "created_at": "2026-11-20T00:00:00+00:00",
    }
    use(FakeDB(unlock_requests=rejected + [approved]))
    res = client.get(f"/api/v1/unlock-requests/check/{LEDGER_ID}?fiscal_year=2025", headers=PROD)
    data = res.json()
    assert data["is_unlocked"] is True
    # 申請者のメールアドレスなどは返さない
    assert set(data["unlock_request"]) == {
        "id", "status", "fiscal_year", "approved_at", "unlock_expires_at"
    }


# ============================================
# 審査（管理者向け）
# ============================================


def test_admin_requires_login(client):
    use(FakeDB(), admin=False)
    res = client.get("/api/admin/election-requests")
    assert res.status_code == 401


def test_admin_list_filters(client):
    use(
        FakeDB(
            election_requests=[
                {"id": "e1", "status": "pending", "is_test": False},
                {"id": "e2", "status": "approved", "is_test": False},
                {"id": "e3", "status": "pending", "is_test": True},
            ]
        )
    )
    res = client.get("/api/admin/election-requests?status=pending&is_test=false")
    assert res.status_code == 200
    assert [r["id"] for r in res.json()["data"]] == ["e1"]


def test_admin_approve_election_request_calls_function(client):
    request_id = "55555555-5555-5555-5555-555555555555"
    election_id = "66666666-6666-6666-6666-666666666666"
    db = use(FakeDB())
    db.rpc_result = {"id": request_id, "status": "approved", "approved_election_id": election_id}
    res = client.post(
        f"/api/admin/election-requests/{request_id}/approve", json={"election_id": election_id}
    )
    assert res.status_code == 200
    assert res.json()["data"]["approved_election_id"] == election_id
    assert db.rpc_calls == [(
        "approve_election_request",
        {"p_request_id": request_id, "p_reviewer_id": ADMIN_ID, "p_election_id": election_id},
    )]


def test_admin_approve_organization_request_without_body_creates(client):
    request_id = "55555555-5555-5555-5555-555555555555"
    db = use(FakeDB())
    db.rpc_result = [{"id": request_id, "status": "approved"}]
    res = client.post(f"/api/admin/organization-requests/{request_id}/approve")
    assert res.status_code == 200
    assert db.rpc_calls[0] == (
        "approve_organization_request",
        {"p_request_id": request_id, "p_reviewer_id": ADMIN_ID, "p_organization_id": None},
    )


@pytest.mark.parametrize(
    "message, expected",
    [
        ("request_not_found", 404),
        ("request_not_pending", 409),
        ("election_not_found", 404),
        ("something_else", 500),
    ],
)
def test_admin_approve_maps_function_errors(client, message, expected):
    db = use(FakeDB())
    db.rpc_result = APIError({"message": message, "code": "P0001"})
    res = client.post(
        "/api/admin/election-requests/55555555-5555-5555-5555-555555555555/approve"
    )
    assert res.status_code == expected


def test_admin_reject_election_request(client):
    request_id = "55555555-5555-5555-5555-555555555555"
    db = use(FakeDB(election_requests=[{"id": request_id, "status": "pending"}]))
    res = client.post(
        f"/api/admin/election-requests/{request_id}/reject",
        json={"rejection_reason": "既に登録済みの選挙です"},
    )
    assert res.status_code == 200
    row = db.all("election_requests")[0]
    assert row["status"] == "rejected"
    assert row["reviewed_by"] == ADMIN_ID
    assert row["rejection_reason"] == "既に登録済みの選挙です"


def test_admin_reject_requires_non_blank_reason(client):
    request_id = "55555555-5555-5555-5555-555555555555"
    db = use(FakeDB(election_requests=[{"id": request_id, "status": "pending"}]))
    res = client.post(
        f"/api/admin/election-requests/{request_id}/reject",
        json={"rejection_reason": "   "},
    )
    assert res.status_code == 422
    assert db.all("election_requests")[0]["status"] == "pending"


def test_admin_reject_closed_request_is_conflict(client):
    request_id = "55555555-5555-5555-5555-555555555555"
    use(FakeDB(organization_requests=[{"id": request_id, "status": "approved"}]))
    res = client.post(
        f"/api/admin/organization-requests/{request_id}/reject",
        json={"rejection_reason": "理由"},
    )
    assert res.status_code == 409


def test_admin_reject_concurrently_approved_is_conflict(client):
    request_id = "55555555-5555-5555-5555-555555555555"
    db = use(FakeDB(election_requests=[{"id": request_id, "status": "pending"}]))

    def approve_meanwhile(db):
        db.rows["election_requests"][0]["status"] = "approved"

    db.before_write.append(approve_meanwhile)
    res = client.post(
        f"/api/admin/election-requests/{request_id}/reject",
        json={"rejection_reason": "理由"},
    )
    assert res.status_code == 409
    assert db.all("election_requests")[0]["status"] == "approved"


def test_admin_approve_unlock_request_sets_expiry(client):
    request_id = "55555555-5555-5555-5555-555555555555"
    db = use(FakeDB(unlock_requests=[{"id": request_id, "status": "pending"}]))
    res = client.post(
        f"/api/admin/unlock-requests/{request_id}/approve", json={"unlock_hours": 48}
    )
    assert res.status_code == 200
    row = db.all("unlock_requests")[0]
    assert row["status"] == "approved"
    assert row["approved_by"] == ADMIN_ID
    expires = datetime.fromisoformat(row["unlock_expires_at"])
    approved = datetime.fromisoformat(row["approved_at"])
    assert expires - approved == timedelta(hours=48)


def test_admin_approve_unlock_request_default_is_7_days(client):
    request_id = "55555555-5555-5555-5555-555555555555"
    db = use(FakeDB(unlock_requests=[{"id": request_id, "status": "pending"}]))
    res = client.post(f"/api/admin/unlock-requests/{request_id}/approve")
    assert res.status_code == 200
    row = db.all("unlock_requests")[0]
    expires = datetime.fromisoformat(row["unlock_expires_at"])
    approved = datetime.fromisoformat(row["approved_at"])
    assert expires - approved == timedelta(days=7)


def test_admin_approve_unlock_concurrently_rejected_is_conflict(client):
    request_id = "55555555-5555-5555-5555-555555555555"
    db = use(FakeDB(unlock_requests=[{"id": request_id, "status": "pending"}]))

    def reject_meanwhile(db):
        db.rows["unlock_requests"][0]["status"] = "rejected"

    db.before_write.append(reject_meanwhile)
    res = client.post(f"/api/admin/unlock-requests/{request_id}/approve")
    assert res.status_code == 409
    assert db.all("unlock_requests")[0]["status"] == "rejected"


def test_admin_reject_unlock_request(client):
    request_id = "55555555-5555-5555-5555-555555555555"
    db = use(FakeDB(unlock_requests=[{"id": request_id, "status": "pending"}]))
    res = client.post(
        f"/api/admin/unlock-requests/{request_id}/reject",
        json={"rejection_reason": "修正の必要が確認できません"},
    )
    assert res.status_code == 200
    assert db.all("unlock_requests")[0]["status"] == "rejected"
