# 목업을 VM 최신 데이터로 재렌더하는 절차 (2026-07-22)

서빙 UI 개편 목업은 저장소 밖 스크래치패드에서 돌아가며 MariaDB 를 직접 읽는다.
로컬 mart 는 VM 보다 낡아 (한때 로컬 205행 대 VM 227행 · 약 41시간 차이), 목업이 옛 타임스탬프와 옛 번역을 보여 준다.
이 절차는 운영 VM 의 최신 데이터를 로컬에 별도로 받아 목업만 새로 뜨는 방법이다.
운영 DB 도 로컬 기존 DB 도 건드리지 않는다.

## 1. 언제 이 절차를 쓰나

- 번역 모델 교체 · 백필 후 목업이 옛 번역을 보여 줄 때.
- 로컬 mart 가 낡아 목업 타임스탬프가 수집 시각 무더기 (`06:57` 같은) 로 뭉쳐 보일 때.
- 목업 설계 판단에 라이브와 같은 데이터가 필요할 때.

설계 판단이 데이터 신선도와 무관하면 (위계 시각 표현 등) 재렌더하지 않는다.
운영 VM 접속은 얻는 것이 분명할 때만 한다.

## 2. VM 에서 articles 덤프

VM 접속은 `ubuntu@155.248.164.17` · 키 `~/.ssh/seoulnow_deploy` (vm-cohost 런북과 동일).
`mysql` 클라이언트는 컨테이너에 없다 — `mariadb` · `mariadb-dump` 를 쓴다.

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 'cd ~/bullet-in && set -a && . ./.env && set +a
  read NAME USER PASS <<< "$(python3 -c "import os,urllib.parse as u; p=u.urlparse(os.environ[\"MARIADB_URL\"]); print(p.path.lstrip(\"/\"), p.username, p.password)")"
  docker exec bullet-in-mariadb-1 mariadb-dump -u"$USER" -p"$PASS" --no-tablespaces "$NAME" articles 2>/dev/null | gzip > /tmp/articles.sql.gz'
scp -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17:/tmp/articles.sql.gz <스크래치패드>/
```

## 3. 로컬 별도 DB 에 적재 — 기존 DB 는 건드리지 않는다

로컬 운영 DB 이름 (`bulletin`) 이 아니라 `bulletin_mock` 에 넣는다.
목업만 이 DB 를 읽고, 파이프라인 · 서빙은 기존 `bulletin` 을 그대로 쓴다.

```bash
set -a && . .env && set +a
read NAME USER PASS <<< "$(python3 -c "import os,urllib.parse as u; p=u.urlparse(os.environ['MARIADB_URL']); print(p.path.lstrip('/'), p.username, p.password)")"
docker exec -i bullet-in-mariadb-1 mariadb -u"$USER" -p"$PASS" -e "CREATE DATABASE IF NOT EXISTS bulletin_mock"
gunzip -c <스크래치패드>/articles.sql.gz | docker exec -i bullet-in-mariadb-1 mariadb -u"$USER" -p"$PASS" bulletin_mock
```

적재 후 두 DB 행 수를 함께 찍어 기존 DB 가 그대로인지 확인한다.

## 3.1. 드리프트 확인 — 로컬이 얼마나 낡았는지 먼저 잰다

받은 사본과 기존 로컬을 대조해 둔다.
**로컬 수치를 배포판 현황으로 말하기 전에 이 표를 만든다.**
이 절차 없이 로컬로 판단했다가 이미 수동 정정된 행을 "고쳐야 할 오류" 로 잘못 제시한 사례가 있다
(`docs/superpowers/2026-07-28-content-trust-audit-handoff.md` 2.2절 · 6.1절).

```sql
-- 행 대조
SELECT COUNT(*) FROM bulletin.articles a JOIN bulletin_mock.articles b USING(content_hash);
SELECT COUNT(*) FROM bulletin_mock.articles b
  LEFT JOIN bulletin.articles a USING(content_hash) WHERE a.content_hash IS NULL;   -- 배포판에만
SELECT COUNT(*) FROM bulletin.articles a
  LEFT JOIN bulletin_mock.articles b USING(content_hash) WHERE b.content_hash IS NULL;  -- 로컬에만

-- 같은 기사인데 값이 다른 것
SELECT COUNT(*) FROM bulletin.articles a JOIN bulletin_mock.articles b USING(content_hash)
  WHERE a.title_ko <> b.title_ko;                                    -- 재번역으로 제목 변경
SELECT a.transfer_stage, b.transfer_stage, b.source_id, LEFT(b.title_ko, 44)
  FROM bulletin.articles a JOIN bulletin_mock.articles b USING(content_hash)
  WHERE NOT (a.transfer_stage <=> b.transfer_stage);                 -- 라이브 수동 정정 흔적
```

**2026-07-28 실측** (로컬 205행 · 7월 19일 수집 대 배포판 467행 · 7월 27일 수집).

| 항목 | 값 |
| --- | --- |
| 양쪽 공통 | 198건 |
| 배포판에만 | 269건 |
| 로컬에만 | 7건 |
| 공통 행 중 제목 상이 | **196건** (재번역으로 거의 전부) |
| 공통 행 중 단계 상이 | 3건 (라이브 수동 정정분) |

**제목은 식별자가 되지 못한다.**
번역 모델 교체로 전건 재번역이 돌면 같은 기사의 `title_ko` 가 바뀐다.
기사를 언급할 때는 `content_hash` 기반 배포판 URL (`https://bullet-in.pages.dev/article/<hash>`) 을 함께 적는다.
제목만 적으면 사용자가 라이브에서 찾지 못한다.

단계가 다른 행은 사람이 직접 고친 흔적이다.
커밋 메시지의 `Refs:` 에 해시가 남아 있는지 확인하면 어느 작업에서 정정했는지 추적된다.

## 4. build.py 를 별도 DB 로 실행

`MARIADB_URL` 의 경로만 `/bulletin_mock` 으로 바꿔 목업 생성 스크립트를 돌린다.
셸 export 는 이 스크립트 실행에만 유효하고 `.env` 파일은 안 바뀐다.

```bash
export MARIADB_URL="$(python3 -c "
import os,urllib.parse as u
p=u.urlparse(os.environ['MARIADB_URL'])
print(p._replace(path='/bulletin_mock').geturl())")"
uv run python <목업 build.py 경로>
```

이후 F안 변환 스크립트 (`build_f.py` · `make_variants.py`) 를 이어서 돌린다.

## 5. 함정

- **`mysql` 이 아니라 `mariadb`** — 컨테이너 이미지가 MariaDB 라 `mysql` 바이너리가 없다.
- **DB 이름을 반드시 분리** — 기존 `bulletin` 에 덤프를 부으면 로컬 파이프라인 상태가 오염된다.
백필 덤프는 되돌릴 수 없다.
- **재렌더 전 기존 목업 백업** — `build.py` 가 `out/` 을 덮으므로, 비교가 필요하면 `out-prebackfill-<시각>` 으로 먼저 복사한다.
- **이 DB 는 임시본** — 판단이 끝나면 `DROP DATABASE bulletin_mock` 으로 정리한다.

## 6. 참고

- VM 부트스트랩 · 접속 : `docs/runbook/2026-07-20-vm-cohost-bootstrap.md`.
- 서빙 SELECT 컬럼 목록 : `run.py` 의 `SERVING_SELECT_SQL` 상수 (#107).
- UI 개편 구현 인수인계 : 세션 메모리 `ui-redesign-implementation-handoff`.
