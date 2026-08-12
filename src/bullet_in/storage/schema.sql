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
  image_url VARCHAR(1024), images_json TEXT, outlet VARCHAR(128), journalist VARCHAR(128),
  team VARCHAR(32) DEFAULT 'arsenal',
  transfer_stage VARCHAR(32),
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
-- transfer_stage 의 collapsed 와 transfer_direction 은 아스날 관점 값이다 (단계 재정의
-- 스펙 2026-08-10 §9) — 같은 기사가 타 구단 관점에선 다른 값이므로, 분석 · 알림 등
-- 다른 소비자가 구단 중립 값으로 쓰면 안 된다. 멀티 클럽 확장 시 전 구단 재도출 대상.
ALTER TABLE articles ADD COLUMN IF NOT EXISTS transfer_stage VARCHAR(32);
ALTER TABLE articles ADD COLUMN IF NOT EXISTS transfer_direction VARCHAR(8);
ALTER TABLE articles ADD COLUMN IF NOT EXISTS images_json TEXT;
ALTER TABLE articles ADD COLUMN IF NOT EXISTS published_precision VARCHAR(4);
ALTER TABLE articles ADD COLUMN IF NOT EXISTS body_level TINYINT;
ALTER TABLE articles ADD COLUMN IF NOT EXISTS rewrite_retention FLOAT;
-- 공홈 채택 경로 ('tag' · 'title') — 단계 규칙이 태그 채택분에만 official 을 고정한다
-- (공홈 수집 개정 스펙 2026-08-12 §3.3). 분류 패스는 수집 회차와 분리돼 (429 로 밀리면
-- 다음 회차가 처리) 회차 메모리로는 남길 수 없어 행에 저장한다. 개정 전 적재분의 NULL 은
-- 전건 태그 채택이라 고정 유지로 읽힌다.
ALTER TABLE articles ADD COLUMN IF NOT EXISTS accept_path VARCHAR(16);
CREATE TABLE IF NOT EXISTS pipeline_runs (
  run_id VARCHAR(64) PRIMARY KEY, dag_run_id VARCHAR(128),
  started_at DATETIME, finished_at DATETIME, duration_sec FLOAT,
  fetch_duration_sec FLOAT,
  source_counts JSON, new_count INT, dup_count INT, error_count INT,
  success_rate FLOAT);
CREATE TABLE IF NOT EXISTS source_freshness (
  run_id VARCHAR(64), checked_at DATETIME, source_id VARCHAR(64),
  last_fetched_at DATETIME, age_hours FLOAT, threshold_hours FLOAT,
  stale BOOLEAN,
  PRIMARY KEY (run_id, source_id));
ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS fetch_duration_sec FLOAT;
ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS blocked_count INT;
ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS candidate_counts JSON;
CREATE TABLE IF NOT EXISTS players (
  id INT AUTO_INCREMENT PRIMARY KEY,
  full_name VARCHAR(100) NOT NULL UNIQUE,
  first_name VARCHAR(50),
  surname VARCHAR(50) NOT NULL,
  ko_name VARCHAR(50),
  ko_candidate VARCHAR(50),
  club VARCHAR(50),
  category VARCHAR(16) NOT NULL,
  status VARCHAR(16) NOT NULL,
  transfer_status VARCHAR(16) NOT NULL,
  origin VARCHAR(16) NOT NULL,
  first_seen CHAR(64),
  added_at DATETIME NOT NULL,
  confirmed_at DATETIME,
  archived_at DATETIME);
ALTER TABLE players ADD COLUMN IF NOT EXISTS ko_full_name VARCHAR(60);
CREATE TABLE IF NOT EXISTS article_players (
  content_hash CHAR(64) NOT NULL,
  player_id INT NOT NULL,
  stage VARCHAR(32),
  extracted_at DATETIME NOT NULL,
  PRIMARY KEY (content_hash, player_id));
ALTER TABLE article_players ADD COLUMN IF NOT EXISTS role VARCHAR(16);
