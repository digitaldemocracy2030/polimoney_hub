"""マスタデータ API のスキーマ定義"""

from typing import Literal, Optional

from pydantic import BaseModel

# 勘定科目が使える台帳の種類（both = 政治団体・選挙の両方）
AccountLedgerType = Literal["both", "organization", "election"]

# 勘定科目の種類
AccountType = Literal["asset", "liability", "equity", "revenue", "expense", "subsidy"]


class AccountCode(BaseModel):
    """勘定科目"""

    code: str
    name: str
    name_kana: Optional[str] = None
    type: str
    report_category: str
    ledger_type: str
    is_public_subsidy_eligible: bool = False
    display_order: int
    polimoney_category: Optional[str] = None
    parent_code: Optional[str] = None
    description: Optional[str] = None


class AccountCodesResponse(BaseModel):
    """勘定科目一覧のレスポンス"""

    data: list[AccountCode]


class AccountCodeResponse(BaseModel):
    """勘定科目 1 件のレスポンス"""

    data: AccountCode
