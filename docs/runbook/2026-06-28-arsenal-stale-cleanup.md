# 런북 — arsenal 과거(비-영입) 데이터 정리

arsenal_official이 "영입(sign) 전용 고정밀 소스"로 재정의되기 전 적재된 비-영입 기사
(여자팀·잡다, 약 31건)가 `articles`·서빙 페이지에 잔존한다. 일회성으로 정리한다.
**실행은 라이브 MariaDB가 떠 있는 상태에서 직접 수행한다.**

## 절차
1. DB 접속 준비:
   ```bash
   set -a; source .env; set +a
   docker compose ps   # mariadb running 확인
   ```
2. 대상 수 확인(삭제 전 반드시):
   ```sql
   SELECT COUNT(*) FROM articles
   WHERE source_id = 'arsenal_official'
     AND LOWER(title_original) NOT LIKE '%sign%'
     AND (title_ko IS NULL OR LOWER(title_ko) NOT LIKE '%sign%');
   ```
3. 삭제:
   ```sql
   DELETE FROM articles
   WHERE source_id = 'arsenal_official'
     AND LOWER(title_original) NOT LIKE '%sign%'
     AND (title_ko IS NULL OR LOWER(title_ko) NOT LIKE '%sign%');
   ```
4. 서빙 페이지 재생성: 다음 파이프라인 실행(`uv run python -m bullet_in.run`)이
   `articles` 기준으로 `site/index.html`을 다시 쓴다.

## 주의
- 2단계 COUNT 결과가 예상(약 31건)과 크게 다르면 멈추고 기준을 재검토한다.
- 'sign' substring 기준이라 'design'·'resign' 등은 보존될 수 있다(현 'sign' 필터와 동일 기준이라 일관).
