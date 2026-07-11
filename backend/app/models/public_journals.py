"""public_journalsテーブル用のPydanticモデル

Supabaseのpublic_journalsテーブルから取得したデータを
表現するためのPydanticモデル。
"""

from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class PublicJournal(BaseModel):
    """public_journalsテーブルのレコードを表現するモデル

    Attributes:
        id: UUID（主キー）
        ledger_id: 台帳ID（public_ledgers.id）
        journal_source_id: Ledger側のID
        date: 日付
        description: 摘要（Polimoney: purpose）
        amount: 金額（Polimoney: price）
        contact_id: 関係者ID（public_contacts.id）
        account_code: 勘定科目コード
        classification: 活動区分（選挙台帳のみ: campaign/pre-campaign）
        non_monetary_basis: 金銭以外の寄附の見積根拠
        note: 備考
        public_expense_amount: 公費負担額（0の場合はNULL）
        content_hash: 改ざん検知用ハッシュ
        synced_at: 同期日時
        created_at: 作成日時
        is_test: テストフラグ
    """

    id: UUID
    ledger_id: UUID
    journal_source_id: UUID
    date: Optional[str] = None
    description: Optional[str] = None
    amount: int
    contact_id: Optional[UUID] = None
    account_code: Optional[str] = None
    classification: Optional[str] = None
    non_monetary_basis: Optional[str] = None
    note: Optional[str] = None
    public_expense_amount: Optional[int] = None
    content_hash: str
    synced_at: str
    created_at: str
    is_test: bool = False

    class Config:
        """Pydantic設定"""

        from_attributes = True
