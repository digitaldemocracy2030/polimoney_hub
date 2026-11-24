-- 本人確認の申請テーブルに is_test・確認コードの失敗回数・申請フォームの項目を追加し、
-- 手続き中の申請の一意制約と、承認の DB 関数を作る
--
-- - is_test: Ledger の DEV キー（テストデータ用）で作られた申請。承認時に作る政治家・団体・管理者も
--   この値に合わせ、本番データと混ざらないようにする
-- - verification_attempts: 確認コードの失敗回数。5 回間違えるとコードを無効にする（再送信でリセット）
-- - official_url（政治家）/ role_in_organization（政治団体の管理者）: Ledger の申請フォームで入力する項目。
--   official_url は承認時に政治家の公式サイトとして登録する
-- - verification_code には確認コードそのものではなく SHA-256 のハッシュを保存する（列の変更は無し）
-- - 手続き中（pending / email_sent / email_verified / dns_verified）の申請は、政治家は 1 ユーザー 1 件、
--   政治団体の管理者は 1 ユーザー・1 団体につき 1 件まで（同時に申請されても 2 件目は作られない）
-- - approve_politician_verification / approve_organization_manager_verification:
--   承認を 1 つのトランザクションで行う（申請の行をロック → 状態の確認 → 政治家・団体・管理者の登録 →
--   申請を approved に）。service_role だけが実行できる
--
-- 追加のみなので、バックエンドのデプロイ前に適用してよい（デプロイ前に適用すること。
-- 新しいバックエンドはこの列と関数を使う）:
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

-- 手続き中の申請は 1 件まで
CREATE UNIQUE INDEX IF NOT EXISTS uq_politician_verifications_active
  ON public.politician_verifications (is_test, ledger_user_id)
  WHERE status IN ('pending', 'email_sent', 'email_verified', 'dns_verified');
CREATE UNIQUE INDEX IF NOT EXISTS uq_org_manager_verifications_active_org
  ON public.organization_manager_verifications (is_test, ledger_user_id, organization_id)
  WHERE status IN ('pending', 'email_sent', 'email_verified', 'dns_verified')
    AND organization_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_org_manager_verifications_active_name
  ON public.organization_manager_verifications (is_test, ledger_user_id, organization_name)
  WHERE status IN ('pending', 'email_sent', 'email_verified', 'dns_verified')
    AND organization_id IS NULL;

-- ============================================
-- 政治家の本人確認の承認
-- ============================================
CREATE OR REPLACE FUNCTION public.approve_politician_verification(
  p_verification_id uuid,
  p_reviewer_id uuid
) RETURNS public.politician_verifications
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
  v public.politician_verifications;
  v_politician_id uuid;
  v_now timestamptz := now();
BEGIN
  -- 申請の行をロックする（同時の却下・承認はロックが外れるまで待つ）
  SELECT * INTO v FROM public.politician_verifications
   WHERE id = p_verification_id
   FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'verification_not_found';
  END IF;
  IF v.status NOT IN ('email_verified', 'dns_verified') THEN
    RAISE EXCEPTION 'verification_not_confirmed';
  END IF;

  -- 申請者の政治家（申請と同じ本番 / テストの範囲）
  SELECT id INTO v_politician_id FROM public.politicians
   WHERE ledger_user_id = v.ledger_user_id
     AND CASE WHEN v.is_test THEN is_test IS TRUE ELSE is_test IS NOT TRUE END
   ORDER BY created_at
   LIMIT 1
   FOR UPDATE;

  IF v_politician_id IS NULL THEN
    INSERT INTO public.politicians (
      name, ledger_user_id, is_test, is_verified, verified_at, verified_domain,
      is_lg_verified, party, official_url, updated_at
    ) VALUES (
      v.politician_name, v.ledger_user_id, v.is_test, true, v_now, v.official_domain,
      v.is_lg_domain, NULLIF(v.party, ''), NULLIF(v.official_url, ''), v_now
    )
    RETURNING id INTO v_politician_id;
  ELSE
    UPDATE public.politicians SET
      is_verified = true,
      verified_at = v_now,
      verified_domain = v.official_domain,
      is_lg_verified = v.is_lg_domain,
      party = COALESCE(NULLIF(v.party, ''), party),
      -- ドメインが変わるときは、古いドメインの公式サイトの URL を外す
      official_url = CASE
        WHEN NULLIF(v.official_url, '') IS NOT NULL THEN v.official_url
        WHEN v.request_type = 'domain_change' THEN NULL
        ELSE official_url
      END,
      updated_at = v_now
    WHERE id = v_politician_id;
  END IF;

  UPDATE public.politician_verifications SET
    status = 'approved',
    approved_politician_id = v_politician_id,
    reviewed_by = p_reviewer_id,
    reviewed_at = v_now,
    updated_at = v_now
  WHERE id = v.id
  RETURNING * INTO v;

  RETURN v;
END;
$$;

-- ============================================
-- 政治団体の管理者の本人確認の承認
-- ============================================
CREATE OR REPLACE FUNCTION public.approve_organization_manager_verification(
  p_verification_id uuid,
  p_reviewer_id uuid
) RETURNS public.organization_manager_verifications
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
  v public.organization_manager_verifications;
  v_organization_id uuid;
  v_now timestamptz := now();
BEGIN
  SELECT * INTO v FROM public.organization_manager_verifications
   WHERE id = p_verification_id
   FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'verification_not_found';
  END IF;
  IF v.status NOT IN ('email_verified', 'dns_verified') THEN
    RAISE EXCEPTION 'verification_not_confirmed';
  END IF;

  v_organization_id := v.organization_id;
  IF v_organization_id IS NOT NULL THEN
    UPDATE public.organizations SET
      is_verified = true,
      verified_at = v_now,
      is_lg_verified = v.is_lg_domain,
      official_url = CASE WHEN v.request_type = 'domain_change' THEN NULL ELSE official_url END,
      updated_at = v_now
    WHERE id = v_organization_id
      AND CASE WHEN v.is_test THEN is_test IS TRUE ELSE is_test IS NOT TRUE END;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'organization_not_found';
    END IF;
  ELSE
    INSERT INTO public.organizations (
      name, type, is_test, is_verified, verified_at, is_lg_verified, updated_at
    ) VALUES (
      v.organization_name, COALESCE(NULLIF(v.organization_type, ''), 'other'), v.is_test,
      true, v_now, v.is_lg_domain, v_now
    )
    RETURNING id INTO v_organization_id;
  END IF;

  INSERT INTO public.organization_managers (
    ledger_user_id, organization_id, verified_email, verified_domain, verified_at,
    is_active, is_test, updated_at
  ) VALUES (
    v.ledger_user_id, v_organization_id, v.official_email, v.official_domain, v_now,
    true, v.is_test, v_now
  )
  ON CONFLICT (ledger_user_id, organization_id) DO UPDATE SET
    verified_email = EXCLUDED.verified_email,
    verified_domain = EXCLUDED.verified_domain,
    verified_at = EXCLUDED.verified_at,
    is_active = true,
    is_test = EXCLUDED.is_test,
    updated_at = EXCLUDED.updated_at;

  UPDATE public.organization_manager_verifications SET
    status = 'approved',
    organization_id = v_organization_id,
    reviewed_by = p_reviewer_id,
    reviewed_at = v_now,
    updated_at = v_now
  WHERE id = v.id
  RETURNING * INTO v;

  RETURN v;
END;
$$;

-- Hub のバックエンド（service_role）だけが実行できる
REVOKE ALL ON FUNCTION public.approve_politician_verification(uuid, uuid)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.approve_organization_manager_verification(uuid, uuid)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.approve_politician_verification(uuid, uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.approve_organization_manager_verification(uuid, uuid)
  TO service_role;

COMMIT;
