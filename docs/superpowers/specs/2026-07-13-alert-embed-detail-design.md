# 알림 embed 디테일 강화 설계 (2026-07-13)

SLO-5 (신선도) · SLO-6 (수집량 이상) Discord embed 를 진단 가능한 알림으로 재설계.
첫 실발송 검증 (2026-07-13) 에서 확인된 정보 부족을 해소한다 — before: `docs/assets/discord-alert-embed-before.png`.

## 1. 배경 · 문제

- **정보 부족** — 현재 embed 는 소스 · 수치 한 줄뿐이라, 받은 사람이 원인 추정 · 조치를 시작할 컨텍스트가 없음.
- **가용 데이터 미사용** — 마지막 수집 시각 · 소스 표시명 · 어댑터 종류 · 최근 회차 수집량 · run_id 가 호출부 스코프에 이미 있으나 버려짐.
- **Discord 기능 미사용** — 필드 그리드 · `timestamp` · `<t:...:R>` 상대시간 · 제목 URL 링크를 안 씀.

## 2. 목표 · 비목표

- **목표** — 알림만 보고 ① 원인 후보를 떠올리고 ② 심각도 (전체 중 몇 개) 를 파악하고 ③ 런북으로 바로 이동할 수 있게 한다.
- **목표** — before / after 캡처를 `docs/assets/` 에 남겨 PR §4 검증 · 런북에 사용.
- **비목표** — 판정 · 적재 로직 무변경 (`evaluate_freshness` · `volume_anomalies` · storage · schema · config).
  표시 계층 (notify.py 빌더) 과 run.py 호출 인자만 손댄다.
- **비목표** — 알림 채널 추가 · 멘션 (@here) · 버튼 등 Discord 고급 기능 없음 (YAGNI).

## 3. 공통 배관 (notify.py)

### 3.1. send_alert 확장 (하위 호환)

- 선택 인자 3개 추가 — 기존 호출부 (Airflow 콜백 포함) 무변경.

```python
def send_alert(title, description, *, color,
               fields=None, url=None, timestamp=None, footer=None) -> None:
    # url: embed["url"] (제목 클릭 링크)
    # timestamp: ISO 8601 문자열 → embed["timestamp"] (Discord 가 로컬 시간 표시)
    # footer: 문자열 → embed["footer"] = {"text": footer}
```

### 3.2. 원인 후보 매핑 · 링크 상수

- **어댑터 → 힌트** — 진단표 (freshness 런북 §대응) 의 요약. 미지 어댑터는 힌트 줄 생략 (오정보 방지).

```python
ADAPTER_HINTS = {
    "x_playwright": "X 쿠키 만료 · 핸들 변경",
    "x_backtrack": "X 쿠키 만료 · 핸들 변경",
    "html": "셀렉터 드리프트 · 사이트 개편",
    "playwright": "셀렉터 · 동의창 드리프트",
    "rss": "피드 URL 변경",
    "fmkorea": "검색 URL 변경 · 429 차단",
}
RUNBOOK_FRESHNESS = "https://github.com/benidjor/bullet-in/blob/main/docs/runbook/2026-07-13-freshness-watermark-ops.md"
RUNBOOK_ANOMALY = "https://github.com/benidjor/bullet-in/blob/main/docs/runbook/2026-07-13-collection-alerts-ops.md"
```

### 3.3. 시각 헬퍼

- **`<t:epoch:스타일>` 마크업** — Discord 가 보는 사람의 로컬 · 상대시간으로 렌더링.
- naive UTC datetime 을 epoch 으로 바꿀 때 `timezone.utc` 를 명시해 UTC 계약 (SLO-5 fix) 과 정합 유지.

```python
def _discord_ts(dt: datetime, style: str) -> str:
    # naive UTC → "<t:1752190200:R>" (R=상대, f=절대)
    return f"<t:{int(dt.replace(tzinfo=timezone.utc).timestamp())}:{style}>"
```

## 4. SLO-5 신선도 embed

### 4.1. 시그니처

```python
def build_freshness_alert(records, default_hours, *,
                          sources, run_id, checked_at) -> dict:
    # records: 전체 SourceFreshness 목록 (조망 요약용 · stale 필터는 내부에서)
    # sources: load_sources() 반환 dict (display_name · adapter)
```

- 발송 조건 (stale 있을 때만) 은 지금처럼 run.py 가 판단.
- 기존 시그니처 (`breaches, default_hours`) 는 호출부가 run.py 하나라 브레이크 허용 · 테스트 갱신.

### 4.2. 구성

```
🕰️ 신선도 경고 — 오래된 소스 1건          ← title (url = freshness 런북)
감시 5소스: stale 1 · 정상 3 · 워터마크 없음 1   ← description

[afcstuff (aggregator) (x_afcstuff)]        ← stale 소스당 field (inline=False)
- ⏳ 61.4h 경과 (임계 24h)
- 마지막 수집: 2일 전 (2026년 7월 11일 오전 1:30)   ← <t:..:R> (<t:..:f>)
- 원인 후보: X 쿠키 만료 · 핸들 변경

[기본 임계]  [회차]                          ← 공통 field (inline=True)
전역 48h    run 3f2a9c12                    ← run_id 앞 8자

footer: bullet-in · timestamp: checked_at (UTC ISO)
```

- **조망 카운트** — stale N = `stale=True` · 워터마크 없음 W = `last_fetched_at is None` · 정상 = 전체 − N − W.
- **field name** — `display_name (source_id)` · display_name 없으면 source_id 만.
- **timestamp** — `checked_at` (DB UTC) 을 ISO 로. 발송 시각과 다를 수 있는 실측 시각이라 의미 있음.

## 5. SLO-6 수집량 embed

### 5.1. 시그니처

```python
def build_anomaly_alert(anomalies, history_count, *,
                        hist, sources, run_id) -> dict:
    # hist: run.py 가 이미 조회한 최근 12회 source_counts (최신순 list[dict])
```

### 5.2. 구성

```
⚠️ 수집량 이상 — 1건 (드롭 1 · 스파이크 0)   ← title (url = anomaly 런북)
최근 12회 대비 소스별 수집량 이상            ← description

[fmkorea 축구 소식통 (fmkorea)]             ← 이상 소스당 field (inline=False)
- ▼ 0건 (평소 ~14)
- 최근: 15 → 13 → 14 → (오늘) 0             ← 직전 5회 (오래된 것부터) + 오늘
- 원인 후보: 검색 URL 변경 · 429 차단

[회차] 최근 12회 기준 · run 3f2a9c12         ← 공통 field
```

- **시퀀스** — `hist[:5]` 를 뒤집어 (오래 → 최신) 나열 + `(오늘) {today}`. 이력이 5회 미만이면 있는 만큼.
- **원인 후보** — 드롭 = `ADAPTER_HINTS` · 스파이크 = "중복 유입 · 파싱 회귀 의심" 고정 문구.
- **timestamp 없음** — 메시지 자체 시각으로 충분 (SLO-5 와 달리 별도 실측 시각이 없음).

## 6. run.py 연결

- 신규 조회 없음 — 이미 스코프에 있는 값의 전달만 추가.

```python
anomalies = volume_anomalies(stats["source_counts"], hist)
if anomalies:
    notify.send_alert(**notify.build_anomaly_alert(
        anomalies, len(hist), hist=hist, sources=sources, run_id=run_id))
...
if breaches:  # 기존 조건 유지 · records 전체 전달
    notify.send_alert(**notify.build_freshness_alert(
        records, default_hours, sources=sources, run_id=run_id,
        checked_at=checked_at))
```

## 7. 엣지 케이스

- **display_name 없음** — `source_id` 로 폴백 (x_afcstuff 는 display_name 있음 · 방어용).
- **미지 어댑터** — 원인 후보 줄 자체를 생략.
- **워터마크 없음 소스** — 필드 없이 description 카운트에만 반영.
- **이상 소스가 hist 에 없음** — 시퀀스 줄 생략 (today 만 있는 신규 소스).
- **필드 25개 제한** — 소스 약 15개라 여유 · 가드 없음 (YAGNI).
- **field value 1024자** — 소스당 3줄 고정이라 여유.

## 8. 테스트 계획

- **send_alert 하위 호환** — url · timestamp · footer 없이 호출 시 기존 embed 와 동일 (기존 테스트 유지 확인).
- **send_alert 확장** — 3개 인자가 embed 의 url · timestamp · footer.text 로 매핑.
- **build_freshness_alert** — 조망 카운트 (stale · 정상 · 워터마크 없음) · 소스당 필드 구조 · `<t:` 마크업 (epoch 값 검증) · 원인 후보 (매핑 · 미지 어댑터 생략 · display_name 폴백) · title url · footer · timestamp.
- **build_anomaly_alert** — 시퀀스 포맷 (5회 + 오늘 · 짧은 이력 · hist 에 없는 소스) · 드롭 / 스파이크 원인 후보 분기 · 제목 건수 집계.
- **기존 테스트 갱신** — 두 빌더의 구 형식 단언을 새 형식으로 교체.

## 9. 산출물

- **코드** — notify.py (send_alert 확장 · 상수 · 헬퍼 · 빌더 2개 개편) · run.py (호출 인자).
- **테스트** — §8.
- **이미지** — `docs/assets/discord-alert-embed-before.png` (커밋됨) + 구현 후 스모크 발송 캡처 `discord-alert-embed-after.png` (사용자 캡처 필요).
- **런북 갱신** — freshness · collection-alerts 런북의 "알림 해석" 에 after 이미지 링크 + 새 항목 (원인 후보 · 조망 · 시퀀스) 설명 반영.
- **PR §4** — before / after 이미지 나란히 + 스모크 발송 로그.

## 10. 브랜치 전략

- 이 트랙은 SLO-5 코드 (PR #36) 에 의존 → `feat/alert-embed-detail` 을 #36 브랜치 위에 스택으로 시작.
- **#36 squash merge 후 · 구현 PR 오픈 전** — `git rebase --onto origin/main a595ab7 feat/alert-embed-detail` 로 기반 정리 (squash 중복 커밋 함정 대응).
