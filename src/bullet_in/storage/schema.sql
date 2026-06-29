CREATE TABLE IF NOT EXISTS sources (
  source_id VARCHAR(64) PRIMARY KEY, display_name VARCHAR(128),
  tier FLOAT, medium VARCHAR(32), enabled BOOLEAN DEFAULT TRUE);
CREATE TABLE IF NOT EXISTS articles (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  content_hash CHAR(64) NOT NULL UNIQUE,
  url VARCHAR(512) NOT NULL UNIQUE,
  source_id VARCHAR(64), author VARCHAR(128),
  tier FLOAT, confidence_score FLOAT,
  title_original TEXT, title_ko TEXT, summary_ko TEXT, body_excerpt TEXT,
  summary3_ko TEXT, body_ko TEXT, body_source TEXT,
  image_url VARCHAR(1024), outlet VARCHAR(128), journalist VARCHAR(128),
  team VARCHAR(32) DEFAULT 'arsenal',
  published_at DATETIME, fetched_at DATETIME,
  revision INT DEFAULT 1,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP);
ALTER TABLE articles ADD COLUMN IF NOT EXISTS summary3_ko TEXT;
ALTER TABLE articles ADD COLUMN IF NOT EXISTS body_ko TEXT;
ALTER TABLE articles ADD COLUMN IF NOT EXISTS body_source TEXT;
ALTER TABLE articles ADD COLUMN IF NOT EXISTS image_url VARCHAR(1024);
ALTER TABLE articles ADD COLUMN IF NOT EXISTS outlet VARCHAR(128);
ALTER TABLE articles ADD COLUMN IF NOT EXISTS journalist VARCHAR(128);
ALTER TABLE articles ADD COLUMN IF NOT EXISTS team VARCHAR(32) DEFAULT 'arsenal';
CREATE TABLE IF NOT EXISTS pipeline_runs (
  run_id VARCHAR(64) PRIMARY KEY, dag_run_id VARCHAR(128),
  started_at DATETIME, finished_at DATETIME, duration_sec FLOAT,
  source_counts JSON, new_count INT, dup_count INT, error_count INT,
  success_rate FLOAT)
