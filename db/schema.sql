-- Skema tabel yang dibaca dashboard (dijalankan otomatis oleh Postgres saat volume pertama kali dibuat)
CREATE TABLE IF NOT EXISTS events(
  id BIGSERIAL PRIMARY KEY, platform TEXT NOT NULL, event_type TEXT NOT NULL,
  payload JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS research_interactions(
  id BIGSERIAL PRIMARY KEY, platform TEXT NOT NULL, viewer_hash TEXT,
  comment TEXT NOT NULL, recommendation JSONB NOT NULL, transparency JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS trust_surveys(
  id BIGSERIAL PRIMARY KEY, respondent_code TEXT NOT NULL, answers JSONB NOT NULL,
  consent BOOLEAN NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS product_catalog(
  id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, price NUMERIC, description TEXT NOT NULL,
  tags TEXT[] NOT NULL DEFAULT '{}', stock TEXT NOT NULL DEFAULT 'unknown');
