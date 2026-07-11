-- ============================================
-- Polimoney Hub: 正規化マイグレーション
-- 実行前に必ずバックアップを取得すること！
-- ============================================

BEGIN;

-- ============================================
-- Step 1: 中間テーブル作成
-- ============================================

-- 政治家 ↔ 政治団体
CREATE TABLE IF NOT EXISTS politician_organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    politician_id UUID NOT NULL REFERENCES politicians(id),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    role VARCHAR(20) DEFAULT 'representative',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (politician_id, organization_id)
);

CREATE INDEX IF NOT EXISTS idx_pol_org_politician ON politician_organizations(politician_id);
CREATE INDEX IF NOT EXISTS idx_pol_org_organization ON politician_organizations(organization_id);

-- 政治家 ↔ 選挙
CREATE TABLE IF NOT EXISTS politician_elections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    politician_id UUID NOT NULL REFERENCES politicians(id),
    election_id UUID NOT NULL REFERENCES elections(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (politician_id, election_id)
);

CREATE INDEX IF NOT EXISTS idx_pol_elec_politician ON politician_elections(politician_id);
CREATE INDEX IF NOT EXISTS idx_pol_elec_election ON politician_elections(election_id);

-- 公開用関係者
CREATE TABLE IF NOT EXISTS public_contacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ledger_id UUID NOT NULL,  -- FK は後で追加（public_ledgers の変更後）
    contact_source_id UUID NOT NULL UNIQUE,
    contact_type VARCHAR(30) NOT NULL,
    name TEXT,
    address TEXT,
    occupation TEXT,
    is_name_private BOOLEAN NOT NULL DEFAULT FALSE,
    is_address_private BOOLEAN NOT NULL DEFAULT FALSE,
    is_occupation_private BOOLEAN NOT NULL DEFAULT FALSE,
    privacy_reason_type VARCHAR(30),
    privacy_reason_other TEXT,
    hub_organization_id UUID REFERENCES organizations(id),
    synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    -- ledger スコープでのユニーク制約
    UNIQUE (ledger_id, id)
);

CREATE INDEX IF NOT EXISTS idx_public_contacts_ledger ON public_contacts(ledger_id);
CREATE INDEX IF NOT EXISTS idx_public_contacts_source ON public_contacts(contact_source_id);

-- RLS
ALTER TABLE politician_organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE politician_elections ENABLE ROW LEVEL SECURITY;
ALTER TABLE public_contacts ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow public read" ON politician_organizations FOR SELECT USING (true);
CREATE POLICY "Allow public read" ON politician_elections FOR SELECT USING (true);
CREATE POLICY "Allow public read" ON public_contacts FOR SELECT USING (true);
CREATE POLICY "Allow service write" ON politician_organizations FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Allow service write" ON politician_elections FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Allow service write" ON public_contacts FOR ALL USING (auth.role() = 'service_role');

-- ============================================
-- Step 2: 既存データを中間テーブルに移行
-- ============================================

-- organizations.politician_id → politician_organizations
INSERT INTO politician_organizations (politician_id, organization_id)
SELECT politician_id, id
FROM organizations
WHERE politician_id IS NOT NULL
ON CONFLICT (politician_id, organization_id) DO NOTHING;

-- public_ledgers の politician_id + election_id → politician_elections
INSERT INTO politician_elections (politician_id, election_id)
SELECT DISTINCT politician_id, election_id
FROM public_ledgers
WHERE election_id IS NOT NULL
ON CONFLICT (politician_id, election_id) DO NOTHING;

-- ============================================
-- Step 3: public_ledgers に新カラム追加
-- ============================================

ALTER TABLE public_ledgers ADD COLUMN IF NOT EXISTS ledger_type VARCHAR(20);
ALTER TABLE public_ledgers ADD COLUMN IF NOT EXISTS politician_organization_id UUID REFERENCES politician_organizations(id);
ALTER TABLE public_ledgers ADD COLUMN IF NOT EXISTS politician_election_id UUID REFERENCES politician_elections(id);

CREATE INDEX IF NOT EXISTS idx_public_ledgers_type ON public_ledgers(ledger_type);
CREATE INDEX IF NOT EXISTS idx_public_ledgers_pol_org ON public_ledgers(politician_organization_id);
CREATE INDEX IF NOT EXISTS idx_public_ledgers_pol_elec ON public_ledgers(politician_election_id);

-- ============================================
-- Step 4: public_ledgers の既存データを新カラムに移行
-- ============================================

UPDATE public_ledgers pl SET
    ledger_type = CASE
        WHEN pl.election_id IS NOT NULL THEN 'election_fund'
        ELSE 'political_fund'
    END,
    politician_organization_id = CASE
        WHEN pl.election_id IS NULL THEN (
            SELECT po.id FROM politician_organizations po
            WHERE po.politician_id = pl.politician_id
              AND po.organization_id = pl.organization_id
        )
        ELSE NULL
    END,
    politician_election_id = CASE
        WHEN pl.election_id IS NOT NULL THEN (
            SELECT pe.id FROM politician_elections pe
            WHERE pe.politician_id = pl.politician_id
              AND pe.election_id = pl.election_id
        )
        ELSE NULL
    END;

ALTER TABLE public_journals ADD COLUMN IF NOT EXISTS contact_id UUID REFERENCES public_contacts(id);
CREATE INDEX IF NOT EXISTS idx_public_journals_contact ON public_journals(contact_id);

-- public_journals に ledger スコープの複合 FK を追加
ALTER TABLE public_journals
    ADD CONSTRAINT fk_public_journals_contact_ledger
    FOREIGN KEY (ledger_id, contact_id)
    REFERENCES public_contacts(ledger_id, id);

-- ============================================
-- Step 6: public_contacts に FK 追加（public_ledgers 変更後）
-- ============================================

ALTER TABLE public_contacts
    ADD CONSTRAINT fk_public_contacts_ledger
    FOREIGN KEY (ledger_id) REFERENCES public_ledgers(id);

-- ============================================
-- Step 7: contact_id バックフィル（既存データを新スキーマへ移行）
-- ============================================

-- public_journals の contact_name/contact_type を使って public_contacts を作成
-- （既存データがある場合のみ。contact_name が NULL のレコードはスキップ）
INSERT INTO public_contacts (ledger_id, contact_source_id, contact_type, name, synced_at)
SELECT DISTINCT pj.ledger_id,
    gen_random_uuid(),  -- 旧データにはソースIDがないため仮UUID生成
    COALESCE(pj.contact_type, 'person'),
    pj.contact_name,
    NOW()
FROM public_journals pj
WHERE pj.contact_name IS NOT NULL
  AND pj.contact_id IS NULL
ON CONFLICT DO NOTHING;

-- public_journals.contact_id を名前マッチングで更新
UPDATE public_journals pj SET
    contact_id = (
        SELECT pc.id FROM public_contacts pc
        WHERE pc.ledger_id = pj.ledger_id
          AND pc.name = pj.contact_name
        LIMIT 1
    )
WHERE pj.contact_name IS NOT NULL
  AND pj.contact_id IS NULL;

-- ============================================
-- Step 8: 旧カラム削除（バックフィル完了後）
-- ============================================

-- public_ledgers から旧カラム削除
DROP INDEX IF EXISTS idx_public_ledgers_politician;
DROP INDEX IF EXISTS idx_public_ledgers_election;
DROP INDEX IF EXISTS idx_organizations_politician_id;

ALTER TABLE public_ledgers DROP COLUMN IF EXISTS politician_id;
ALTER TABLE public_ledgers DROP COLUMN IF EXISTS organization_id;
ALTER TABLE public_ledgers DROP COLUMN IF EXISTS election_id;

-- public_journals から旧カラム削除（バックフィル完了後のため安全）
ALTER TABLE public_journals DROP COLUMN IF EXISTS contact_name;
ALTER TABLE public_journals DROP COLUMN IF EXISTS contact_type;

-- organizations から politician_id 削除
ALTER TABLE organizations DROP COLUMN IF EXISTS politician_id;

-- ============================================
-- Step 9: NOT NULL 制約・CHECK 制約追加
-- ============================================

ALTER TABLE public_ledgers ALTER COLUMN ledger_type SET NOT NULL;

ALTER TABLE public_ledgers ADD CONSTRAINT valid_ledger_reference CHECK (
    (ledger_type = 'political_fund' AND politician_organization_id IS NOT NULL AND politician_election_id IS NULL)
    OR
    (ledger_type = 'election_fund' AND politician_election_id IS NOT NULL AND politician_organization_id IS NULL)
);

COMMIT;
