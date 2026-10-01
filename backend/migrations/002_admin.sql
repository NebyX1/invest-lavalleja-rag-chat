ALTER TABLE users ADD COLUMN name TEXT NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN is_superadmin INTEGER NOT NULL DEFAULT 1 CHECK (is_superadmin IN (0, 1));
UPDATE users SET name=email WHERE name='';
