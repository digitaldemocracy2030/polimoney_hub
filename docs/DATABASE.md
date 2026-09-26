# Polimoney Hub データベース設計書

## 概要

Polimoney Hub は、政治資金の透明性を実現するための **共通マスタデータベース**
です。
選挙、選挙区、政治家、政治団体などの識別子を一元管理し、Polimoney・Ledger
などの各サービスから参照されます。

### データベース

- **Supabase (PostgreSQL)**
- RLS (Row Level Security) 有効
- 接続情報は運営から共有

---

## テーブル一覧

| テーブル名                           | 説明                                    | 件数目安    |
| ------------------------------------ | --------------------------------------- | ----------- |
| `municipalities`                     | 市区町村マスタ                          | 約 1,800 件 |
| `districts`                          | 選挙区マスタ                            | 約 4,000 件 |
| `politicians`                        | 政治家マスタ                            | 随時追加    |
| `organizations`                      | 政治団体マスタ                          | 随時追加    |
| `elections`                          | 選挙マスタ                              | 随時追加    |
| `election_types`                     | 選挙タイプマスタ                        | 6 件        |
| `account_codes`                      | 勘定科目マスタ                          | 約 50 件    |
| `public_subsidy_items`               | 公費負担項目マスタ                      | 約 20 件    |
| `master_metadata`                    | マスタ更新日時                          | 8 件        |
| `public_ledgers`                     | 公開台帳（Ledger から同期）             | -           |
| `public_journals`                    | 公開仕訳（Ledger から同期）             | -           |
| `ledger_change_logs`                 | 台帳変更ログ                            | -           |
| `election_requests`                  | 選挙登録リクエスト                      | -           |
| `organization_requests`              | 政治団体登録リクエスト                  | -           |
| `unlock_requests`                    | ロック解除リクエスト                    | -           |
| `admin_users`                        | 管理者ユーザー                          | -           |
| `politician_verifications`           | **【v2 追加】政治家認証申請**           | -           |
| `organization_manager_verifications` | **【v2 追加】政治団体管理者認証申請**   | -           |
| `organization_managers`              | **【v2 追加】政治団体管理者マッピング** | -           |
| `impersonation_reports`              | **【v2 追加】なりすまし通報**           | -           |
| `politician_organizations`           | **【v2 追加】政治家-団体リンク**        | -           |
| `politician_elections`               | **【v2 追加】政治家-選挙リンク**        | -           |
| `public_contacts`                    | **【v2 追加】公開関係者**               | -           |

---

## ER 図

```
┌─────────────────┐
│  municipalities │ ← 市区町村マスタ（約1,800件）
│  code (PK)      │
└────────┬────────┘
         │
         │ (municipality_code)
         ▼
┌─────────────────┐       ┌─────────────────┐
│    districts    │       │   politicians   │
│    id (PK)      │       │    id (PK)      │
└────────┬────────┘       └────────┬────────┘
         │                         │
         │ (district_id)           │ (politician_id)
         ▼                         ▼
┌─────────────────┐       ┌─────────────────┐
│    elections    │       │  organizations  │
│    id (PK)      │       │    id (PK)      │
└────────┬────────┘       └────────┬────────┘
         │                         │
         └──────────┬──────────────┘
                    │
                    ▼
          ┌─────────────────┐
          │  public_ledgers │ ← Ledger から同期
          │    id (PK)      │
          └────────┬────────┘
                   │
                   ▼
          ┌─────────────────┐
          │ public_journals │
          │    id (PK)      │
          └─────────────────┘

┌─────────────────┐       ┌─────────────────────┐
│  election_types │←──────│  public_subsidy_items│
│  code (PK)      │       │  id (PK)            │
└─────────────────┘       └──────────┬──────────┘
                                     │
                          ┌──────────┴──────────┐
                          │    account_codes    │
                          │    code (PK)        │
                          └─────────────────────┘
```

---

## テーブル詳細

### municipalities（市区町村マスタ）

地方選挙（知事選、市長選、議会選）の選挙区として使用。
データソース:
[city_code.csv](https://github.com/digitaldemocracy2030/polimoney/blob/main/city_code.csv)

| カラム                 | 型                      | 説明                          |
| ---------------------- | ----------------------- | ----------------------------- |
| `code`                 | VARCHAR(6) PK           | 団体コード（総務省コード）    |
| `prefecture_name`      | VARCHAR                 | 都道府県名                    |
| `city_name`            | VARCHAR                 | 市区町村名（NULL = 都道府県） |
| `prefecture_name_kana` | VARCHAR                 | 都道府県名（カナ）            |
| `city_name_kana`       | VARCHAR                 | 市区町村名（カナ）            |
| `is_active`            | BOOLEAN DEFAULT TRUE    | 有効フラグ                    |
| `created_at`           | TIMESTAMPTZ DEFAULT NOW | 作成日時                      |
| `updated_at`           | TIMESTAMPTZ DEFAULT NOW | 更新日時                      |

---

### districts（選挙区マスタ）

衆参の選挙区、および地方選挙の区域を管理。

| カラム              | 型                      | 説明                                 |
| ------------------- | ----------------------- | ------------------------------------ |
| `id`                | UUID PK                 | UUID（自動生成）                     |
| `name`              | VARCHAR                 | 選挙区名                             |
| `type`              | VARCHAR(10)             | 選挙タイプ（下記参照）               |
| `prefecture_codes`  | VARCHAR                 | 関連都道府県（衆参用、カンマ区切り） |
| `municipality_code` | VARCHAR(6) FK           | 市区町村コード（地方選挙用）         |
| `description`       | TEXT                    | 説明                                 |
| `is_active`         | BOOLEAN DEFAULT TRUE    | 有効フラグ                           |
| `created_at`        | TIMESTAMPTZ DEFAULT NOW | 作成日時                             |
| `updated_at`        | TIMESTAMPTZ DEFAULT NOW | 更新日時                             |

---

### election_types（選挙タイプマスタ）

| カラム          | 型                      | 説明             |
| --------------- | ----------------------- | ---------------- |
| `code`          | VARCHAR PK              | 選挙タイプコード |
| `name`          | VARCHAR                 | 選挙タイプ名     |
| `description`   | TEXT                    | 説明             |
| `display_order` | INTEGER                 | 表示順           |
| `is_active`     | BOOLEAN DEFAULT TRUE    | 有効フラグ       |
| `created_at`    | TIMESTAMPTZ DEFAULT NOW | 作成日時         |

**選挙タイプ一覧:**

| コード | 名前                 | 説明                                       |
| ------ | -------------------- | ------------------------------------------ |
| `HR`   | 衆議院議員選挙       | House of Representatives（小選挙区・比例） |
| `HC`   | 参議院議員選挙       | House of Councillors（選挙区・比例）       |
| `PG`   | 都道府県知事選挙     | Prefectural Governor                       |
| `PA`   | 都道府県議会議員選挙 | Prefectural Assembly                       |
| `CM`   | 市区町村長選挙       | City/Town/Village Mayor                    |
| `GM`   | 市区町村議会議員選挙 | General/Municipal Assembly                 |

---

### elections（選挙マスタ）

実際の選挙（日付あり）を管理。

| カラム          | 型                      | 説明             |
| --------------- | ----------------------- | ---------------- |
| `id`            | UUID PK                 | UUID（自動生成） |
| `name`          | VARCHAR                 | 選挙名           |
| `type`          | VARCHAR(10)             | 選挙タイプ       |
| `district_id`   | UUID FK                 | 選挙区 ID        |
| `election_date` | DATE                    | 選挙日           |
| `is_active`     | BOOLEAN DEFAULT TRUE    | 有効フラグ       |
| `created_at`    | TIMESTAMPTZ DEFAULT NOW | 作成日時         |
| `updated_at`    | TIMESTAMPTZ DEFAULT NOW | 更新日時         |

---

### politicians（政治家マスタ）【v2 更新】

| カラム            | 型                      | 説明                                          |
| ----------------- | ----------------------- | --------------------------------------------- |
| `id`              | UUID PK                 | UUID（自動生成）                              |
| `name`            | VARCHAR                 | 氏名                                          |
| `name_kana`       | VARCHAR                 | 氏名（カナ）                                  |
| `ledger_user_id`  | UUID                    | **【v2 追加】Ledger 側の認証済みユーザー ID** |
| `official_url`    | TEXT                    | **【v2 追加】公式サイト URL**                 |
| `party`           | TEXT                    | **【v2 追加】所属政党（または無所属）**       |
| `photo_url`       | TEXT                    | **【v2 追加】顔写真 URL**                     |
| `is_verified`     | BOOLEAN DEFAULT FALSE   | **【v2 追加】認証済みフラグ**                 |
| `verified_at`     | TIMESTAMPTZ             | **【v2 追加】認証日時**                       |
| `verified_domain` | TEXT                    | **【v2 追加】認証に使用した公式ドメイン**     |
| `created_at`      | TIMESTAMPTZ DEFAULT NOW | 作成日時                                      |
| `updated_at`      | TIMESTAMPTZ DEFAULT NOW | 更新日時                                      |

---

### organizations（政治団体マスタ）【v2 更新】

| カラム                   | 型                      | 説明                                      |
| ------------------------ | ----------------------- | ----------------------------------------- |
| `id`                     | UUID PK                 | UUID（自動生成）                          |
| `name`                   | VARCHAR                 | 団体名                                    |
| `type`                   | VARCHAR(50)             | 団体タイプ（下記参照）                    |
| `politician_id`          | UUID FK                 | 関連政治家 ID                             |
| `official_url`           | TEXT                    | 公式サイト URL                            |
| `registration_authority` | TEXT                    | 届出先選挙管理委員会                      |
| `established_date`       | DATE                    | **【v2.1 追加】届出年月日（設立届出日）** |
| `office_address`         | TEXT                    | **【v2.1 追加】主たる事務所の所在地**     |
| `representative_name`    | TEXT                    | **【v2.1 追加】代表者名**                 |
| `accountant_name`        | TEXT                    | **【v2.1 追加】会計責任者名**             |
| `contact_email`          | TEXT                    | **【v2.1 追加】問い合わせ先メール**       |
| `description`            | TEXT                    | **【v2.1 追加】活動概要**                 |
| `sns_x`                  | TEXT                    | **【v2.1 追加】X (Twitter) URL**          |
| `sns_instagram`          | TEXT                    | **【v2.1 追加】Instagram URL**            |
| `sns_facebook`           | TEXT                    | **【v2.1 追加】Facebook URL**             |
| `sns_tiktok`             | TEXT                    | **【v2.1 追加】TikTok URL**               |
| `is_verified`            | BOOLEAN DEFAULT FALSE   | **【v2.1 追加】認証済みフラグ**           |
| `verified_at`            | TIMESTAMPTZ             | **【v2.1 追加】認証日時**                 |
| `is_active`              | BOOLEAN DEFAULT TRUE    | 有効フラグ                                |
| `created_at`             | TIMESTAMPTZ DEFAULT NOW | 作成日時                                  |
| `updated_at`             | TIMESTAMPTZ DEFAULT NOW | 更新日時                                  |

**団体タイプ (`type`):**

| 値                | 説明             | 備考                    |
| ----------------- | ---------------- | ----------------------- |
| `political_party` | 政党             | 政党一覧 API で取得可能 |
| `support_group`   | 後援会           |                         |
| `fund_management` | 資金管理団体     |                         |
| `other`           | その他の政治団体 |                         |

> **注意:** 政党は `type = 'political_party'` の政治団体として管理されます。

---

### account_codes（勘定科目マスタ）

| カラム                       | 型                      | 説明                 |
| ---------------------------- | ----------------------- | -------------------- |
| `code`                       | VARCHAR PK              | 科目コード           |
| `name`                       | VARCHAR                 | 科目名               |
| `name_kana`                  | VARCHAR                 | 科目名（カナ）       |
| `type`                       | VARCHAR                 | 勘定タイプ           |
| `report_category`            | VARCHAR                 | 報告書上の分類       |
| `ledger_type`                | VARCHAR DEFAULT 'both'  | 使用可能な台帳タイプ |
| `is_public_subsidy_eligible` | BOOLEAN DEFAULT FALSE   | 公費負担対象フラグ   |
| `display_order`              | INTEGER                 | 表示順               |
| `polimoney_category`         | VARCHAR                 | Polimoney カテゴリ   |
| `parent_code`                | VARCHAR FK              | 親科目コード         |
| `description`                | TEXT                    | 説明                 |
| `is_active`                  | BOOLEAN DEFAULT TRUE    | 有効フラグ           |
| `created_at`                 | TIMESTAMPTZ DEFAULT NOW | 作成日時             |
| `updated_at`                 | TIMESTAMPTZ DEFAULT NOW | 更新日時             |

**勘定タイプ (`type`):**

| 値          | 説明     |
| ----------- | -------- |
| `asset`     | 資産     |
| `liability` | 負債     |
| `equity`    | 純資産   |
| `revenue`   | 収入     |
| `expense`   | 支出     |
| `subsidy`   | 公費負担 |

**台帳タイプ (`ledger_type`):**

| 値             | 説明           |
| -------------- | -------------- |
| `organization` | 政治団体用     |
| `election`     | 選挙運動用     |
| `both`         | 両方で使用可能 |

---

### public_subsidy_items（公費負担項目マスタ）

| カラム               | 型                      | 説明             |
| -------------------- | ----------------------- | ---------------- |
| `id`                 | UUID PK                 | UUID             |
| `election_type_code` | VARCHAR FK              | 選挙タイプコード |
| `account_code`       | VARCHAR FK              | 勘定科目コード   |
| `item_name`          | VARCHAR                 | 項目名           |
| `unit`               | VARCHAR                 | 単位             |
| `unit_price_limit`   | INTEGER                 | 単価上限         |
| `quantity_formula`   | TEXT                    | 数量計算式       |
| `max_quantity`       | INTEGER                 | 最大数量         |
| `total_limit`        | INTEGER                 | 合計上限         |
| `notes`              | TEXT                    | 備考             |
| `effective_from`     | DATE                    | 適用開始日       |
| `effective_until`    | DATE                    | 適用終了日       |
| `is_active`          | BOOLEAN DEFAULT TRUE    | 有効フラグ       |
| `created_at`         | TIMESTAMPTZ DEFAULT NOW | 作成日時         |
| `updated_at`         | TIMESTAMPTZ DEFAULT NOW | 更新日時         |

---

### master_metadata（マスタ更新日時）

各マスタの最終更新日時を記録。Polimoney での「最終更新」表示に使用。

| カラム            | 型                      | 説明         |
| ----------------- | ----------------------- | ------------ |
| `table_name`      | VARCHAR PK              | テーブル名   |
| `last_updated_at` | TIMESTAMPTZ DEFAULT NOW | 最終更新日時 |

---

## 公開データ（Ledger 同期用）

### public_ledgers（公開台帳）

Ledger から同期された公開用の収支報告書。

| カラム             | 型                      | 説明           |
| ------------------ | ----------------------- | -------------- |
| `id`               | UUID PK                 | UUID           |
| `politician_id`    | UUID FK                 | 政治家 ID      |
| `organization_id`  | UUID FK                 | 政治団体 ID    |
| `election_id`      | UUID FK                 | 選挙 ID        |
| `fiscal_year`      | INTEGER                 | 会計年度       |
| `total_income`     | INTEGER DEFAULT 0       | 収入合計       |
| `total_expense`    | INTEGER DEFAULT 0       | 支出合計       |
| `journal_count`    | INTEGER DEFAULT 0       | 仕訳件数       |
| `ledger_source_id` | UUID UNIQUE             | Ledger 側の ID |
| `last_updated_at`  | TIMESTAMPTZ             | 最終更新日時   |
| `first_synced_at`  | TIMESTAMPTZ             | 初回同期日時   |
| `created_at`       | TIMESTAMPTZ DEFAULT NOW | 作成日時       |
| `is_test`          | BOOLEAN DEFAULT FALSE   | テストフラグ   |

### public_journals（公開仕訳）

| カラム                  | 型                      | 説明                                            |
| ----------------------- | ----------------------- | ----------------------------------------------- |
| `id`                    | UUID PK                 | UUID                                            |
| `ledger_id`             | UUID FK                 | 台帳 ID                                         |
| `journal_source_id`     | UUID UNIQUE             | Ledger 側の ID                                  |
| `date`                  | DATE                    | 日付                                            |
| `description`           | TEXT                    | 摘要（Polimoney: `purpose`）                    |
| `amount`                | INTEGER                 | 金額（Polimoney: `price`）                      |
| `contact_name`          | TEXT                    | 相手先名（匿名化済み）                          |
| `contact_type`          | VARCHAR(20)             | 相手先種別                                      |
| `account_code`          | VARCHAR                 | 勘定科目コード（Polimoney: `category` 導出用）  |
| `classification`        | VARCHAR(20)             | 活動区分（選挙台帳のみ: campaign/pre-campaign） |
| `non_monetary_basis`    | TEXT                    | 金銭以外の寄附の見積根拠                        |
| `note`                  | TEXT                    | 備考                                            |
| `public_expense_amount` | INTEGER                 | 公費負担額（0 の場合は NULL）                   |
| `content_hash`          | VARCHAR(64)             | 改ざん検知用ハッシュ                            |
| `synced_at`             | TIMESTAMPTZ             | 同期日時                                        |
| `created_at`            | TIMESTAMPTZ DEFAULT NOW | 作成日時                                        |
| `is_test`               | BOOLEAN DEFAULT FALSE   | テストフラグ                                    |

**Polimoney JSON との対応:**

| Polimoney JSON          | Hub カラム                                                             |
| ----------------------- | ---------------------------------------------------------------------- |
| `data_id`               | `id`                                                                   |
| `date`                  | `date`                                                                 |
| `price`                 | `amount`                                                               |
| `category`              | `account_code` から API 層で導出                                       |
| `type`                  | `ledger_id` → `public_ledgers.election_id` + `classification` から導出 |
| `purpose`               | `description`                                                          |
| `non_monetary_basis`    | `non_monetary_basis`                                                   |
| `note`                  | `note`                                                                 |
| `public_expense_amount` | `public_expense_amount`（>0 のみ出力）                                 |

---

## 登録リクエスト

### election_requests（選挙登録リクエスト）

ユーザーからの選挙登録リクエスト。運営が承認/却下。

| カラム                       | 型                        | 説明                       |
| ---------------------------- | ------------------------- | -------------------------- |
| `id`                         | UUID PK                   | UUID                       |
| `name`                       | VARCHAR                   | 選挙名                     |
| `type`                       | VARCHAR(10)               | 選挙タイプ                 |
| `district_id`                | UUID FK                   | 選挙区 ID                  |
| `area_description`           | TEXT                      | 選挙区説明（未登録の場合） |
| `election_date`              | DATE                      | 選挙日                     |
| `requested_by_politician_id` | UUID FK                   | リクエスト者（政治家）     |
| `requested_by_email`         | VARCHAR                   | リクエスト者メール         |
| `evidence_url`               | TEXT                      | 証拠 URL                   |
| `notes`                      | TEXT                      | 備考                       |
| `status`                     | VARCHAR DEFAULT 'pending' | ステータス                 |
| `rejection_reason`           | TEXT                      | 却下理由                   |
| `approved_election_id`       | UUID FK                   | 承認後の選挙 ID            |
| `created_at`                 | TIMESTAMPTZ DEFAULT NOW   | 作成日時                   |
| `reviewed_at`                | TIMESTAMPTZ               | レビュー日時               |
| `reviewed_by`                | VARCHAR                   | レビュー者                 |

**ステータス (`status`):**

| 値           | 説明         |
| ------------ | ------------ |
| `pending`    | 審査待ち     |
| `approved`   | 承認済み     |
| `rejected`   | 却下         |
| `needs_info` | 追加情報必要 |

### organization_requests（政治団体登録リクエスト）

同様の構造。`evidence_type` で証明書類の種類を指定。

### unlock_requests（ロック解除リクエスト）

ロックされた台帳の一時解除リクエスト。

| カラム                 | 型                        | 説明               |
| ---------------------- | ------------------------- | ------------------ |
| `id`                   | UUID PK                   | UUID               |
| `ledger_id`            | UUID                      | 台帳 ID            |
| `ledger_type`          | VARCHAR                   | 台帳タイプ         |
| `fiscal_year`          | INTEGER                   | 会計年度           |
| `requested_by_user_id` | UUID                      | リクエスト者 ID    |
| `requested_by_email`   | VARCHAR                   | リクエスト者メール |
| `reason`               | TEXT                      | 理由               |
| `status`               | VARCHAR DEFAULT 'pending' | ステータス         |
| `approved_at`          | TIMESTAMPTZ               | 承認日時           |
| `approved_by`          | UUID                      | 承認者 ID          |
| `unlock_expires_at`    | TIMESTAMPTZ               | 解除期限           |
| `rejection_reason`     | TEXT                      | 却下理由           |
| `created_at`           | TIMESTAMPTZ DEFAULT NOW   | 作成日時           |
| `updated_at`           | TIMESTAMPTZ DEFAULT NOW   | 更新日時           |

---

## 管理者

### admin_users（管理者ユーザー）

| カラム       | 型                      | 説明              |
| ------------ | ----------------------- | ----------------- |
| `id`         | UUID PK FK              | Supabase Auth UID |
| `email`      | VARCHAR                 | メールアドレス    |
| `name`       | VARCHAR                 | 名前              |
| `role`       | VARCHAR DEFAULT 'admin' | 権限              |
| `is_active`  | BOOLEAN DEFAULT TRUE    | 有効フラグ        |
| `dev_mode`   | BOOLEAN DEFAULT FALSE   | 開発モードフラグ  |
| `created_at` | TIMESTAMPTZ DEFAULT NOW | 作成日時          |
| `updated_at` | TIMESTAMPTZ DEFAULT NOW | 更新日時          |

---

## アカウント認証【v2 追加】

### politician_verifications（政治家認証申請）

Ledger ユーザーからの政治家認証申請を管理。公式ドメインのメール認証を必須とする。

| カラム                       | 型                      | 説明                        |
| ---------------------------- | ----------------------- | --------------------------- |
| `id`                         | UUID PK                 | UUID（自動生成）            |
| `ledger_user_id`             | UUID NOT NULL           | 申請者の Ledger ユーザー ID |
| `politician_id`              | UUID FK                 | 認証対象の政治家 ID（任意） |
| `name`                       | TEXT NOT NULL           | 申請者の氏名                |
| `official_email`             | TEXT NOT NULL           | 公式メールアドレス          |
| `official_url`               | TEXT                    | 公式サイト URL              |
| `party`                      | TEXT                    | 所属政党（または無所属）    |
| `email_verified`             | BOOLEAN DEFAULT FALSE   | メール認証完了フラグ        |
| `email_verification_code`    | TEXT                    | メール認証コード            |
| `email_verification_sent_at` | TIMESTAMPTZ             | 認証コード送信日時          |
| `status`                     | TEXT DEFAULT 'pending'  | ステータス                  |
| `rejection_reason`           | TEXT                    | 却下理由                    |
| `reviewed_by`                | UUID                    | レビュー者 ID               |
| `reviewed_at`                | TIMESTAMPTZ             | レビュー日時                |
| `created_at`                 | TIMESTAMPTZ DEFAULT NOW | 作成日時                    |
| `updated_at`                 | TIMESTAMPTZ DEFAULT NOW | 更新日時                    |

**ステータス (`status`):**

| 値               | 説明                     |
| ---------------- | ------------------------ |
| `pending`        | 審査待ち                 |
| `email_sent`     | メール認証コード送信済み |
| `email_verified` | メール認証完了、審査待ち |
| `approved`       | 承認済み                 |
| `rejected`       | 却下                     |

---

### organization_manager_verifications（政治団体管理者認証申請）

Ledger ユーザーからの政治団体管理者認証申請を管理。

| カラム                       | 型                      | 説明                        |
| ---------------------------- | ----------------------- | --------------------------- |
| `id`                         | UUID PK                 | UUID（自動生成）            |
| `ledger_user_id`             | UUID NOT NULL           | 申請者の Ledger ユーザー ID |
| `organization_id`            | UUID FK                 | 認証対象の政治団体 ID       |
| `organization_name`          | TEXT NOT NULL           | 政治団体名（新規の場合）    |
| `official_email`             | TEXT NOT NULL           | 公式メールアドレス          |
| `role_in_organization`       | TEXT                    | 団体内の役割（代表者等）    |
| `email_verified`             | BOOLEAN DEFAULT FALSE   | メール認証完了フラグ        |
| `email_verification_code`    | TEXT                    | メール認証コード            |
| `email_verification_sent_at` | TIMESTAMPTZ             | 認証コード送信日時          |
| `status`                     | TEXT DEFAULT 'pending'  | ステータス                  |
| `rejection_reason`           | TEXT                    | 却下理由                    |
| `reviewed_by`                | UUID                    | レビュー者 ID               |
| `reviewed_at`                | TIMESTAMPTZ             | レビュー日時                |
| `created_at`                 | TIMESTAMPTZ DEFAULT NOW | 作成日時                    |
| `updated_at`                 | TIMESTAMPTZ DEFAULT NOW | 更新日時                    |

---

### organization_managers（政治団体管理者マッピング）

承認された政治団体管理者と政治団体の紐付けを管理。

| カラム            | 型                      | 説明                       |
| ----------------- | ----------------------- | -------------------------- |
| `id`              | UUID PK                 | UUID（自動生成）           |
| `ledger_user_id`  | UUID NOT NULL           | Ledger ユーザー ID         |
| `organization_id` | UUID FK NOT NULL        | 政治団体 ID                |
| `verified_at`     | TIMESTAMPTZ             | 認証日時                   |
| `verified_domain` | TEXT                    | 認証に使用した公式ドメイン |
| `created_at`      | TIMESTAMPTZ DEFAULT NOW | 作成日時                   |
| `updated_at`      | TIMESTAMPTZ DEFAULT NOW | 更新日時                   |

**ユニーク制約:** `(ledger_user_id, organization_id)`

---

### impersonation_reports（なりすまし通報）

公開ページからのなりすまし通報を管理。

| カラム                 | 型                      | 説明                                  |
| ---------------------- | ----------------------- | ------------------------------------- |
| `id`                   | UUID PK                 | UUID（自動生成）                      |
| `report_type`          | TEXT NOT NULL           | 通報種別（politician/organization）   |
| `target_id`            | UUID NOT NULL           | 対象の政治家/政治団体 ID              |
| `reporter_name`        | TEXT NOT NULL           | 通報者氏名                            |
| `reporter_email`       | TEXT NOT NULL           | 通報者メールアドレス                  |
| `reporter_phone`       | TEXT                    | 通報者電話番号                        |
| `reporter_address`     | TEXT                    | 通報者住所                            |
| `evidence_type`        | TEXT NOT NULL           | 証拠種別（id_card/badge/certificate） |
| `evidence_description` | TEXT                    | 証拠の説明                            |
| `evidence_file_url`    | TEXT                    | 証拠ファイル URL                      |
| `status`               | TEXT DEFAULT 'pending'  | ステータス                            |
| `resolution_notes`     | TEXT                    | 対応メモ                              |
| `reviewed_by`          | UUID                    | レビュー者 ID                         |
| `reviewed_at`          | TIMESTAMPTZ             | レビュー日時                          |
| `created_at`           | TIMESTAMPTZ DEFAULT NOW | 作成日時                              |
| `updated_at`           | TIMESTAMPTZ DEFAULT NOW | 更新日時                              |

**証拠種別 (`evidence_type`):**

| 値            | 説明                     |
| ------------- | ------------------------ |
| `id_card`     | 身分証明書               |
| `badge`       | 議員バッジ               |
| `certificate` | 当選証書・設立届出書など |

> **注意:** 名刺は証拠として受け付けない（偽造が容易なため）

---

## API との連携

### マスタ取得（認証必要）

```
GET /api/v1/municipalities          # 市区町村一覧
GET /api/v1/districts               # 選挙区一覧
GET /api/v1/elections               # 選挙一覧
GET /api/v1/politicians             # 政治家一覧
GET /api/v1/organizations           # 政治団体一覧
GET /api/v1/master/account-codes    # 勘定科目一覧
GET /api/v1/master/election-types   # 選挙タイプ一覧
```

### 公開データ取得（認証必要）

```
GET /api/v1/public/ledgers             # 公開台帳一覧
GET /api/v1/public/ledgers/:id         # 台帳詳細
GET /api/v1/public/journals/:ledgerId  # 仕訳一覧
```

### 公開 API（認証不要）【v2.1 更新】

認証不要で一般公開される API。政治家・政治団体の公開ページから利用。

#### 認証済み政治家

```
GET /api/public/politicians           # 認証済み政治家一覧
    ?party=<政党名>                   # 政党フィルター（将来廃止予定）
    ?search=<検索ワード>              # 名前検索
    ?limit=50&offset=0                # ページネーション

GET /api/public/politicians/:id       # 政治家詳細（関連団体・収支情報含む）
```

#### 政党

```
GET /api/public/parties               # 政党一覧（organizations から抽出）
```

> **注意:** 政党は `organizations` テーブルの `type = 'political_party'` として管理されます。

#### 認証済み政治団体

```
GET /api/public/organizations         # 認証済み政治団体一覧
    ?type=<団体タイプ>               # タイプフィルター
    ?search=<検索ワード>              # 名前検索
    ?politician_id=<政治家ID>         # 関連政治家フィルター
    ?limit=50&offset=0                # ページネーション

GET /api/public/organizations/types   # 団体タイプ一覧（認証済み団体のみ）

GET /api/public/organizations/:id     # 政治団体詳細（認証済みのみ）
```

**レスポンス例（政治団体詳細）:**

```json
{
  "data": {
    "id": "uuid",
    "name": "山田太郎後援会",
    "type": "support_group",
    "type_name": "後援会",
    "official_url": "https://example.com",
    "registration_authority": "東京都選挙管理委員会",
    "established_date": "2020-01-15",
    "office_address": "東京都千代田区",
    "representative_name": "山田太郎",
    "accountant_name": "佐藤次郎",
    "contact_email": "info@example.com",
    "description": "山田太郎の政治活動を支援する後援会です。",
    "sns_x": "https://x.com/example",
    "sns_instagram": "https://instagram.com/example",
    "sns_facebook": "https://facebook.com/example",
    "sns_tiktok": "https://tiktok.com/@example",
    "verified_at": "2024-12-20T10:00:00Z",
    "politician": { "id": "uuid", "name": "山田太郎" },
    "ledgers": [...]
  }
}
```

#### 統計情報

```
GET /api/public/stats                 # 公開統計
```

**レスポンス:**

```json
{
  "data": {
    "verified_politicians": 100,
    "verified_organizations": 250,
    "political_parties": 10,
    "public_ledgers": 500,
    "public_journals": 10000
  }
}
```

#### なりすまし通報（「私ではありません」機能）

```
GET  /api/public/impersonation-reports/evidence-types   # 証拠種別一覧
POST /api/public/impersonation-reports                  # 通報を作成
GET  /api/public/impersonation-reports/:id/status       # 通報ステータス確認
     ?email=<通報者メール>
```

**通報作成リクエスト例:**

```json
{
  "target_type": "politician",
  "target_politician_id": "uuid",
  "reporter_name": "山田太郎",
  "reporter_email": "taro.yamada@example.com",
  "reporter_phone": "090-1234-5678",
  "reporter_address": "東京都千代田区...",
  "evidence_type": "member_id",
  "evidence_file_url": "https://...",
  "evidence_file_name": "議員証.pdf",
  "additional_notes": "補足説明..."
}
```

**証拠種別 (`evidence_type`):**

| 値             | 説明                         |
| -------------- | ---------------------------- |
| `id_card`      | 身分証明書（運転免許証など） |
| `passport`     | パスポート                   |
| `member_badge` | 議員バッジ                   |
| `member_id`    | 議員証                       |
| `other`        | その他                       |

> **注意:** 名刺は偽造が容易なため、証拠として受け付けていません。

---

## 初期データ

### 市区町村マスタ

- ファイル: `db/seed-municipalities.ts`
- 件数: 約 1,800 件
- ソース:
  [city_code.csv](https://github.com/digitaldemocracy2030/polimoney/blob/main/city_code.csv)

### 勘定科目マスタ

- ファイル: `db/seed-account-codes.ts`
- 件数: 約 50 件
- 政治資金規正法・公職選挙法に準拠

### 選挙区マスタ

- ファイル: `db/seed-districts.ts`
- 衆院選 289 区、参院選 45 区、地方選挙区

---

## テストデータの管理

### 概要

開発・テスト用のダミーデータは **本番データベースに `is_test = true` フラグ付きで保存**
されます。これにより、テスト環境と本番環境で同じ Hub インスタンスを使用しながら、
データを明確に区別できます。

### テストデータフラグ (`is_test`)

以下のテーブルに `is_test` カラムが存在します：

| テーブル                | 説明                       |
| ----------------------- | -------------------------- |
| `politicians`           | テスト用政治家             |
| `organizations`         | テスト用政治団体           |
| `organization_managers` | テスト用管理者             |
| `elections`             | テスト用選挙               |
| `public_ledgers`        | テスト用台帳（同期データ） |
| `public_journals`       | テスト用仕訳（同期データ） |

### テストユーザー ID

Ledger 側のテストアカウントは以下の固定 UUID で識別されます：

```
TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
```

このユーザーに紐づくデータ（`ledger_user_id` が一致するもの）は、
すべてテストデータとして扱われます。

### テストデータの特徴

1. **本番環境と同一の Hub に保存** - DEV/PROD 環境の切り替えは不要
2. **`is_test = true` で識別** - クエリでフィルタリング可能
3. **Ledger 同期時に自動設定** - `syncJournals`/`syncLedger` API 呼び出し時に自動的にフラグが設定される

### API キーによるフィルタリング

Hub は API キーに基づいて `is_test` フィルタリングを行います：

| API キー       | `isTestMode` | 返却データ        |
| -------------- | ------------ | ----------------- |
| `API_KEY_PROD` | `false`      | `is_test = false` |
| `API_KEY_DEV`  | `true`       | `is_test = true`  |

```typescript
// Hub middleware/auth.ts
if (apiKey === apiKeyDev) {
  c.set("isTestMode", true); // テストデータを返す
} else if (apiKey === apiKeyProd) {
  c.set("isTestMode", false); // 本番データを返す
}
```

```sql
-- 各 API でのクエリ例
SELECT * FROM politicians
WHERE COALESCE(is_test, false) = $isTestMode;
```

### テストデータの初期化

テスト用ダミーデータは `db/seed-test-data.sql` で管理されます。
開発環境のセットアップ時に投入してください。

**投入済みテストデータ:**

| データ種別 | ID                                     | 名前                 |
| ---------- | -------------------------------------- | -------------------- |
| 政治家     | `11111111-1111-1111-1111-111111111111` | 山田 太郎            |
| 政治家     | `22222222-2222-2222-2222-222222222222` | 佐藤 花子            |
| 政治団体   | `aaaa1111-1111-1111-1111-111111111111` | 山田太郎後援会       |
| 政治団体   | `aaaa1111-2222-2222-2222-222222222222` | 山田太郎を応援する会 |

---

## 注意事項

1. **ID は UUID** - 全テーブルの主キーは UUID（`gen_random_uuid()`）
2. **is_active フラグ** - 削除ではなく非アクティブ化で対応
3. **RLS 有効** - Row Level Security でアクセス制御
4. **PostgreSQL 構文** - Supabase は PostgreSQL ベース
5. **テストデータ** - `is_test = true` のデータは開発・テスト用

---

## 開発環境

### ローカル開発

```bash
# Supabase CLI でローカル起動
supabase start

# マイグレーション適用
supabase db push

# シードデータ投入
deno run --allow-env --allow-net --allow-read db/seed-account-codes.ts
```

### 環境変数

**Hub 側の .env:**

```bash
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_PUBLISHABLE_KEY=eyJhbGci...
SUPABASE_SECRET_KEY=eyJhbGci...

# API 認証キー（Ledger/Polimoney からのアクセス用）
API_KEY_PROD=your-production-api-key
API_KEY_DEV=your-development-api-key
```

---

## politician_organizations（政治家-団体リンク）【v2 追加】

政治家と政治団体の関連を管理するテーブル。

| カラム名          | 型             | NULL | デフォルト         | 説明                                     |
| ----------------- | -------------- | ---- | ------------------ | ---------------------------------------- |
| `id`              | uuid           | NO   | gen_random_uuid()  | PK                                       |
| `politician_id`   | uuid           | NO   | -                  | FK → politicians.id                      |
| `organization_id` | uuid           | NO   | -                  | FK → organizations.id                    |
| `role`            | varchar        | YES  | 'representative'   | 役割（代表者、会計責任者等）             |
| `is_active`       | boolean        | YES  | true               | 現在有効か                               |
| `created_at`      | timestamptz    | YES  | now()              | 作成日時                                 |
| `updated_at`      | timestamptz    | YES  | now()              | 更新日時                                 |

---

## politician_elections（政治家-選挙リンク）【v2 追加】

政治家と選挙の関連を管理するテーブル。

| カラム名        | 型             | NULL | デフォルト         | 説明                                     |
| --------------- | -------------- | ---- | ------------------ | ---------------------------------------- |
| `id`            | uuid           | NO   | gen_random_uuid()  | PK                                       |
| `politician_id` | uuid           | NO   | -                  | FK → politicians.id                      |
| `election_id`   | uuid           | NO   | -                  | FK → elections.id                        |
| `created_at`    | timestamptz    | YES  | now()              | 作成日時                                 |

---

## public_contacts（公開関係者）【v2 追加】

Ledger から同期された関係者情報の公開版。プライバシー制御カラム付き。

| カラム名                 | 型             | NULL | デフォルト         | 説明                                     |
| ------------------------ | -------------- | ---- | ------------------ | ---------------------------------------- |
| `id`                     | uuid           | NO   | gen_random_uuid()  | PK                                       |
| `ledger_id`              | uuid           | NO   | -                  | FK → public_ledgers.id                   |
| `contact_source_id`      | uuid           | NO   | -                  | Ledger 側の contacts.id                  |
| `contact_type`           | varchar        | NO   | -                  | 関係者種別                               |
| `name`                   | text           | YES  | -                  | 氏名                                     |
| `address`                | text           | YES  | -                  | 住所                                     |
| `occupation`             | text           | YES  | -                  | 職業                                     |
| `is_name_private`        | boolean        | NO   | false              | 氏名非公開フラグ                         |
| `is_address_private`     | boolean        | NO   | false              | 住所非公開フラグ                         |
| `is_occupation_private`  | boolean        | NO   | false              | 職業非公開フラグ                         |
| `privacy_reason_type`    | varchar        | YES  | -                  | 非公開理由の種別                         |
| `privacy_reason_other`   | text           | YES  | -                  | 非公開理由（その他）                     |
| `hub_organization_id`    | uuid           | YES  | -                  | FK → organizations.id                    |
| `synced_at`              | timestamptz    | NO   | now()              | Ledger からの同期日時                    |
| `created_at`             | timestamptz    | YES  | now()              | 作成日時                                 |

---

## 問い合わせ

- Hub 管理画面: `http://localhost:3722`（開発環境）
- GitHub: [polimoney_hub](https://github.com/digitaldemocracy2030/polimoney_hub)
