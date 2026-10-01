ALTER TABLE sessions ADD COLUMN captcha_id TEXT;
ALTER TABLE sessions ADD COLUMN captcha_question TEXT;
ALTER TABLE sessions ADD COLUMN captcha_hash TEXT;
ALTER TABLE sessions ADD COLUMN captcha_expires REAL NOT NULL DEFAULT 0;
