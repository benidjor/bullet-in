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
-- 저자 전원 (대표 포함) — 공저 기사가 저자 각각의 기자 필터에 도달하게 하는 입력.
-- journalist 는 대표 1명으로 남는다 (카드 표기 · tier 판정이 단일 값을 쓴다).
ALTER TABLE articles ADD COLUMN IF NOT EXISTS authors_json TEXT;
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
  stale BOOLEAN, stored_fetched_at DATETIME NULL,
  PRIMARY KEY (run_id, source_id));
ALTER TABLE source_freshness ADD COLUMN IF NOT EXISTS stored_fetched_at DATETIME NULL;
ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS fetch_duration_sec FLOAT;
ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS blocked_count INT;
ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS candidate_counts JSON;
ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS fetch_detail JSON;
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
-- 소속 두 축 (2026-08-27) — club 은 **현 소속**, former_club 은 **전 소속**이다.
--
-- 그전에는 club 한 칸에 두 뜻이 섞여 있었다 (실측 40행 중 5행) — 타 클럽행인 고든 ·
-- 토날리에는 전 소속 (Newcastle) 이, 아스날 영입을 마친 콘사에는 전 소속
-- (Aston Villa) 이 들어 있었고, 같은 타 클럽행인 로저스 · 앤더슨에는 간 곳이 있었다.
-- 값만 봐서는 어느 쪽인지 못 갈라 화면에 쓸 수 없었다.
--
-- 두 칸으로 가르면 이적 축의 여러 자리가 같은 재료를 쓴다 — 타 클럽행은 "어디로
-- 갔나" (club), 영입 완료는 "어디서 왔나" (former_club), 진행 중은 "지금 어디 있나"
-- (club) 를 각각 읽는다.
ALTER TABLE players ADD COLUMN IF NOT EXISTS former_club VARCHAR(50);
-- 손으로 고정한 카드 사진 (2026-08-28). 비어 있으면 렌더가 그 선수의 최근 기사
-- 사진을 자동으로 고른다 (serve.render.assign_player_photos). 자동 선택은 새 기사가
-- 들어올 때마다 갈아타므로 (30일에 177회 실측) 얼굴이 어긋난 선수만 여기에 박는다.
-- 값을 넣는 곳은 `python -m bullet_in.set_player_photo` 하나다.
ALTER TABLE players ADD COLUMN IF NOT EXISTS photo_url VARCHAR(1024);
CREATE TABLE IF NOT EXISTS article_players (
  content_hash CHAR(64) NOT NULL,
  player_id INT NOT NULL,
  stage VARCHAR(32),
  extracted_at DATETIME NOT NULL,
  PRIMARY KEY (content_hash, player_id));
ALTER TABLE article_players ADD COLUMN IF NOT EXISTS role VARCHAR(16);
-- 역할 미기입을 저장 단계에서 막는다 — 서빙은 이 값 하나로 선수 페이지 목록을
-- 가르므로, 비어 들어오면 주역으로 읽든 언급으로 읽든 화면이 조용히 틀어진다.
-- 값을 만드는 규칙 (roster.decide_role) 이 항상 주역 · 언급 중 하나를 돌려주고
-- 운영 2,889쌍에 미기입이 0 이라 이 제약은 기존 행을 건드리지 않는다.
ALTER TABLE article_players MODIFY IF EXISTS role VARCHAR(16) NOT NULL;
