"""同期APIエンドポイント

Ledger から Hub への公開データ同期を受け付ける。
contacts → journals → ledger の順に同期する。
"""

from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, model_validator
from supabase import Client

from app.database.supabase import get_admin_supabase_client_dep

router = APIRouter()


def _utc_now() -> str:
    """現在の UTC タイムスタンプを ISO 8601 文字列で返す"""
    return datetime.now(timezone.utc).isoformat()


# ============================================
# Contacts 同期
# ============================================


class SyncContactInput(BaseModel):
    """Ledger から同期する関係者データ

    contact_source_id が Ledger 側の contacts.id に相当し、
    Hub 側の public_contacts.contact_source_id として保存される。
    これにより同一関係者のユニーク識別が可能になる。
    """

    contact_source_id: str  # Ledger contacts.id — ユニーク識別子
    ledger_id: str  # Hub public_ledgers.id
    contact_type: str
    name: Optional[str] = None
    address: Optional[str] = None
    occupation: Optional[str] = None
    is_name_private: bool = False
    is_address_private: bool = False
    is_occupation_private: bool = False
    privacy_reason_type: Optional[str] = None
    privacy_reason_other: Optional[str] = None
    hub_organization_id: Optional[str] = None


class SyncContactResult(BaseModel):
    """同期結果"""

    hub_contact_id: str  # Hub の public_contacts.id
    contact_source_id: str  # Ledger の contacts.id
    action: str  # "created" | "updated" | "skipped"


class SyncContactError(BaseModel):
    """同期エラー"""

    contact_source_id: str
    error: str


class SyncContactsResponse(BaseModel):
    """contacts 同期レスポンス"""

    data: list[SyncContactResult]
    errors: list[SyncContactError] = []


@router.post(
    "/sync/contacts",
    response_model=SyncContactsResponse,
)
async def sync_contacts(
    contacts: list[SyncContactInput],
    supabase: Client = Depends(get_admin_supabase_client_dep),
):
    """関係者データを Ledger から Hub に同期する

    contact_source_id（Ledger の contacts.id）をユニークキーとして
    upsert する。同姓同名でも UUID で区別される。

    Args:
        contacts: 同期する関係者データのリスト
        supabase: Supabaseクライアント（admin権限）

    Returns:
        SyncContactsResponse: 同期結果（Hub 側の contact_id を含む）
    """
    results: list[SyncContactResult] = []
    errors: list[SyncContactError] = []

    for contact in contacts:
        try:
            # contact_source_id で既存レコードを検索
            existing = (
                supabase.table("public_contacts")
                .select("id")
                .eq("contact_source_id", contact.contact_source_id)
                .maybe_single()
                .execute()
            )

            # 非公開フィールドは NULL にする
            name = None if contact.is_name_private else contact.name
            address = None if contact.is_address_private else contact.address
            occupation = (
                None if contact.is_occupation_private else contact.occupation
            )

            record = {
                "contact_source_id": contact.contact_source_id,
                "ledger_id": contact.ledger_id,
                "contact_type": contact.contact_type,
                "name": name,
                "address": address,
                "occupation": occupation,
                "is_name_private": contact.is_name_private,
                "is_address_private": contact.is_address_private,
                "is_occupation_private": contact.is_occupation_private,
                "privacy_reason_type": contact.privacy_reason_type,
                "privacy_reason_other": contact.privacy_reason_other,
                "hub_organization_id": contact.hub_organization_id,
                "synced_at": _utc_now(),
            }

            if existing and existing.data:
                # 更新
                hub_contact_id = existing.data["id"]
                supabase.table("public_contacts").update(record).eq(
                    "id", hub_contact_id
                ).execute()

                results.append(
                    SyncContactResult(
                        hub_contact_id=hub_contact_id,
                        contact_source_id=contact.contact_source_id,
                        action="updated",
                    )
                )
            else:
                # 新規作成
                insert_result = (
                    supabase.table("public_contacts")
                    .insert(record)
                    .select("id")
                    .single()
                    .execute()
                )

                results.append(
                    SyncContactResult(
                        hub_contact_id=insert_result.data["id"],
                        contact_source_id=contact.contact_source_id,
                        action="created",
                    )
                )

        except Exception as e:
            print(f"[Sync] Error syncing contact {contact.contact_source_id}: {e}")
            errors.append(
                SyncContactError(
                    contact_source_id=contact.contact_source_id,
                    error=str(e),
                )
            )
            continue

    return SyncContactsResponse(data=results, errors=errors)


# ============================================
# Journals 同期
# ============================================


class SyncJournalInput(BaseModel):
    """Ledger から同期する仕訳データ"""

    journal_source_id: str
    ledger_source_id: str
    date: Optional[str] = None
    description: Optional[str] = None
    amount: int
    contact_id: Optional[str] = None  # Hub の public_contacts.id
    account_code: str
    classification: Optional[str] = None
    non_monetary_basis: Optional[str] = None
    note: Optional[str] = None
    public_expense_amount: Optional[int] = None
    content_hash: str
    is_test: bool = False


class SyncJournalsRequest(BaseModel):
    """仕訳同期リクエスト"""

    journals: list[SyncJournalInput]


class SyncJournalResult(BaseModel):
    """仕訳同期結果"""

    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0


@router.post(
    "/sync/journals",
    response_model=dict,
)
async def sync_journals(
    request: SyncJournalsRequest,
    supabase: Client = Depends(get_admin_supabase_client_dep),
):
    """仕訳データを Ledger から Hub に同期する

    journal_source_id をキーとして upsert する。
    contact_id は Hub の public_contacts.id を指定する。

    Args:
        request: 同期する仕訳データ
        supabase: Supabaseクライアント（admin権限）

    Returns:
        dict: 同期結果
    """
    result = SyncJournalResult()

    for journal in request.journals:
        try:
            # 既存レコードを検索
            existing = (
                supabase.table("public_journals")
                .select("id, content_hash")
                .eq("journal_source_id", journal.journal_source_id)
                .maybe_single()
                .execute()
            )

            # ledger_source_id から Hub 側の public_ledgers.id を解決
            hub_ledger = (
                supabase.table("public_ledgers")
                .select("id")
                .eq("ledger_source_id", journal.ledger_source_id)
                .maybe_single()
                .execute()
            )
            if not hub_ledger or not hub_ledger.data:
                print(
                    f"[Sync] Hub ledger not found for source_id {journal.ledger_source_id}"
                )
                result.errors += 1
                continue

            hub_ledger_id = hub_ledger.data["id"]

            record = {
                "journal_source_id": journal.journal_source_id,
                "ledger_id": hub_ledger_id,
                "date": journal.date,
                "description": journal.description,
                "amount": journal.amount,
                "contact_id": journal.contact_id,
                "account_code": journal.account_code,
                "classification": journal.classification,
                "non_monetary_basis": journal.non_monetary_basis,
                "note": journal.note,
                "public_expense_amount": journal.public_expense_amount,
                "content_hash": journal.content_hash,
                "is_test": journal.is_test,
                "synced_at": _utc_now(),
            }

            if existing and existing.data:
                # ハッシュが同じならスキップ
                if existing.data.get("content_hash") == journal.content_hash:
                    result.skipped += 1
                    continue

                # 更新
                supabase.table("public_journals").update(record).eq(
                    "id", existing.data["id"]
                ).execute()
                result.updated += 1
            else:
                # 新規作成
                supabase.table("public_journals").insert(record).execute()
                result.created += 1

        except Exception as e:
            print(
                f"[Sync] Error syncing journal {journal.journal_source_id}: {e}"
            )
            result.errors += 1

    return {"data": result.model_dump()}


# ============================================
# Ledger 同期
# ============================================


class SyncLedgerInput(BaseModel):
    """Ledger から同期する台帳データ"""

    ledger_source_id: str
    ledger_type: Literal["political_fund", "election_fund"]
    politician_organization_id: Optional[str] = None
    politician_election_id: Optional[str] = None
    fiscal_year: int
    total_income: int
    total_expense: int
    journal_count: int
    is_test: bool = False

    @model_validator(mode="after")
    def validate_ledger_references(self) -> "SyncLedgerInput":
        if self.ledger_type == "political_fund" and not self.politician_organization_id:
            raise ValueError(
                "politician_organization_id は political_fund に必須です"
            )
        if self.ledger_type == "election_fund" and not self.politician_election_id:
            raise ValueError(
                "politician_election_id は election_fund に必須です"
            )
        return self


class SyncLedgerRequest(BaseModel):
    """台帳同期リクエスト"""

    ledger: SyncLedgerInput


@router.post(
    "/sync/ledger",
)
async def sync_ledger(
    request: SyncLedgerRequest,
    supabase: Client = Depends(get_admin_supabase_client_dep),
):
    """台帳データを Ledger から Hub に同期する

    ledger_source_id をキーとして upsert する。

    Args:
        request: 同期する台帳データ
        supabase: Supabaseクライアント（admin権限）

    Returns:
        dict: 同期結果
    """
    ledger = request.ledger

    # 既存レコードを検索
    existing = (
        supabase.table("public_ledgers")
        .select("id")
        .eq("ledger_source_id", ledger.ledger_source_id)
        .maybe_single()
        .execute()
    )

    record = {
        "ledger_source_id": ledger.ledger_source_id,
        "ledger_type": ledger.ledger_type,
        "politician_organization_id": ledger.politician_organization_id,
        "politician_election_id": ledger.politician_election_id,
        "fiscal_year": ledger.fiscal_year,
        "total_income": ledger.total_income,
        "total_expense": ledger.total_expense,
        "journal_count": ledger.journal_count,
        "is_test": ledger.is_test,
        "last_updated_at": _utc_now(),
    }

    if existing and existing.data:
        # 更新
        supabase.table("public_ledgers").update(record).eq(
            "id", existing.data["id"]
        ).execute()
        return {
            "data": {**record, "id": existing.data["id"]},
            "action": "updated",
        }
    else:
        # 新規作成
        record["first_synced_at"] = _utc_now()
        insert_result = (
            supabase.table("public_ledgers")
            .insert(record)
            .select("id")
            .single()
            .execute()
        )
        return {
            "data": {**record, "id": insert_result.data["id"]},
            "action": "created",
        }


# ============================================
# 同期ステータス
# ============================================


@router.get("/sync/status")
async def get_sync_status(
    supabase: Client = Depends(get_admin_supabase_client_dep),
):
    """同期ステータスを確認する"""
    try:
        ledgers_count = (
            supabase.table("public_ledgers")
            .select("id", count="exact")
            .execute()
        )
        journals_count = (
            supabase.table("public_journals")
            .select("id", count="exact")
            .execute()
        )
        contacts_count = (
            supabase.table("public_contacts")
            .select("id", count="exact")
            .execute()
        )

        return {
            "status": "ready",
            "message": "Hub sync is operational",
            "stats": {
                "public_ledgers": ledgers_count.count or 0,
                "public_journals": journals_count.count or 0,
                "public_contacts": contacts_count.count or 0,
            },
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
        }


# ============================================
# 変更ログ
# ============================================


class ChangeLogInput(BaseModel):
    """変更ログ"""

    ledger_source_id: str
    change_summary: str
    change_details: Optional[dict] = None


@router.post("/sync/change-log")
async def record_change_log(
    data: ChangeLogInput,
    supabase: Client = Depends(get_admin_supabase_client_dep),
):
    """変更ログを記録する"""
    try:
        supabase.table("ledger_change_logs").insert(
            {
                "ledger_source_id": data.ledger_source_id,
                "change_summary": data.change_summary,
                "change_details": data.change_details,
            }
        ).execute()
    except Exception as e:
        print(f"[Sync] Error recording change log: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"変更ログの記録に失敗しました: {e}",
        )

    return {"status": "ok"}
