-- 公開読み取り（"Allow public read"）ポリシーの削除
--
-- Hub のデータは Hub API（backend/）経由でだけ読ませる。API は service_role（Secret キー）で
-- DB を読み、/api/v1/* は Ledger 専用 API キーで保護する。一般公開用の API キーの仕組みが
-- できるまでは、Publishable（anon）キーでテーブルを直接読めないようにする。
--
-- 適用の順番:
--   1. Admin クライアント（get_admin_supabase_client_dep）を使うバックエンドを先にデプロイする
--      （古いバックエンドは Publishable キーで読んでいるため、先に適用すると空の結果になる）
--   2. その後にこの SQL を適用する:
--        supabase db query --linked -f db/migrate-restrict-public-read.sql
--
-- 残すもの:
--   - "Allow service write"（service_role の読み書き）
--   - admin_users の "Admin users can read own data"
--   - impersonation_reports のポリシー（匿名の INSERT は引き続き許可）
--
-- 確認方法（anon キーでの読み取りが空になること）:
--   curl -s "$SUPABASE_URL/rest/v1/politicians?select=id&limit=1" \
--     -H "apikey: $SUPABASE_PUBLISHABLE_KEY"
--   → [] が返ればよい（RLS により行が見えない）
--   ポリシーの一覧:
--   SELECT tablename, policyname FROM pg_policies
--   WHERE schemaname = 'public' AND policyname = 'Allow public read';
--   → 0 行

BEGIN;

DROP POLICY IF EXISTS "Allow public read" ON public.account_codes;
DROP POLICY IF EXISTS "Allow public read" ON public.districts;
DROP POLICY IF EXISTS "Allow public read" ON public.election_requests;
DROP POLICY IF EXISTS "Allow public read" ON public.election_types;
DROP POLICY IF EXISTS "Allow public read" ON public.elections;
DROP POLICY IF EXISTS "Allow public read" ON public.ledger_change_logs;
DROP POLICY IF EXISTS "Allow public read" ON public.master_metadata;
DROP POLICY IF EXISTS "Allow public read" ON public.municipalities;
DROP POLICY IF EXISTS "Allow public read" ON public.organization_requests;
DROP POLICY IF EXISTS "Allow public read" ON public.organizations;
DROP POLICY IF EXISTS "Allow public read" ON public.politician_elections;
DROP POLICY IF EXISTS "Allow public read" ON public.politician_organizations;
DROP POLICY IF EXISTS "Allow public read" ON public.politicians;
DROP POLICY IF EXISTS "Allow public read" ON public.public_contacts;
DROP POLICY IF EXISTS "Allow public read" ON public.public_journals;
DROP POLICY IF EXISTS "Allow public read" ON public.public_ledgers;
DROP POLICY IF EXISTS "Allow public read" ON public.public_subsidy_items;
DROP POLICY IF EXISTS "Allow public read" ON public.unlock_requests;

COMMIT;
