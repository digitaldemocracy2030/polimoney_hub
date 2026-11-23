# Polimoney バックエンド

- 言語：Python 3.11+
- フレームワーク：FastAPI
- データベース：Supabase
- データアクセス：Supabase Pythonクライアント + Pydanticモデル（非ORM）
- コンテナ化：Docker & docker-compose

## セットアップ手順

### 前提条件

- Python 3.11+
- Supabase アカウント
- Docker & Docker Compose (オプション)

### 環境変数の設定

環境変数を設定してください：

```bash
cp .env.example .env
# .envファイルを編集してSupabaseの接続情報を設定
```

## Docker Composeで起動（推奨）

プロジェクトディレクトリで以下のコマンドを実行してください：

```bash
docker-compose up --build
```

これで以下のサービスが起動します：

- APIサーバー: `http://localhost:8000`
- 自動生成APIドキュメント: `http://localhost:8000/docs`

## 開発用（ローカル実行）

Docker Composeを使わずにローカルで実行する場合：

1. **Pythonのインストール**
   Python 3.13以上をインストールしてください。

2. **依存パッケージ・環境変数のインストール**

   ```bash
   uv pip install -r requirements.txt

   # mac, linux
   cp -i .env.example .env

   # windows
   Copy-Item .env.example .env

   ```

3. **サーバーの起動**

   ```bash
   python -m uvicorn app.main:app --reload
   ```

## 環境変数

以下の環境変数を`.env`ファイルに設定してください：

### データベース設定

Supabaseを使用しています。最低限、以下の環境変数を設定してください：

```bash
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_SECRET_KEY=your-service-role-key
SUPABASE_PUBLISHABLE_KEY=your-anon-key
```

### アプリケーション設定

```bash
ENV=development
DEBUG=true
HOST=0.0.0.0
PORT=8000
CORS_ORIGINS=["http://localhost:3000","http://localhost:8080"]
```

## APIドキュメント

FastAPIにより自動生成されるAPIドキュメント：

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- OpenAPI Schema: `http://localhost:8000/openapi.json`

## API エンドポイント

一般公開用の API キーの仕組みができるまで、`/api/v1/*` はすべて **Ledger 専用 API キー**（`X-API-Key` ヘッダー）が必要（`app/core/api_key.py`）。認証不要なのは `/health` だけ。

| 環境変数                   | 扱うデータ                              |
| -------------------------- | --------------------------------------- |
| `LEDGER_SYNC_API_KEY_PROD` | 本番データ（`is_test` が false / NULL） |
| `LEDGER_SYNC_API_KEY_DEV`  | テストデータ（`is_test = true`）        |

キーが無い・違う場合は 401、どちらのキーも未設定なら 503。DB は service_role（`SUPABASE_SECRET_KEY`）で読む（公開読み取りの RLS ポリシーは `db/migrate-restrict-public-read.sql` で削除する）。

| メソッド・パス                                      | 内容                                                                                        |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `GET /api/v1/political-funds/{ledger_id}`           | 政治資金収支報告書のデータ                                                                  |
| `GET /api/v1/election-funds/{ledger_id}`            | 選挙運動費用収支報告書のデータ                                                              |
| `GET /api/v1/polimoney/*`                           | Polimoney 向けの公開データ                                                                  |
| `GET /api/v1/master/account-codes[/{code}]`         | 勘定科目                                                                                    |
| `GET /api/v1/politicians?ledger_user_id=`           | Ledger ユーザーに紐づく政治家                                                               |
| `GET /api/v1/organizations`                         | 有効な政治団体（名前順）                                                                    |
| `GET /api/v1/organizations/managed?ledger_user_id=` | Ledger ユーザーが管理者の政治団体（`manager_verified_at` / `manager_verified_domain` 付き） |
| `GET /api/v1/organizations/{id}`                    | 政治団体 1 件                                                                               |
| `GET /api/v1/elections`                             | 有効な選挙（投票日の新しい順）                                                              |
| `POST /api/v1/politician-elections`                 | 政治家 ↔ 選挙の紐付けを取得・作成（本人確認済みの政治家本人のみ）                          |
| `POST /api/v1/politician-organizations/resolve`     | 政治団体の代表者の紐付けを引く（作成はしない）                                              |
| `POST /api/v1/sync/*`, `GET /api/v1/sync/status`    | Ledger → Hub の公開データ同期                                                               |

政治家・政治団体・選挙・政治団体管理者は、API キーに応じて本番データかテストデータのどちらかだけを扱う（`app/utils/test_scope.py`）。

## テスト実行

```bash
# 全テスト実行
pytest

# カバレッジレポート付き
pytest --cov=app --cov-report=html

# 特定のテスト実行
pytest tests/test_auth.py
```

## プロジェクト構造

```
backend/
├── app/
│   ├── main.py                 # FastAPIアプリケーション
│   ├── config.py               # 設定管理（Pydantic Settings）
│   ├── core/                   # 認証・セキュリティなどのコア機能
│   ├── database/
│   │   └── supabase.py         # Supabaseクライアント設定
│   ├── models/                 # Supabase行を表現するPydanticモデル
│   ├── schemas/                # APIレスポンス用Pydanticスキーマ
│   ├── routers/                # APIルーター
│   └── utils/                  # ユーティリティ
├── tests/                      # テスト
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── run.py
└── pytest.ini
```

## アーキテクチャ

このプロジェクトはFastAPIをベースとした**3層クリーンアーキテクチャ**を採用しています。各層が明確に分離されており、保守性とテスト容易性を確保しています。

### 全体構造

```
┌─────────────────┐
│   Presentation  │  ← APIルーター (HTTPリクエスト/レスポンス)
├─────────────────┤
│ Business Logic  │  ← サービス層 (ビジネスルール・認証)
├─────────────────┤
│ Data Access    │  ← リポジトリ層 (データ永続化)
└─────────────────┘
```

### 各層の詳細

#### 1. プレゼンテーション層 (Presentation Layer)
**場所**: `app/routers/`
**役割**: HTTPリクエストの処理とレスポンスの生成
- APIエンドポイントの定義 (`@router.get`, `@router.post` など)
- リクエストデータのバリデーションとレスポンスのシリアライズ
- HTTPステータスコードとエラーレスポンスの管理
- **主なファイル**: `auth.py`, `users.py`, `political_funds.py` など

#### 2. ビジネスロジック層 (Business Logic Layer)
**場所**: `app/core/`
**役割**: アプリケーションのビジネスルールとドメインlogic
- 認証・認可ロジック
- データのバリデーションと処理
- ビジネスルールの適用
- サービスクラスの実装
- **主なファイル**: `auth.py` (AuthService), `security.py`

#### 3. データアクセス層 (Data Access Layer)
**場所**: `app/database/`, `app/models/`
**役割**: Supabaseを介したデータの取得
- Supabase Pythonクライアントの設定
- Supabaseテーブル行を表現するPydanticモデル
- データ取得用のクエリ/関数
- **主なファイル**: `database/supabase.py`, `models/public_journals.py`, `models/public_ledgers.py`

### 補助層

#### スキーマ層 (Schema Layer)
**場所**: `app/schemas/`
**役割**: データ構造の定義とバリデーション
- Pydanticモデルによるリクエスト/レスポンス定義
- APIデータのシリアライズ/デシリアライズ
- 入力データのバリデーション

#### 依存関係層 (Dependencies Layer)
**場所**: `app/dependencies/`
**役割**: FastAPIの依存性注入管理
- データベースセッションの注入
- 認証済みユーザーの取得
- サービスインスタンスの生成

#### 設定層 (Configuration Layer)
**場所**: `app/config.py`
**役割**: アプリケーション設定の集中管理
- 環境変数の読み込み
- 設定値のバリデーション

### アーキテクチャの特徴

#### 依存性の逆転
- 上位層（プレゼンテーション層）は下位層（ビジネスロジック層）に依存
- 下位層はインターフェース（抽象）に依存することで、具体的な実装との疎結合を実現

#### 依存性注入 (DI)
FastAPIの強力な依存性注入システムを活用：
```python
# 依存関係の定義
def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> models.User:
    # トークン検証とユーザー取得
    # ...
```

#### 関心の分離
各層が独立した責任を持ち、変更が他の層に影響しにくい設計：
- **プレゼンテーション層**: HTTP通信のみ担当
- **ビジネスロジック層**: ビジネスルールのみ担当
- **データアクセス層**: データ永続化のみ担当

### 利点

1. **保守性**: 各層の責任が明確で変更の影響範囲が限定される
2. **テスト容易性**: 各層を独立してユニットテスト可能
3. **再利用性**: ビジネスロジックを複数のAPIで再利用可能
4. **拡張性**: 新機能の追加や既存機能の変更が容易

## 環境変数一覧

| 変数名 | 説明 | 必須 |
|--------|------|------|
| `SUPABASE_URL` | SupabaseプロジェクトURL | ○ |
| `ENV` | 実行環境 (development/production) | △ |
| `DEBUG` | デバッグモード | △ |
| `CORS_ORIGINS` | 許可するオリジンのリスト | △ |

## 開発コマンド

```bash
# 依存関係インストール
uv pip install -r requirements.txt

# マイグレーション作成
alembic revision --autogenerate -m "migration message"

# マイグレーション実行
alembic upgrade head

# サーバー起動
uvicorn app.main:app --reload

# テスト実行
pytest

# フォーマット
black .
isort .

# ドキュメントビルド
cd docs
make html
```
