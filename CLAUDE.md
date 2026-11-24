# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 前提

- Polimoney Hub は政治家・政治団体・選挙・勘定科目マスタと、公開用の台帳データを持つ。Polimoney Ledger（別リポジトリ）と Polimoney（可視化）が使う。全体の構成は Polimoney リポジトリの `docs/ARCHITECTURE.md`。
- 現役の API は `backend/`（Python / FastAPI）。ルートの `README.md` と `deno.json` は旧 Deno + Hono 版の記述が残っている。`admin/` は Deno / Fresh の管理画面（Next.js + Mantine に移行予定）。
- サービス開始前なので、後方互換のための仕組みは残さない。

## コマンド

```bash
cd backend
python -m uvicorn app.main:app --reload --port 3722   # http://localhost:3722/docs
python -m pytest tests/test_verification_api.py -q    # 1 ファイル
python -m pytest tests -q --continue-on-collection-errors
```

- `tests/` には、main でも読み込みエラーになるファイルや失敗するテストがある。変更前後で結果を比べ、増えていないことを確かめる。
- `.env` は読まない・作らない・編集しない（値はユーザーが設定する）。

## デプロイと DB

- `main` に push すると GitHub Actions（`.github/workflows/deploy-backend.yml`）で Azure Container Apps に自動デプロイされる（本番 https://api.polimoney.dd2030.org）。**マージ = 本番反映**。
- DB は Supabase（Hub DB）。スキーマ変更は `db/*.sql` に書き、`supabase db query --linked -f db/<file>.sql` で適用する。**新しいコードが使う列・関数は、PR のマージ（= デプロイ）より前に適用する**。追加のみの変更（`IF NOT EXISTS` / `CREATE OR REPLACE`）にして、先に適用しても今のコードを壊さないようにする。
- DB の関数は、適用前に `BEGIN; ...; ROLLBACK;` のトランザクション内で動作を確かめる。

## 認証

| パス | 方式 |
| --- | --- |
| `/health` | 不要 |
| `/api/v1/*` | `X-API-Key`（Ledger 専用キー、`app/core/api_key.py`）。DEV キーはテストデータ（`is_test = true`）だけを扱い、`app/utils/test_scope.py` の `apply_test_scope` で絞り込む |
| `/api/admin/*` | `Authorization: Bearer <Hub の Supabase Auth のトークン>` + `admin_users`（`is_active`）。`app/core/admin_auth.py` |

- DB は service_role で読み書きする（RLS は効かない）。だから API 側で必ず、呼び出し元の範囲（本人の `ledger_user_id`、本番 / テストの範囲）に絞り込む。他人の行は 404 にする。
- エラーは `{"detail": "<日本語のメッセージ>"}`。

## 実装のルール（CodeRabbit で繰り返し指摘されたもの）

1. **同時に届いた要求で壊れないようにする。** 「読み取る → 判定する → 書き込む」の間に別の要求が割り込む前提で書く。
   - 状態を変える更新は、読み取ったときの値（`status`、回数、コードのハッシュなど）を更新条件に入れた比較更新にし、更新できなければ 409（または読み直して再試行）。
   - 回数などの加算は、読み取った値を条件にした比較更新で行い、上限の判定もその結果で行う（値を読んで `+1` を書くだけにしない）。
   - 「1 件まで」の制約は、事前の SELECT だけでなく DB の一意制約（部分一意インデックス）でも守り、一意制約違反（`23505`）は 409 にする。
2. **複数のテーブルへの書き込みは 1 つのトランザクションにする。** supabase-py には複数の操作をまたぐトランザクションが無いので、DB の関数（plpgsql）にして `supabase.rpc()` で呼ぶ。関数の中で対象の行を `FOR UPDATE` でロックしてから状態を確かめる。関数は `REVOKE ... FROM PUBLIC, anon, authenticated` して service_role だけに実行させる。
3. **同期 I/O をするエンドポイントは `def` にする。** supabase-py・`httpx.get` などは同期なので、`async def` の中で呼ぶとイベントループが止まる。`def` にして FastAPI のスレッドプールで実行させる。
4. **例外の扱い。** 想定外の例外は 500 にしてログに出す（メッセージに秘密情報を入れない）。`raise ... from e` で元の例外をつなぐ。
5. **テスト。** 簡易 DB（`tests/test_verification_api.py` の `FakeDB`）で、正常系に加えて「書き込みの直前に別の要求が行を変えた」場合（`before_write`）も確かめる。

## 文書

- 文書・コミットメッセージは日本語。コミットは `feat:` / `fix:` / `docs:` / `refactor:` / `chore:` 等 + 要約、空行、箇条書き（`.cursor/rules/commit.md`）。
- 文書には**今の状態**を書く。未マージ・未デプロイ・計画中のことは、「（計画）」「PR #xx のマージ後」のように今の状態と分けて書く。
- API を変えたら `backend/README.md` のエンドポイント一覧も直す。Ledger から使う API なら Ledger の `docs/HUB_API_GAP.md` も合わせる。
