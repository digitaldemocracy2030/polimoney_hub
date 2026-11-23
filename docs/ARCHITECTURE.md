# Polimoney Hub アーキテクチャ設計

## 概要

Polimoney Hub は、Polimoney エコシステムのデータハブとして、以下の役割を担います：

1. **共通識別子の管理** - 政治家・政治団体・選挙の ID を一元管理
2. **データ連携の仲介** - Ledger と Polimoney 間のデータフローを制御
3. **匿名化処理** - プライバシー設定に基づくデータ変換
4. **キャッシュ** - 高頻度アクセスの最適化

---

## システムアーキテクチャ

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Polimoney Hub                                    │
│                                                                          │
│  ┌──────────────────────────┐    ┌──────────────────────────────────┐  │
│  │    API Server (Hono)     │    │      Admin UI (Fresh)            │  │
│  │                          │    │                                  │  │
│  │  /api/v1/* - 公開 API    │    │  /login    - ログイン            │  │
│  │  /api/auth/* - 認証 API  │    │  /         - ダッシュボード      │  │
│  │  /api/admin/* - 管理 API │    │  /users    - ユーザー管理        │  │
│  └────────────┬─────────────┘    │  /election-requests - 承認       │  │
│               │                  └──────────────┬───────────────────┘  │
│               │                                 │                       │
│               └─────────────┬───────────────────┘                       │
│                             ▼                                           │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │              Supabase クライアント (@supabase/supabase-js)        │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└───────────────────────────────────────┬─────────────────────────────────┘
                                        │
                                        ▼
                   ┌─────────────────────────────────────────┐
                   │ Supabase                                │
                   │                                         │
                   │ [Supabase Auth]                         │
                   │ - 管理者認証（Email + Password）        │
                   │ - Magic Link 招待                       │
                   │                                         │
                   │ [PostgreSQL]                            │
                   │ - politicians, organizations, elections │
                   │ - public_ledgers, public_journals       │
                   │ - admin_users (管理者)                  │
                   └─────────────────────────────────────────┘
```

---

## Polimoney エコシステム全体図

> ⚠️ **重要**: Ledger と Hub は **別々の Supabase プロジェクト** を使用しています。
> 混同しないように注意してください。

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              DD2030 SaaS                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐│
│  │                        Polimoney Hub                                    ││
│  │  - 共通識別子管理 (政治家/政治団体/選挙)                                ││
│  │  - データ連携・匿名化                                                   ││
│  │  - 管理画面 (Fresh)                                                     ││
│  │                                                                          ││
│  │  ┌────────────────────────────────────────────────────────────────┐    ││
│  │  │ 🅱️ Supabase Project B (Hub 専用)                               │    ││
│  │  │    - PostgreSQL: politicians, organizations, elections         │    ││
│  │  │    - PostgreSQL: public_ledgers, public_journals, admin_users  │    ││
│  │  │    - Supabase Auth: 管理者認証                                 │    ││
│  │  └────────────────────────────────────────────────────────────────┘    ││
│  └────────────────────────────────────────────────────────────────────────┘│
│                              │                                              │
│                              │ API (X-API-Key)                              │
│          ┌───────────────────┴───────────────────┐                         │
│          │                                       │                         │
│          ▼                                       ▼                         │
│  ┌────────────────────────────────┐      ┌───────────────┐                │
│  │ Polimoney Ledger               │      │ Polimoney     │                │
│  │ (政治家向け収支管理)           │      │ (可視化)      │                │
│  │                                │      │               │                │
│  │  ┌──────────────────────────┐  │      │ ┌───────────┐ │                │
│  │  │ 🅰️ Supabase Project A     │  │      │ │ Next.js   │ │                │
│  │  │    (Ledger 専用)          │  │      │ │ - 収支表示│ │                │
│  │  │    - PostgreSQL: journals │  │      │ │ - 比較    │ │                │
│  │  │    - PostgreSQL: contacts │  │      │ │ - 分析    │ │                │
│  │  │    - Supabase Auth: OTP   │  │      │ └───────────┘ │                │
│  │  │    - Supabase Storage     │  │      │               │                │
│  │  └──────────────────────────┘  │      └───────────────┘                │
│  └────────────────────────────────┘                                        │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐│
│  │                      将来の消費者                                       ││
│  │  - 市民向けアプリ                                                       ││
│  │  - 研究者向け API                                                       ││
│  │  - メディア向けダッシュボード                                           ││
│  └────────────────────────────────────────────────────────────────────────┘│
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Supabase プロジェクトの分離

| プロジェクト               | 用途                           | 環境変数プレフィックス       |
| -------------------------- | ------------------------------ | ---------------------------- |
| **🅰️ Supabase A (Ledger)** | 政治家のプライベートデータ     | `SUPABASE_` (Ledger の .env) |
| **🅱️ Supabase B (Hub)**    | 共通識別子・公開データ・管理者 | `SUPABASE_` (Hub の .env)    |

**なぜ分離するか:**

- Ledger: 政治家の個人情報・領収書など機密データを扱う
- Hub: 公開データ・共通識別子を扱う（セキュリティ境界を分ける）

### 共通識別子の管理方針（重要）

> ⚠️ **Hub は共通識別子の唯一の情報源 (Single Source of Truth) です。**
>
> Ledger や Polimoney は共通識別子をローカルに保存 **しません**。
> 必要なときに Hub API から取得し、キャッシュで性能を担保します。

```
┌─────────────────────────────────────────────────────────────────────┐
│                    🅱️ Hub (Supabase B)                              │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │ 共通識別子（Single Source of Truth）                          │ │
│  │ - politicians (政治家)                                        │ │
│  │ - organizations (政治団体)                                    │ │
│  │ - elections (選挙)                                            │ │
│  │ ※ Ledger/Polimoney はここからのみ取得                        │ │
│  └───────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────┬───────────────────────────────────┘
                                  │
                    Hub API (認証: X-API-Key)
                                  │
        ┌─────────────────────────┼─────────────────────────┐
        │                         │                         │
        ▼                         ▼                         ▼
┌───────────────┐         ┌───────────────┐         ┌───────────────┐
│ Ledger        │         │ Polimoney     │         │ 将来の消費者  │
│ (キャッシュ)  │         │ (可視化)      │         │               │
└───────┬───────┘         └───────────────┘         └───────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────────┐
│                    🅰️ Ledger (Supabase A)                         │
│  - journals に election_id, organization_id を UUID で参照       │
│  - elections/organizations/politicians テーブルは存在しない      │
└───────────────────────────────────────────────────────────────────┘
```

**この方針の理由:**

| 理由         | 説明                                             |
| ------------ | ------------------------------------------------ |
| データ整合性 | 二重管理による不整合を防止                       |
| シンプルさ   | 同期ロジックが不要                               |
| 可用性       | Hub がダウン = 3 プロダクト全体がダウン（許容）  |
| 性能         | キャッシュで十分（共通識別子は頻繁に変わらない） |

---

## データフロー

### 1. 新規登録フロー（政治家 ID 発行）

```
ユーザー → Ledger → Hub API → 🅱️ Supabase B (Hub)
                                    │
                                    └→ 政治家 ID (UUID) を発行・保存
                                    │
              ←─────────────────────┘
              政治家 ID を Ledger に返却
              （Ledger は 🅰️ Supabase A に保存）
```

### 2. 仕訳データ連携（Ledger → Hub 同期）

```
🅰️ Supabase A (Ledger DB)
     │ journals, contacts, etc.
     │
     ▼
Polimoney Ledger
     │ 仕訳を公開する際に Hub API を呼び出し
     │ POST /api/v1/sync (API Key 認証)
     ▼
Polimoney Hub
     │ 匿名化処理 (is_name_private 等)
     │ ハッシュ生成（改ざん検知用）
     ▼
🅱️ Supabase B (Hub DB)
     │ public_ledgers, public_journals
     ▼
Polimoney (可視化) / 他の消費者
```

### 3. サービス間の認証

| 通信経路               | 認証方式             | 説明                                    |
| ---------------------- | -------------------- | --------------------------------------- |
| Ledger → Hub API       | `X-API-Key` ヘッダー | 環境変数 `LEDGER_SYNC_API_KEY_PROD` / `LEDGER_SYNC_API_KEY_DEV`。一般公開用キーができるまで `/api/v1/*` はすべてこのキーが必要（`/health` のみ不要） |
| Hub Admin UI → Hub API | Bearer Token (JWT)   | 🅱️ Supabase B の Auth で発行            |
| Ledger UI → Ledger API | Bearer Token (JWT)   | 🅰️ Supabase A の Auth で発行            |

### 3. データ取得フロー

```
Polimoney (可視化)
     │
     │ GET /api/v1/journals (予定)
     ▼
Polimoney Hub
     │
     └─→ Hub Supabase: 政治家名・選挙情報・公開仕訳データを取得
```

---

## 技術スタック

| レイヤー           | 技術                  | 理由                                   |
| ------------------ | --------------------- | -------------------------------------- |
| ランタイム         | Deno                  | TypeScript ネイティブ、セキュア        |
| API フレームワーク | Hono                  | 軽量、Edge 最適化                      |
| 管理画面           | Fresh                 | Deno ネイティブ、SSR                   |
| DB クライアント    | @supabase/supabase-js | 認証統合、RLS 対応                     |
| ホスティング       | Deno Deploy           | グローバルエッジ、コールドスタート高速 |
| DB                 | Supabase (PostgreSQL) | 認証・RLS 統合、無料枠充実             |
| 認証               | Supabase Auth         | JWT、Magic Link、パスワード認証        |

---

## 認証・認可

### サービス間認証（API）

| 通信            | 認証方式                               |
| --------------- | -------------------------------------- |
| Ledger → Hub    | API Key (`X-API-Key` ヘッダー)         |
| Polimoney → Hub | API Key（一般公開用キーは未実装。現状 `/api/v1/*` は Ledger 専用キーのみ） |
| Hub → Supabase  | Service Role Key（サーバーサイドのみ） |

### 管理画面認証（Supabase Auth）

| 機能           | 方式                                    |
| -------------- | --------------------------------------- |
| 管理者招待     | `inviteUserByEmail()` → Magic Link      |
| パスワード設定 | 招待リンクからパスワード設定画面へ      |
| 通常ログイン   | Email + Password (`signInWithPassword`) |
| パスワード忘れ | Magic Link (`resetPasswordForEmail`)    |

### 環境変数

```
# Supabase 接続
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_PUBLISHABLE_KEY=eyJhbGci...  # クライアント用
SUPABASE_SECRET_KEY=eyJhbGci...       # サーバー用（公開厳禁）

# API 認証キー（Ledger/Polimoney からのアクセス用）
LEDGER_SYNC_API_KEY_PROD=your-production-api-key
LEDGER_SYNC_API_KEY_DEV=your-development-api-key
```

---

## ディレクトリ構成

```
polimoney_hub/
├── src/                          # API サーバー (Hono)
│   ├── index.ts                  # エントリポイント
│   ├── routes/
│   │   ├── politicians.ts        # 政治家 API         ✅ 実装済
│   │   ├── organizations.ts      # 政治団体 API       ✅ 実装済
│   │   ├── elections.ts          # 選挙 API           ✅ 実装済
│   │   ├── auth.ts               # 認証 API           ✅ 実装済
│   │   ├── admin.ts              # 管理 API           ✅ 実装済
│   │   ├── sync.ts               # 同期 API           ✅ 実装済
│   │   └── ledgers.ts            # 公開台帳 API       ⏳ 予定
│   ├── db/
│   │   └── client.ts             # Supabase クライアント
│   ├── lib/
│   │   └── supabase.ts           # Supabase ヘルパー
│   └── middleware/
│       ├── auth.ts               # API Key 認証
│       └── admin-auth.ts         # 管理者認証
├── admin/                        # 管理画面 (Fresh)
│   ├── routes/
│   │   ├── index.tsx             # ダッシュボード     ✅ 実装済
│   │   ├── login.tsx             # ログイン           ⏳ 実装中
│   │   ├── users/                # ユーザー管理       ⏳ 予定
│   │   ├── election-requests/    # 選挙リクエスト     ✅ 実装済
│   │   └── organization-requests/# 団体リクエスト     ✅ 実装済
│   ├── components/
│   │   └── Layout.tsx            # 共通レイアウト
│   └── lib/
│       └── auth.ts               # 認証ヘルパー
├── db/
│   ├── schema-supabase.sql       # Supabase スキーマ
│   └── seed-supabase.ts          # シードデータ
├── docs/
│   ├── API.md                    # API 仕様
│   └── ARCHITECTURE.md           # 本ドキュメント
├── deno.json
└── README.md
```

---

## 公開データの永続化

### 設計方針

Polimoney がデータを取得する際、毎回 Ledger DB にクエリするのは非効率です。
そのため、Hub (Supabase) に**公開用データを永続保存**し、Ledger DB への負荷をゼロにします。

### データフロー

```
┌─────────────────┐
│ Ledger DB       │ ← 政治家のみアクセス（プライベート）
│ (Supabase)      │
└────────┬────────┘
         │ API 経由で同期
         ▼
┌─────────────────┐
│ Hub             │
│ - 匿名化        │
│ - ハッシュ生成  │
│ - 変更検知      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Hub Supabase    │ ← 公開データの永続保存
│ - public_ledgers│    Ledger DB への負荷ゼロ
│ - public_journals│
│ - change_logs   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Polimoney       │ ← Hub Supabase からのみ取得
└─────────────────┘
```

---

## 変更履歴と透明性

### 課題

政治家が過去の台帳をこっそり変更しても誰も気づけない → 不健全

### 解決策: ハッシュ + 台帳レベルの変更ログ

1. 仕訳登録時に**ハッシュ**を生成・保存（改ざん検知用）
2. **台帳レベル**で変更ログを保存（仕訳ごとだと多すぎる）
3. Polimoney で「最終更新日時」と「変更履歴」を表示

### スキーマ

```sql
-- 公開用台帳（1年分の収支報告）
CREATE TABLE public_ledgers (
    id UUID PRIMARY KEY,
    politician_id UUID NOT NULL REFERENCES politicians(id),
    election_id VARCHAR(50) REFERENCES elections(id),
    fiscal_year INTEGER NOT NULL,
    total_income INTEGER DEFAULT 0,
    total_expense INTEGER DEFAULT 0,
    journal_count INTEGER DEFAULT 0,
    last_updated_at TIMESTAMPTZ NOT NULL,
    first_synced_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 公開用仕訳
CREATE TABLE public_journals (
    id UUID PRIMARY KEY,
    ledger_id UUID NOT NULL REFERENCES public_ledgers(id),
    date DATE NOT NULL,
    description TEXT,
    amount INTEGER NOT NULL,
    contact_name TEXT,
    contact_type VARCHAR(20),
    content_hash VARCHAR(64) NOT NULL,
    synced_at TIMESTAMPTZ NOT NULL
);

-- 台帳レベルの変更ログ
CREATE TABLE ledger_change_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ledger_id UUID REFERENCES public_ledgers(id),
    changed_at TIMESTAMPTZ NOT NULL,
    change_summary TEXT  -- "仕訳3件を追加", "仕訳を修正" 等
);
```

### Polimoney での表示

```
┌─────────────────────────────────────────────────────────────┐
│ 山田太郎 - 2024年度 収支報告書                              │
│                                                              │
│ 最終更新: 2024/03/01 10:30  📋 変更履歴                     │
├─────────────────────────────────────────────────────────────┤
│  [収入ビュー] [支出ビュー] [科目別] [月別推移]              │
│  ...                                                         │
└─────────────────────────────────────────────────────────────┘
```

### 変更履歴ビュー（2 階層）

**Level 1: 変更一覧**

```
┌─────────────────────────────────────────────────────────────┐
│ 📋 変更履歴                                        ✕ 閉じる│
├─────────────────────────────────────────────────────────────┤
│  📅 2024/03/01 10:30  仕訳1件を修正           ▶ 詳細       │
│  📅 2024/02/25 14:15  仕訳2件を追加           ▶ 詳細       │
│  📅 2024/01/20 09:00  初回同期（15件）                      │
└─────────────────────────────────────────────────────────────┘
```

**Level 2: 変更詳細（日付クリック後）**

```
┌─────────────────────────────────────────────────────────────┐
│ 📋 変更履歴 > 2024/03/01 10:30                   ◀ 戻る    │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ✚ 追加された仕訳                                           │
│  ─────────────────────────────────────────────────────────  │
│  2024/02/20  事務所賃料      ¥80,000                        │
│  2024/02/15  交通費          ¥5,000                         │
│                                                              │
│  ✎ 修正された仕訳                                           │
│  ─────────────────────────────────────────────────────────  │
│  2024/01/15  ポスター印刷                                   │
│    • 金額: ¥50,000 → ¥30,000                               │
│    • 摘要: ポスター印刷 → チラシ印刷                       │
│                                                              │
│  🗑 削除された仕訳                                           │
│  ─────────────────────────────────────────────────────────  │
│  （なし）                                                    │
└─────────────────────────────────────────────────────────────┘
```

### change_details の形式

```json
{
  "added": [
    {
      "id": "uuid",
      "date": "2024-02-20",
      "description": "事務所賃料",
      "amount": 80000
    }
  ],
  "modified": [
    {
      "id": "uuid",
      "date": "2024-01-15",
      "description": "ポスター印刷",
      "changes": {
        "amount": { "before": 50000, "after": 30000 },
        "description": { "before": "ポスター印刷", "after": "チラシ印刷" }
      }
    }
  ],
  "deleted": [
    {
      "id": "uuid",
      "date": "2024-01-10",
      "description": "削除された仕訳",
      "amount": 10000
    }
  ]
}
```

### 差分保存フィールド

透明性のため、重要フィールドの差分（before/after）を保存：

| フィールド     | 保存 | 理由             |
| -------------- | ---- | ---------------- |
| `amount`       | ✅   | 金額変更は重要   |
| `description`  | ✅   | 摘要変更は重要   |
| `contact_name` | ✅   | 支出先変更は重要 |
| `date`         | ✅   | 日付変更は怪しい |
| `account_code` | ❌   | 科目変更は稀     |

---

## 今後の拡張

### Phase 1: 基盤構築 ✅

- [x] 政治家 / 政治団体 / 選挙 API
- [x] API Key 認証
- [x] Supabase 接続
- [x] Supabase Auth 統合

### Phase 2: 管理画面 🔄 進行中

- [x] ダッシュボード
- [x] 選挙リクエスト承認画面
- [x] 団体リクエスト承認画面
- [ ] ログイン画面
- [ ] ユーザー管理画面

### Phase 3: 公開データ永続化

- [x] public_ledgers / public_journals テーブル作成
- [x] ledger_change_logs テーブル作成
- [ ] ハッシュ生成ロジック実装

### Phase 4: Ledger 連携

- [x] 同期 API エンドポイント
- [ ] 匿名化処理ロジック
- [ ] Ledger ↔ Hub 自動同期

### Phase 5: Polimoney 連携

- [ ] 公開台帳 API (`/api/v1/public-ledgers`)
- [ ] 変更履歴 API (`/api/v1/ledgers/:id/changes`)
- [ ] 監査ログ

### Phase 6: 拡張

- [ ] 市民向けアプリ対応
- [ ] 研究者向け API
- [ ] OpenAPI / Swagger ドキュメント
