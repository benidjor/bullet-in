# 배포 후 라이브 확인에서 만난 오진 함정 2건 — 308 리다이렉트 · 스냅샷 표

2026-08-07 진행 단계 사다리 배포 (#230 · #231) 직후 라이브 확인 중에 겪었다.
둘 다 실제 화면은 정상인데 확인 방법이 틀려서 "배포가 잘못됐다" 는 결론으로 갈 뻔했다.

## 1. 함정 1 — curl 이 0바이트를 준다고 배포 실패가 아니다

### 1.1. 증상

배포 직후 `curl -s https://bullet-in.pages.dev/player/trossard.html` 이 빈 응답을 줬다.
같은 URL 을 브라우저로 열면 정상이다.
grep 기반 확인이 전부 0 건으로 나와 "구판이 배포됐다 · 페이지가 사라졌다" 로 읽히기 쉽다.

### 1.2. 원인

Cloudflare Pages 가 `.html` 경로를 클린 URL 로 308 리다이렉트한다 (`/player/trossard.html` → `/player/trossard`).
308 응답에는 본문이 없고, `curl` 은 기본으로 리다이렉트를 따라가지 않는다.

### 1.3. 조치

라이브 확인 `curl` 에는 항상 `-L` 을 붙인다.

```bash
curl -sL https://bullet-in.pages.dev/player/trossard.html | grep -c tlnode   # 5 가 나와야 정상
```

기존 함정 "소프트 404 는 200 을 준다" 와 성격이 같다.
상태 코드만 봐도 틀리고 (404 인데 200) 본문만 봐도 틀린다 (정상인데 0바이트) — 둘 다 `-L` 을 붙인 뒤 내용으로 판정한다.

## 2. 함정 2 — 스냅샷 실측표를 라이브 기대값으로 쓰면 데이터가 바뀐 것을 결함으로 오진한다

### 2.1. 증상

사다리 스펙 §6.2 는 색인 배지의 기대값을 다섯 명 분량으로 표에 적어 두었다 (2026-08-05 운영 사본 실측).
배포 후 라이브에서 두 명이 표와 달랐다 — 기마랑이스 `관심` → `이적 합의` · 알바레스 `루머` → `관심`.
표와 다르니 "배지 계산 구현이 틀렸다" 고 의심하기 쉽다.

### 2.2. 원인

표의 기준은 08-05 사본이고 라이브는 그 뒤 회차가 돌면서 기사가 늘었다 (526 → 569행).
배지의 정의는 "시간축 최신 기사의 귀속 단계" 라서 새 기사가 들어오면 값이 바뀌는 것이 정상이다.
DB 를 조회해 확인했다 — 기마랑이스는 08-06 `agreed` 기사 (등번호 39번 배정), 알바레스는 08-05 저녁 `interest` 기사가 시간축 최신이었다.

### 2.3. 조치 — 검증을 두 단계로 가른다

- **구현 검증은 스냅샷으로** — 표를 만든 그 사본 (`bulletin_mock`) 으로 렌더하면 표와 모든 항목이 일치해야 한다.
안 맞으면 구현이 틀린 것이다.
- **라이브 검증은 정의로** — 표가 아니라 "시간축 최신 귀속 단계와 배지가 같은가" 를 DB 조회로 확인한다.

```sql
-- 배지 기대값 = 이 조회의 첫 행 stage (is_displayable 한 것 중 최신)
SELECT a.published_at, ap.stage, LEFT(a.title_ko, 44)
FROM article_players ap
JOIN players p ON p.id = ap.player_id
JOIN articles a ON a.content_hash = ap.content_hash
WHERE p.full_name LIKE '%Guimar%' AND ap.stage IS NOT NULL AND ap.stage <> 'other'
ORDER BY a.published_at DESC LIMIT 3;
```

### 2.4. 교훈

실측표에는 측정 시점의 데이터 상태가 함께 담겨 있다.
표를 옮겨 쓸 때는 "이 값은 어느 시점 데이터인가" 를 같이 옮기고 라이브 대조에는 값이 아니라 정의를 쓴다.

## 3. 참조

- 사다리 스펙 (§4.4 · §6.2 실측표): `docs/superpowers/specs/2026-08-05-serve-player-progress-ladder-design.md`
- 소프트 404 함정 포함 VM 운영 함정 모음: `docs/troubleshooting/2026-08-04-called-design-a-defect-without-reading-it.md` 계열 · 세션 메모리 vm-manual-ops-gotchas
