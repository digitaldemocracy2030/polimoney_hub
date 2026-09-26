-- politicians テーブルにプロフィール情報カラムを追加
-- title: 肩書き（例: 「AIエンジニア」「公認会計士」）
-- image_url: プロフィール画像のURL

ALTER TABLE politicians ADD COLUMN IF NOT EXISTS title VARCHAR(100);
ALTER TABLE politicians ADD COLUMN IF NOT EXISTS image_url TEXT;
