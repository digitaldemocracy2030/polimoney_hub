-- Polimoney Hub - 登録申請（選挙・政治団体）と年度のロック解除申請の受付・審査
--
-- - 3 つの申請テーブルに is_test を足す（DEV キーの申請はテストデータ。本番データと混ざらない）
-- - 選挙・政治団体の申請に、申請者の Ledger ユーザー（ledger_user_id）と updated_at を足す
-- - 政治団体の申請に、証明書類の Ledger Storage 上のパス（evidence_file_path）を足す
--   （evidence_file_url は期限付きの署名付き URL のため、期限切れ後の再発行に使う）
-- - 「申請中は 1 件まで」を部分一意インデックスで守る（API は一意制約違反を 409 にする）
-- - 選挙・政治団体の承認は、マスタの行の作成（または既存の行への紐付け）と申請の更新を
--   1 つのトランザクションで行う DB の関数にする
--
-- 追加のみの変更なので、先に適用しても今のコードは壊れない。
-- 適用: supabase db query --linked -f db/migrate-request-review.sql
-- 適用前に、申請中の重複が無いことを確かめる（あれば一意インデックスの作成が失敗する）:
--   SELECT ledger_id, fiscal_year, count(*) FROM unlock_requests
--    WHERE status = 'pending' GROUP BY 1, 2 HAVING count(*) > 1;

BEGIN;

-- ============================================
-- 列
-- ============================================
ALTER TABLE public.election_requests
  ADD COLUMN IF NOT EXISTS is_test boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS ledger_user_id uuid,
  ADD COLUMN IF NOT EXISTS updated_at timestamptz DEFAULT now();

ALTER TABLE public.organization_requests
  ADD COLUMN IF NOT EXISTS is_test boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS ledger_user_id uuid,
  ADD COLUMN IF NOT EXISTS evidence_file_path text,
  ADD COLUMN IF NOT EXISTS updated_at timestamptz DEFAULT now();

ALTER TABLE public.unlock_requests
  ADD COLUMN IF NOT EXISTS is_test boolean NOT NULL DEFAULT false;

-- ============================================
-- インデックス
-- ============================================
-- いずれも is_test を含める（テストデータと本番データの申請が互いに 409 にならないように）

-- 同じ申請者が、同じ選挙（名前と投開票日）を重ねて申請中にしない
CREATE UNIQUE INDEX IF NOT EXISTS uq_election_requests_pending
  ON public.election_requests (is_test, ledger_user_id, name, election_date)
  WHERE status = 'pending';

-- 同じ申請者が、同じ政治団体（名前）を重ねて申請中にしない
CREATE UNIQUE INDEX IF NOT EXISTS uq_organization_requests_pending
  ON public.organization_requests (is_test, ledger_user_id, name)
  WHERE status = 'pending';

-- 同じ台帳の同じ年度のロック解除は、申請中を 1 件まで
CREATE UNIQUE INDEX IF NOT EXISTS uq_unlock_requests_pending
  ON public.unlock_requests (is_test, ledger_id, COALESCE(fiscal_year, 0))
  WHERE status = 'pending';

-- 解除状態の確認（台帳ごとに新しい順）
CREATE INDEX IF NOT EXISTS idx_unlock_requests_ledger_created
  ON public.unlock_requests (ledger_id, created_at DESC);

-- ============================================
-- 選挙の登録申請の承認
-- ============================================
-- p_election_id を指定すると、既存の選挙に紐付ける（作らない）。
-- 指定しなければ申請の内容で選挙を作る。どちらも申請の is_test の範囲の選挙だけを扱う。
CREATE OR REPLACE FUNCTION public.approve_election_request(
  p_request_id uuid,
  p_reviewer_id uuid,
  p_election_id uuid DEFAULT NULL
) RETURNS public.election_requests
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
  r public.election_requests;
  v_election_id uuid;
  v_now timestamptz := now();
BEGIN
  SELECT * INTO r FROM public.election_requests
   WHERE id = p_request_id
   FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'request_not_found';
  END IF;
  IF r.status IS DISTINCT FROM 'pending' THEN
    RAISE EXCEPTION 'request_not_pending';
  END IF;

  IF p_election_id IS NOT NULL THEN
    SELECT id INTO v_election_id FROM public.elections
     WHERE id = p_election_id
       AND CASE WHEN r.is_test THEN is_test IS TRUE ELSE is_test IS NOT TRUE END;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'election_not_found';
    END IF;
  ELSE
    INSERT INTO public.elections (
      name, type, district_id, election_date, is_active, is_test, updated_at
    ) VALUES (
      r.name, r.type, r.district_id, r.election_date, true, r.is_test, v_now
    )
    RETURNING id INTO v_election_id;
  END IF;

  UPDATE public.election_requests SET
    status = 'approved',
    approved_election_id = v_election_id,
    reviewed_by = p_reviewer_id::text,
    reviewed_at = v_now,
    updated_at = v_now
  WHERE id = r.id
  RETURNING * INTO r;

  RETURN r;
END;
$$;

-- ============================================
-- 政治団体の登録申請の承認
-- ============================================
-- p_organization_id を指定すると、既存の政治団体に紐付ける（作らない）。
-- 指定しなければ申請の内容で政治団体を作る。どちらも申請の is_test の範囲の団体だけを扱う。
CREATE OR REPLACE FUNCTION public.approve_organization_request(
  p_request_id uuid,
  p_reviewer_id uuid,
  p_organization_id uuid DEFAULT NULL
) RETURNS public.organization_requests
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
  r public.organization_requests;
  v_organization_id uuid;
  v_now timestamptz := now();
BEGIN
  SELECT * INTO r FROM public.organization_requests
   WHERE id = p_request_id
   FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'request_not_found';
  END IF;
  IF r.status IS DISTINCT FROM 'pending' THEN
    RAISE EXCEPTION 'request_not_pending';
  END IF;

  IF p_organization_id IS NOT NULL THEN
    SELECT id INTO v_organization_id FROM public.organizations
     WHERE id = p_organization_id
       AND CASE WHEN r.is_test THEN is_test IS TRUE ELSE is_test IS NOT TRUE END;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'organization_not_found';
    END IF;
  ELSE
    INSERT INTO public.organizations (
      name, type, registration_authority, is_active, is_test, updated_at
    ) VALUES (
      r.name, r.type, r.registration_authority, true, r.is_test, v_now
    )
    RETURNING id INTO v_organization_id;
  END IF;

  UPDATE public.organization_requests SET
    status = 'approved',
    approved_organization_id = v_organization_id,
    reviewed_by = p_reviewer_id::text,
    reviewed_at = v_now,
    updated_at = v_now
  WHERE id = r.id
  RETURNING * INTO r;

  RETURN r;
END;
$$;

-- Hub のバックエンド（service_role）だけが実行できる
REVOKE ALL ON FUNCTION public.approve_election_request(uuid, uuid, uuid)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.approve_organization_request(uuid, uuid, uuid)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.approve_election_request(uuid, uuid, uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.approve_organization_request(uuid, uuid, uuid)
  TO service_role;

COMMIT;
