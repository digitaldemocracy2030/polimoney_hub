"""Polimoney APIのテスト"""

from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, status
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.database.supabase import get_supabase_client_dep
from app.routers import polimoney
from app.utils.election_funds_response import sum_public_expense_by_ledger
from app.utils.polimoney_response import MultipleCandidatesException

ELECTION_ID = UUID("11111111-1111-1111-1111-111111111111")
ELECTION_ID_2 = UUID("22222222-2222-2222-2222-222222222222")
POLITICIAN_ID_1 = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
POLITICIAN_ID_2 = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
LEDGER_ID_1 = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
LEDGER_ID_2 = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
NON_ELECTION_LEDGER_ID = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
MISSING_ELECTION_ID = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")


def _make_execute_response(data):
    response = MagicMock()
    response.data = data
    return response


def _chainable_query(final_data):
    query = MagicMock()

    def configure(method_name):
        def chained(*_args, **_kwargs):
            return query

        setattr(query, method_name, chained)

    for method_name in (
        "select",
        "eq",
        "not_",
        "is_",
        "in_",
        "order",
        "maybe_single",
        "single",
    ):
        configure(method_name)

    query.not_.is_ = MagicMock(return_value=query)
    query.execute.return_value = _make_execute_response(final_data)
    return query


def _create_test_app(mock_supabase: MagicMock) -> FastAPI:
    test_app = FastAPI()

    @test_app.exception_handler(MultipleCandidatesException)
    async def multiple_candidates_exception_handler(_request, exc):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=exc.error.model_dump(mode="json"),
        )

    test_app.include_router(polimoney.router, prefix="/api/v1")
    test_app.dependency_overrides[get_supabase_client_dep] = lambda: mock_supabase
    return test_app


class TestSumPublicExpenseByLedger:
    """公費負担集計ユーティリティのテスト"""

    def test_sums_positive_amounts_per_ledger(self):
        journals = [
            {"ledger_id": "ledger-1", "public_expense_amount": 100},
            {"ledger_id": "ledger-1", "public_expense_amount": 50},
            {"ledger_id": "ledger-2", "public_expense_amount": 200},
        ]
        assert sum_public_expense_by_ledger(journals) == {
            "ledger-1": 150,
            "ledger-2": 200,
        }

    def test_skips_zero_negative_and_missing_amounts(self):
        journals = [
            {"ledger_id": "ledger-1", "public_expense_amount": 0},
            {"ledger_id": "ledger-1", "public_expense_amount": -10},
            {"ledger_id": "ledger-1", "public_expense_amount": None},
            {"ledger_id": None, "public_expense_amount": 100},
        ]
        assert sum_public_expense_by_ledger(journals) == {}


class TestPolimoneyElectionsAPI:
    """公開選挙一覧APIのテスト"""

    def test_deduplicates_and_sorts_elections(self):
        mock_supabase = MagicMock()
        mock_supabase.table.return_value = _chainable_query(
            [
                {
                    "election_id": str(ELECTION_ID),
                    "elections": {
                        "id": str(ELECTION_ID),
                        "name": "古い選挙",
                        "type": "general",
                        "election_date": "2024-01-01",
                        "district": {"id": str(uuid4()), "name": "第1区"},
                    },
                },
                {
                    "election_id": str(ELECTION_ID),
                    "elections": {
                        "id": str(ELECTION_ID),
                        "name": "古い選挙",
                        "type": "general",
                        "election_date": "2024-01-01",
                        "district": {"id": str(uuid4()), "name": "第1区"},
                    },
                },
                {
                    "election_id": str(ELECTION_ID_2),
                    "elections": {
                        "id": str(ELECTION_ID_2),
                        "name": "新しい選挙",
                        "type": "general",
                        "election_date": "2026-01-01",
                        "district": {"id": str(uuid4()), "name": "第2区"},
                    },
                },
            ]
        )

        client = TestClient(_create_test_app(mock_supabase))
        response = client.get("/api/v1/polimoney/elections")

        assert response.status_code == 200
        body = response.json()
        assert body["total_count"] == 2
        assert body["data"][0]["name"] == "新しい選挙"
        assert body["data"][1]["name"] == "古い選挙"


class TestPolimoneyElectionJournalsAPI:
    """選挙別仕訳APIのテスト"""

    @pytest.mark.asyncio
    async def test_returns_404_when_election_not_found(self):
        mock_supabase = MagicMock()
        elections_query = _chainable_query(None)
        mock_supabase.table.side_effect = (
            lambda name: elections_query if name == "elections" else MagicMock()
        )

        test_app = _create_test_app(mock_supabase)
        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://testserver",
        ) as client:
            response = await client.get(
                f"/api/v1/polimoney/elections/{MISSING_ELECTION_ID}/journals"
            )

        assert response.status_code == 404
        assert response.json()["detail"] == "選挙情報が見つかりません"

    @pytest.mark.asyncio
    async def test_returns_400_when_multiple_candidates_without_politician_id(self):
        mock_supabase = MagicMock()

        def table_side_effect(name):
            if name == "elections":
                return _chainable_query({"id": str(ELECTION_ID)})
            if name == "public_ledgers":
                return _chainable_query(
                    [
                        {
                            "id": str(LEDGER_ID_1),
                            "politician_id": str(POLITICIAN_ID_1),
                        },
                        {
                            "id": str(LEDGER_ID_2),
                            "politician_id": str(POLITICIAN_ID_2),
                        },
                    ]
                )
            return MagicMock()

        mock_supabase.table.side_effect = table_side_effect

        test_app = _create_test_app(mock_supabase)
        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://testserver",
        ) as client:
            response = await client.get(
                f"/api/v1/polimoney/elections/{ELECTION_ID}/journals"
            )

        assert response.status_code == 400
        body = response.json()
        assert "error" in body
        assert len(body["candidates"]) == 2


class TestPolimoneyElectionCandidatesAPI:
    """候補者一覧APIのテスト"""

    @pytest.mark.asyncio
    async def test_returns_404_when_election_not_found(self):
        mock_supabase = MagicMock()
        mock_supabase.table.return_value = _chainable_query(None)

        test_app = _create_test_app(mock_supabase)
        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://testserver",
        ) as client:
            response = await client.get(
                f"/api/v1/polimoney/elections/{MISSING_ELECTION_ID}/candidates"
            )

        assert response.status_code == 404
        assert response.json()["detail"] == "選挙情報が見つかりません"

    @pytest.mark.asyncio
    async def test_aggregates_public_expense_total(self):
        mock_supabase = MagicMock()

        def table_side_effect(name):
            if name == "elections":
                return _chainable_query({"id": str(ELECTION_ID)})
            if name == "public_ledgers":
                return _chainable_query(
                    [
                        {
                            "id": str(LEDGER_ID_1),
                            "politician_id": str(POLITICIAN_ID_1),
                            "total_income": 1000,
                            "total_expense": 400,
                            "journal_count": 2,
                            "politicians": {
                                "id": str(POLITICIAN_ID_1),
                                "name": "候補者A",
                                "name_kana": "コウホシャエー",
                            },
                        }
                    ]
                )
            if name == "public_journals":
                return _chainable_query(
                    [
                        {
                            "ledger_id": str(LEDGER_ID_1),
                            "public_expense_amount": 100,
                        },
                        {
                            "ledger_id": str(LEDGER_ID_1),
                            "public_expense_amount": 0,
                        },
                        {
                            "ledger_id": str(LEDGER_ID_1),
                            "public_expense_amount": 50,
                        },
                    ]
                )
            return MagicMock()

        mock_supabase.table.side_effect = table_side_effect

        test_app = _create_test_app(mock_supabase)
        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://testserver",
        ) as client:
            response = await client.get(
                f"/api/v1/polimoney/elections/{ELECTION_ID}/candidates"
            )

        assert response.status_code == 200
        candidate = response.json()["data"][0]
        assert candidate["summary"]["public_expense_total"] == 150
        assert candidate["summary"]["balance"] == 600


class TestPolimoneyLedgerJournalsAPI:
    """台帳別仕訳APIのテスト"""

    @pytest.mark.asyncio
    async def test_returns_400_for_non_election_ledger(self):
        mock_supabase = MagicMock()
        mock_supabase.table.return_value = _chainable_query(
            {
                "id": str(NON_ELECTION_LEDGER_ID),
                "election_id": None,
                "politician_id": str(POLITICIAN_ID_1),
                "organization_id": str(uuid4()),
                "fiscal_year": 2024,
                "total_income": 0,
                "total_expense": 0,
                "journal_count": 0,
                "ledger_source_id": str(uuid4()),
                "last_updated_at": "2026-01-01",
                "first_synced_at": "2026-01-01",
                "created_at": "2026-01-01",
                "is_test": False,
            }
        )

        test_app = _create_test_app(mock_supabase)
        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://testserver",
        ) as client:
            response = await client.get(
                f"/api/v1/polimoney/ledgers/{NON_ELECTION_LEDGER_ID}/journals"
            )

        assert response.status_code == 400
        assert response.json()["detail"] == "選挙台帳以外は非対応です"

    @pytest.mark.asyncio
    async def test_returns_404_when_ledger_not_found(self):
        mock_supabase = MagicMock()
        mock_supabase.table.return_value = _chainable_query(None)

        test_app = _create_test_app(mock_supabase)
        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://testserver",
        ) as client:
            response = await client.get(f"/api/v1/polimoney/ledgers/{uuid4()}/journals")

        assert response.status_code == 404
        assert response.json()["detail"] == "台帳が見つかりません"


class TestPolimoneyPoliticiansAPI:
    """政治家一覧APIのテスト"""

    def test_returns_politicians_with_party_and_district(self):
        """政治家一覧が政党名・選挙区名を含んで正しく返されることを検証する"""
        mock_supabase = MagicMock()
        call_count = {"value": 0}

        def table_side_effect(name):
            if name == "public_ledgers":
                call_count["value"] += 1
                if call_count["value"] == 1:
                    # 選挙台帳
                    return _chainable_query(
                        [
                            {
                                "id": str(LEDGER_ID_1),
                                "politician_elections": {
                                    "politician_id": str(POLITICIAN_ID_1),
                                    "elections": {
                                        "election_date": "2026-01-01",
                                        "district": {"name": "東京都第1区"},
                                    },
                                },
                            },
                        ]
                    )
                else:
                    # 政治資金台帳
                    return _chainable_query([])
            if name == "politicians":
                return _chainable_query(
                    [
                        {
                            "id": str(POLITICIAN_ID_1),
                            "name": "テスト太郎",
                            "name_kana": "テストタロウ",
                            "title": "AIエンジニア",
                            "image_url": "https://example.com/photo.jpg",
                        },
                    ]
                )
            if name == "politician_organizations":
                return _chainable_query(
                    [
                        {
                            "politician_id": str(POLITICIAN_ID_1),
                            "organizations": {
                                "name": "未来創造党",
                                "type": "political_party",
                            },
                        },
                    ]
                )
            return MagicMock()

        mock_supabase.table.side_effect = table_side_effect

        client = TestClient(_create_test_app(mock_supabase))
        response = client.get("/api/v1/polimoney/politicians")

        assert response.status_code == 200
        body = response.json()
        assert body["total_count"] == 1
        assert body["api_version"] == "v1"

        politician = body["data"][0]
        assert politician["name"] == "テスト太郎"
        assert politician["name_kana"] == "テストタロウ"
        assert politician["title"] == "AIエンジニア"
        assert politician["image_url"] == "https://example.com/photo.jpg"
        assert politician["party"] == "未来創造党"
        assert politician["district"] == "東京都第1区"
        assert politician["ledger_count"] == 1

    def test_returns_empty_list_when_no_public_data(self):
        """公開データが存在しない場合に空配列が返されることを検証する"""
        mock_supabase = MagicMock()
        mock_supabase.table.return_value = _chainable_query([])

        client = TestClient(_create_test_app(mock_supabase))
        response = client.get("/api/v1/polimoney/politicians")

        assert response.status_code == 200
        body = response.json()
        assert body["total_count"] == 0
        assert body["data"] == []

    def test_aggregates_ledger_count_from_both_types(self):
        """選挙台帳と政治資金台帳の合計台帳数が正しく集計されることを検証する"""
        mock_supabase = MagicMock()
        call_count = {"value": 0}

        def table_side_effect(name):
            if name == "public_ledgers":
                call_count["value"] += 1
                if call_count["value"] == 1:
                    # 選挙台帳
                    return _chainable_query(
                        [
                            {
                                "id": str(LEDGER_ID_1),
                                "politician_elections": {
                                    "politician_id": str(POLITICIAN_ID_1),
                                    "elections": {
                                        "election_date": "2026-01-01",
                                        "district": {"name": "東京都第1区"},
                                    },
                                },
                            },
                        ]
                    )
                else:
                    # 政治資金台帳（同じ政治家）
                    return _chainable_query(
                        [
                            {
                                "id": str(LEDGER_ID_2),
                                "politician_organizations": {
                                    "politician_id": str(POLITICIAN_ID_1),
                                },
                            },
                        ]
                    )
            if name == "politicians":
                return _chainable_query(
                    [
                        {
                            "id": str(POLITICIAN_ID_1),
                            "name": "テスト太郎",
                            "name_kana": None,
                            "title": None,
                            "image_url": None,
                        },
                    ]
                )
            if name == "politician_organizations":
                return _chainable_query([])
            return MagicMock()

        mock_supabase.table.side_effect = table_side_effect

        client = TestClient(_create_test_app(mock_supabase))
        response = client.get("/api/v1/polimoney/politicians")

        assert response.status_code == 200
        body = response.json()
        assert body["total_count"] == 1
        assert body["data"][0]["ledger_count"] == 2

