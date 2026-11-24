-- 本人確認の申請テーブルに is_test・確認コードの失敗回数・申請フォームの項目を追加する
--
-- - is_test: Ledger の DEV キー（テストデータ用）で作られた申請。承認時に作る政治家・団体・管理者も
--   この値に合わせ、本番データと混ざらないようにする
-- - verification_attempts: 確認コードの失敗回数。5 回間違えるとコードを無効にする（再送信でリセット）
-- - official_url（政治家）/ role_in_organization（政治団体の管理者）: Ledger の申請フォームで入力する項目。
--   official_url は承認時に政治家の公式サイトとして登録する
-- - verification_code には確認コードそのものではなく SHA-256 のハッシュを保存する（列の変更は無し）
--
-- 追加のみなので、バックエンドのデプロイ前に適用してよい（デプロイ前に適用すること。
-- 新しいバックエンドはこの列を読み書きする）:
--   supabase db query --linked -f db/migrate-verification-test-and-attempts.sql

BEGIN;

ALTER TABLE public.politician_verifications
  ADD COLUMN IF NOT EXISTS is_test boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS verification_attempts integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS official_url text;

ALTER TABLE public.organization_manager_verifications
  ADD COLUMN IF NOT EXISTS is_test boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS verification_attempts integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS role_in_organization text;

CREATE INDEX IF NOT EXISTS idx_politician_verifications_ledger_user
  ON public.politician_verifications (ledger_user_id);
CREATE INDEX IF NOT EXISTS idx_politician_verifications_status
  ON public.politician_verifications (status);
CREATE INDEX IF NOT EXISTS idx_org_manager_verifications_ledger_user
  ON public.organization_manager_verifications (ledger_user_id);
CREATE INDEX IF NOT EXISTS idx_org_manager_verifications_status
  ON public.organization_manager_verifications (status);

COMMIT;
