# 런북 — BBC 수집 드리프트 정리 (2026-06-30)

bbc_sport 셀렉터 교정(`fix/tier1-bbc-collection-drift`) 이전 적재된 비-기사 · 깨진-제목 행과
football.london 뉴스레터 legacy 링크를 일회성으로 정리한다.
**실행은 라이브 MariaDB 가 떠 있는 상태에서 직접 수행하며, COUNT 확인 후 DELETE 한다.**

## 선행
- bbc_sport 어댑터 교정(셀렉터 · title_selector)이 머지 · 배포돼 있어야 한다(재수집이 깨끗해야 의미 있음).
- 접속 준비:
  ```bash
  set -a; source .env; set +a
  docker compose ps   # mariadb running 확인
  ```

## 절차
1. 대상 수 확인(삭제 전 반드시):
   ```sql
   SELECT source_id, COUNT(*) FROM articles
   WHERE source_id = 'bbc_sport'
      OR (source_id = 'football_london'
          AND (LOWER(title_original) LIKE '%sent to your inbox%'
               OR LOWER(title_original) LIKE '%newsletter%'))
   GROUP BY source_id;
   ```
2. 삭제:
   ```sql
   DELETE FROM articles WHERE source_id = 'bbc_sport';
   DELETE FROM articles WHERE source_id = 'football_london'
     AND (LOWER(title_original) LIKE '%sent to your inbox%'
          OR LOWER(title_original) LIKE '%newsletter%');
   ```
3. 재수집 · 서빙 재생성:
   ```bash
   uv run python -m bullet_in.run
   ```
4. 검증:
   ```sql
   SELECT source_id, COUNT(*) FROM articles GROUP BY source_id;
   ```
   - bbc_sport: 깨끗한 제목의 main-content 기사만(소수).
   - football_london 뉴스레터: 0건.

## 주의
- **③ 이적무관 실제 기사(football.london 경기리포트 · 평점 · 킷 등)는 이번 정리 대상이 아니다(보존).**
  football.london DELETE 는 뉴스레터 패턴으로 한정한다.
- bbc_sport 전건 삭제는 현재 페이지 밖 과거 기사 유실을 수반한다(대부분 쓰레기라 수용).
- 3단계 `run` 은 전체 소스 재수집 + 신규 enrich(Gemini) 를 트리거한다. 무료 티어 429 시
  남은 건은 다음 사이클 누적(정상 동작).
