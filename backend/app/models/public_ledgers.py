"""public_ledgersテーブル用のPydanticモデル

Supabaseのpublic_ledgersテーブルから取得したデータを
表現するためのPydanticモデル。
"""

from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class PublicLedger(BaseModel):
    """public_ledgersテーブルのレコードを表現するモデル

    Attributes:
        id: UUID（主キー）
        ledger_type: 台帳種別（'political_fund' | 'election_fund'）
        politician_organization_id: 政治家×政治団体の中間テーブルID
        politician_election_id: 政治家×選挙の中間テーブルID
        fiscal_year: 会計年度
        total_income: 収入合計
        total_expense: 支出合計
        journal_count: 仕訳件数
        ledger_source_id: Ledger側のID
        last_updated_at: 最終更新日時
        first_synced_at: 初回同期日時
        created_at: 作成日時
        is_test: テストフラグ
    """

    id: UUID
    ledger_type: str
    politician_organization_id: Optional[UUID] = None
    politician_election_id: Optional[UUID] = None
    fiscal_year: int
    total_income: int = 0
    total_expense: int = 0
    journal_count: int = 0
    ledger_source_id: UUID
    last_updated_at: str
    first_synced_at: str
    created_at: str
    is_test: bool = False

    class Config:
        """Pydantic設定"""

        from_attributes = True
