-- Polimoney Hub - 正規化後スキーマ（v5）
-- 中間テーブル導入 + public_contacts 追加

-- ============================================
-- 基本マスタ（変更なし）
-- ============================================

-- 市区町村マスタ（総務省 全国地方公共団体コード）
CREATE TABLE IF NOT EXISTS municipalities (
    code VARCHAR(6) PRIMARY KEY,
    prefecture_name VARCHAR(10) NOT NULL,
    city_name VARCHAR(50),
    prefecture_name_kana VARCHAR(20),
    city_name_kana VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 選挙区マスタ
CREATE TABLE IF NOT EXISTS districts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL,
    type VARCHAR(10) NOT NULL,
    prefecture_codes VARCHAR(50),
    municipality_code VARCHAR(6) REFERENCES municipalities(code),
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 政治家マスタ
CREATE TABLE IF NOT EXISTS politicians (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    name_kana VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 政治団体マスタ（politician_id を削除）
CREATE TABLE IF NOT EXISTS organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    type VARCHAR(50) NOT NULL,
    -- politician_id 削除: politician_organizations 中間テーブルに移行
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 選挙マスタ（変更なし）
CREATE TABLE IF NOT EXISTS elections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    type VARCHAR(10) NOT NULL,
    district_id UUID REFERENCES districts(id),
    election_date DATE NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- マスタ更新日時（変更なし）
CREATE TABLE IF NOT EXISTS master_metadata (
    table_name VARCHAR(50) PRIMARY KEY,
    last_updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- 勘定科目マスタ（変更なし）
-- ============================================

CREATE TABLE IF NOT EXISTS account_codes (
    code VARCHAR(50) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    name_kana VARCHAR(100),
    type VARCHAR(20) NOT NULL,
    report_category VARCHAR(50) NOT NULL,
    ledger_type VARCHAR(20) NOT NULL DEFAULT 'both',
    is_public_subsidy_eligible BOOLEAN DEFAULT FALSE,
    display_order INT NOT NULL,
    polimoney_category VARCHAR(50),
    parent_code VARCHAR(50) REFERENCES account_codes(code),
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_account_codes_type ON account_codes(type);
CREATE INDEX IF NOT EXISTS idx_account_codes_ledger ON account_codes(ledger_type);
CREATE INDEX IF NOT EXISTS idx_account_codes_order ON account_codes(display_order);
CREATE INDEX IF NOT EXISTS idx_account_codes_active ON account_codes(is_active);

-- ============================================
-- 選挙公営費目マスタ（変更なし）
-- ============================================

CREATE TABLE IF NOT EXISTS election_types (
    code VARCHAR(10) PRIMARY KEY,
    name VARCHAR(50) NOT NULL,
    description TEXT,
    display_order INT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public_subsidy_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    election_type_code VARCHAR(10) NOT NULL REFERENCES election_types(code),
    account_code VARCHAR(50) NOT NULL REFERENCES account_codes(code),
    item_name VARCHAR(100) NOT NULL,
    unit VARCHAR(20),
    unit_price_limit INT,
    quantity_formula TEXT,
    max_quantity INT,
    total_limit INT,
    notes TEXT,
    effective_from DATE,
    effective_until DATE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_subsidy_items_election ON public_subsidy_items(election_type_code);
CREATE INDEX IF NOT EXISTS idx_subsidy_items_account ON public_subsidy_items(account_code);
CREATE INDEX IF NOT EXISTS idx_subsidy_items_active ON public_subsidy_items(is_active);

-- ============================================
-- インデックス（基本マスタ）
-- ============================================

CREATE INDEX IF NOT EXISTS idx_municipalities_prefecture ON municipalities(prefecture_name);
CREATE INDEX IF NOT EXISTS idx_municipalities_active ON municipalities(is_active);
CREATE INDEX IF NOT EXISTS idx_districts_type ON districts(type);
CREATE INDEX IF NOT EXISTS idx_districts_active ON districts(is_active);
CREATE INDEX IF NOT EXISTS idx_districts_municipality ON districts(municipality_code);
CREATE INDEX IF NOT EXISTS idx_organizations_active ON organizations(is_active);
CREATE INDEX IF NOT EXISTS idx_elections_type ON elections(type);
CREATE INDEX IF NOT EXISTS idx_elections_date ON elections(election_date);
CREATE INDEX IF NOT EXISTS idx_elections_district ON elections(district_id);
CREATE INDEX IF NOT EXISTS idx_elections_active ON elections(is_active);

-- ============================================
-- 中間テーブル（新規）
-- ============================================

-- 政治家 ↔ 政治団体（多対多）
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

-- 政治家 ↔ 選挙（多対多）
CREATE TABLE IF NOT EXISTS politician_elections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    politician_id UUID NOT NULL REFERENCES politicians(id),
    election_id UUID NOT NULL REFERENCES elections(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (politician_id, election_id)
);

CREATE INDEX IF NOT EXISTS idx_pol_elec_politician ON politician_elections(politician_id);
CREATE INDEX IF NOT EXISTS idx_pol_elec_election ON politician_elections(election_id);

-- ============================================
-- 公開データ（Ledger から同期）
-- ============================================

-- 公開用台帳（中間テーブル経由の参照に変更）
CREATE TABLE IF NOT EXISTS public_ledgers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ledger_type VARCHAR(20) NOT NULL,  -- 'political_fund' | 'election_fund'
    politician_organization_id UUID REFERENCES politician_organizations(id),
    politician_election_id UUID REFERENCES politician_elections(id),
    fiscal_year INT NOT NULL,
    total_income INT DEFAULT 0,
    total_expense INT DEFAULT 0,
    journal_count INT DEFAULT 0,
    ledger_source_id UUID NOT NULL UNIQUE,
    is_test BOOLEAN DEFAULT FALSE,
    last_updated_at TIMESTAMPTZ NOT NULL,
    first_synced_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT valid_ledger_reference CHECK (
        (ledger_type = 'political_fund' AND politician_organization_id IS NOT NULL AND politician_election_id IS NULL)
        OR
        (ledger_type = 'election_fund' AND politician_election_id IS NOT NULL AND politician_organization_id IS NULL)
    )
);

-- 公開用関係者（新規 — Ledger の contacts に対応）
CREATE TABLE IF NOT EXISTS public_contacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ledger_id UUID NOT NULL REFERENCES public_ledgers(id),
    contact_source_id UUID NOT NULL UNIQUE,           -- Ledger 側の contacts.id
    contact_type VARCHAR(30) NOT NULL,                -- 'person', 'corporation', 'political_organization'
    -- 公開情報（プライバシー設定に基づく）
    -- is_*_private = false の場合: 実際の値を格納
    -- is_*_private = true の場合: NULL を格納
    name TEXT,
    address TEXT,
    occupation TEXT,
    -- プライバシー設定（Ledger から同期）
    is_name_private BOOLEAN NOT NULL DEFAULT FALSE,
    is_address_private BOOLEAN NOT NULL DEFAULT FALSE,
    is_occupation_private BOOLEAN NOT NULL DEFAULT FALSE,
    privacy_reason_type VARCHAR(30),                  -- 'personal_info', 'other'
    privacy_reason_other TEXT,
    -- Hub の政治団体への参照（political_organization タイプの場合）
    hub_organization_id UUID REFERENCES organizations(id),
    synced_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    -- ledger スコープでのユニーク制約（複合FK用）
    UNIQUE (ledger_id, id)
);

-- 公開用仕訳（contact_name/contact_type を廃止、contact_id で参照）
CREATE TABLE IF NOT EXISTS public_journals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ledger_id UUID NOT NULL REFERENCES public_ledgers(id),
    journal_source_id UUID NOT NULL UNIQUE,
    date DATE,
    description TEXT,
    amount INT NOT NULL,
    contact_id UUID REFERENCES public_contacts(id),   -- contact_name/contact_type を廃止
    account_code VARCHAR(50),
    classification VARCHAR(20),
    non_monetary_basis TEXT,
    note TEXT,
    public_expense_amount INT,
    content_hash VARCHAR(64) NOT NULL,
    is_test BOOLEAN DEFAULT FALSE,
    synced_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    -- ledger スコープで contact を参照（他の ledger の contact を参照できない）
    FOREIGN KEY (ledger_id, contact_id) REFERENCES public_contacts(ledger_id, id)
);

-- 変更ログ（変更なし）
CREATE TABLE IF NOT EXISTS ledger_change_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ledger_id UUID NOT NULL REFERENCES public_ledgers(id),
    changed_at TIMESTAMPTZ NOT NULL,
    change_summary TEXT NOT NULL,
    change_details JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- インデックス（公開データ用）
-- ============================================

CREATE INDEX IF NOT EXISTS idx_public_ledgers_type ON public_ledgers(ledger_type);
CREATE INDEX IF NOT EXISTS idx_public_ledgers_pol_org ON public_ledgers(politician_organization_id);
CREATE INDEX IF NOT EXISTS idx_public_ledgers_pol_elec ON public_ledgers(politician_election_id);
CREATE INDEX IF NOT EXISTS idx_public_ledgers_fiscal_year ON public_ledgers(fiscal_year);
CREATE INDEX IF NOT EXISTS idx_public_contacts_ledger ON public_contacts(ledger_id);
CREATE INDEX IF NOT EXISTS idx_public_contacts_source ON public_contacts(contact_source_id);
CREATE INDEX IF NOT EXISTS idx_public_journals_ledger ON public_journals(ledger_id);
CREATE INDEX IF NOT EXISTS idx_public_journals_date ON public_journals(date);
CREATE INDEX IF NOT EXISTS idx_public_journals_contact ON public_journals(contact_id);
CREATE INDEX IF NOT EXISTS idx_change_logs_ledger ON ledger_change_logs(ledger_id);
CREATE INDEX IF NOT EXISTS idx_change_logs_changed_at ON ledger_change_logs(changed_at DESC);

-- ============================================
-- 登録リクエスト（変更なし）
-- ============================================

CREATE TABLE IF NOT EXISTS election_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    type VARCHAR(10) NOT NULL,
    district_id UUID REFERENCES districts(id),
    area_description TEXT,
    election_date DATE NOT NULL,
    requested_by_politician_id UUID REFERENCES politicians(id),
    requested_by_email VARCHAR(255),
    evidence_url TEXT,
    notes TEXT,
    status VARCHAR(20) DEFAULT 'pending',
    rejection_reason TEXT,
    approved_election_id UUID REFERENCES elections(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    reviewed_at TIMESTAMPTZ,
    reviewed_by VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS organization_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    type VARCHAR(50) NOT NULL,
    registration_authority VARCHAR(100),
    requested_by_politician_id UUID REFERENCES politicians(id),
    requested_by_email VARCHAR(255),
    evidence_type VARCHAR(50) NOT NULL,
    evidence_file_url TEXT NOT NULL,
    evidence_file_name VARCHAR(255),
    notes TEXT,
    status VARCHAR(20) DEFAULT 'pending',
    rejection_reason TEXT,
    approved_organization_id UUID REFERENCES organizations(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    reviewed_at TIMESTAMPTZ,
    reviewed_by VARCHAR(255)
);

CREATE INDEX IF NOT EXISTS idx_election_requests_status ON election_requests(status);
CREATE INDEX IF NOT EXISTS idx_election_requests_politician ON election_requests(requested_by_politician_id);
CREATE INDEX IF NOT EXISTS idx_organization_requests_status ON organization_requests(status);
CREATE INDEX IF NOT EXISTS idx_organization_requests_politician ON organization_requests(requested_by_politician_id);

-- ============================================
-- 初期データ
-- ============================================

INSERT INTO master_metadata (table_name, last_updated_at)
VALUES 
    ('municipalities', NOW()),
    ('districts', NOW()),
    ('elections', NOW()),
    ('politicians', NOW()),
    ('organizations', NOW()),
    ('account_codes', NOW()),
    ('election_types', NOW()),
    ('public_subsidy_items', NOW())
ON CONFLICT (table_name) DO NOTHING;

-- ============================================
-- ロック解除リクエスト（変更なし）
-- ============================================

CREATE TABLE IF NOT EXISTS unlock_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ledger_id UUID NOT NULL,
    ledger_type VARCHAR(20) NOT NULL,
    fiscal_year INT,
    requested_by_user_id UUID NOT NULL,
    requested_by_email VARCHAR(255) NOT NULL,
    reason TEXT NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    approved_at TIMESTAMPTZ,
    approved_by UUID,
    unlock_expires_at TIMESTAMPTZ,
    rejection_reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_unlock_requests_status ON unlock_requests(status);
CREATE INDEX IF NOT EXISTS idx_unlock_requests_ledger ON unlock_requests(ledger_id);
CREATE INDEX IF NOT EXISTS idx_unlock_requests_expires ON unlock_requests(unlock_expires_at);

-- ============================================
-- 管理者テーブル（変更なし）
-- ============================================

CREATE TABLE IF NOT EXISTS admin_users (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email VARCHAR(255) NOT NULL,
    name VARCHAR(255),
    role VARCHAR(20) DEFAULT 'admin',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_admin_users_email ON admin_users(email);
CREATE INDEX IF NOT EXISTS idx_admin_users_active ON admin_users(is_active);

-- ============================================
-- Row Level Security (RLS)
-- ============================================

ALTER TABLE municipalities ENABLE ROW LEVEL SECURITY;
ALTER TABLE districts ENABLE ROW LEVEL SECURITY;
ALTER TABLE politicians ENABLE ROW LEVEL SECURITY;
ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE elections ENABLE ROW LEVEL SECURITY;
ALTER TABLE master_metadata ENABLE ROW LEVEL SECURITY;
ALTER TABLE account_codes ENABLE ROW LEVEL SECURITY;
ALTER TABLE election_types ENABLE ROW LEVEL SECURITY;
ALTER TABLE public_subsidy_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE politician_organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE politician_elections ENABLE ROW LEVEL SECURITY;
ALTER TABLE public_ledgers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public_contacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public_journals ENABLE ROW LEVEL SECURITY;
ALTER TABLE ledger_change_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE election_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE organization_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE unlock_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE admin_users ENABLE ROW LEVEL SECURITY;

-- 読み取りポリシー（全員許可）
CREATE POLICY "Allow public read" ON municipalities FOR SELECT USING (true);
CREATE POLICY "Allow public read" ON districts FOR SELECT USING (true);
CREATE POLICY "Allow public read" ON politicians FOR SELECT USING (true);
CREATE POLICY "Allow public read" ON organizations FOR SELECT USING (true);
CREATE POLICY "Allow public read" ON elections FOR SELECT USING (true);
CREATE POLICY "Allow public read" ON master_metadata FOR SELECT USING (true);
CREATE POLICY "Allow public read" ON account_codes FOR SELECT USING (true);
CREATE POLICY "Allow public read" ON election_types FOR SELECT USING (true);
CREATE POLICY "Allow public read" ON public_subsidy_items FOR SELECT USING (true);
CREATE POLICY "Allow public read" ON politician_organizations FOR SELECT USING (true);
CREATE POLICY "Allow public read" ON politician_elections FOR SELECT USING (true);
CREATE POLICY "Allow public read" ON public_ledgers FOR SELECT USING (true);
CREATE POLICY "Allow public read" ON public_contacts FOR SELECT USING (true);
CREATE POLICY "Allow public read" ON public_journals FOR SELECT USING (true);
CREATE POLICY "Allow public read" ON ledger_change_logs FOR SELECT USING (true);

-- 申請テーブル: 認証済みかつ申請本人のみ閲覧可能（PII保護）
CREATE POLICY "Allow own read" ON election_requests FOR SELECT
    USING (auth.uid() = requested_by_politician_id);
CREATE POLICY "Allow own read" ON organization_requests FOR SELECT
    USING (auth.uid() = requested_by_politician_id);
CREATE POLICY "Allow own read" ON unlock_requests FOR SELECT
    USING (auth.uid() = requested_by_user_id);

-- 管理者は自分のデータのみ読める
CREATE POLICY "Admin users can read own data" ON admin_users FOR SELECT USING (auth.uid() = id);

-- 書き込みポリシー（service_role のみ）
CREATE POLICY "Allow service write" ON municipalities FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Allow service write" ON districts FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Allow service write" ON politicians FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Allow service write" ON organizations FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Allow service write" ON elections FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Allow service write" ON master_metadata FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Allow service write" ON account_codes FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Allow service write" ON election_types FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Allow service write" ON public_subsidy_items FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Allow service write" ON politician_organizations FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Allow service write" ON politician_elections FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Allow service write" ON public_ledgers FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Allow service write" ON public_contacts FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Allow service write" ON public_journals FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Allow service write" ON ledger_change_logs FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Allow service write" ON election_requests FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Allow service write" ON organization_requests FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Allow service write" ON unlock_requests FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Allow service write" ON admin_users FOR ALL USING (auth.role() = 'service_role');
