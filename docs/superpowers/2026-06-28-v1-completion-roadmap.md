# Bullet-in v1 완성 로드맵 (2026-06-28)

초기 설계 (`specs/2026-05-27-bullet-in-design.md`) §4 · §8 · §10 · §15를 현재 코드와 대조한 갭 분석을 바탕으로,
"완성까지 남은 작업"을 우선순위로 정리한 문서.

## 완성 기준
- **완성 = v1 필수 기능 + SLO 달성** (초기 설계 §13의 v1 + §10 SLO).
- **Stretch는 완성 범위에서 제외** (교차 corroboration · 역번역 정확도 검증 · 대시보드 · AWS 등) — 별도 항목으로만 기록.
- 신규 사용자 요구 (기사 상세 페이지 · 전체 본문 번역 · 3줄 요약 · 웹 UI 개편)는 이 완성 범위에 **추가**한다.

## 방법
- 이 문서는 **방향과 우선순위**만 정한다. 각 항목은 착수 시점에 brainstorming → spec → plan → 실행 (SDD)으로 상세화한다.
- 한 항목 = 한 기능/트랙 = (원칙적으로) 한 PR.

---

## 갭 분석 요약 (2026-06-28)

### 이미 구현됨 (작업 불필요)
- asyncio 병렬 수집, 단일 어댑터 인터페이스, dedup (content_hash + URL 정규화 + MariaDB UNIQUE),
  revision 변경 감지, 공신력 스코어링 (tier 외부화 · confidence), LLM enrich (신규만 · 멱등 · ko/en 경로 분리),
  Airflow 3.x DAG · 마이그레이션, dbt unique/not_null 테스트, 일일 성공률 SLO, dbt-duckdb의 MariaDB attach PoC.

### 미구현 / 부분 (완성까지 남은 갭)
| 항목 | 상태 | 근거 |
|---|---|---|
| 신선도 (SLO-5) · 증분 워터마크 | 미구현 | dbt에 `sources:`/freshness 블록 없음, 워터마크 테이블 없음 (전량 수집 + dedup만) |
| 수집량 이상 탐지 + 알림 (SLO-6) | 부분 | `volume_anomaly()` 구현 · 테스트됐으나 run.py 미연결, 알림 (Slack/메일/webhook) 전무 |
| 수집 현황 모니터링 뷰 (§4) | 미구현 | 기사 페이지만 존재, dbt 마트 `tier_distribution` · `slo_rollup` 없음 |
| 병렬화 시간 단축 ~70% 실측 (SLO-1) | 부분 | `benchmark()`/`speedup_pct()` 코드는 있으나 호출 · 기록 없음, README SLO 공란 |
| `dup_count` 하드코딩 0 (run.py) | 버그 | 중복률 SLO 측정 데이터 오염 |
| 비활성 소스 — goal (Playwright JS) · x_afcstuff (ITK X) | 비활성 | v1 필수 소스 다양성 (JS 1+ / ITK X 1~2) 미충족 |

### 신규 사용자 요구 (현재 전무)
- 기사 상세 페이지 (헤드라인 클릭 → 상단 3줄 요약 + 하단 전체 번역 본문 + 출처): 상세 템플릿 · 라우팅 없음.
- 전체 기사 본문 번역: EN 소스 본문 미수집 · 미번역.
- 3줄 요약: 현재 1문장 `summary_ko`.
- 웹 UI 디자인: CSS · JS 없는 단순 HTML.

---

## 우선순위 (Tier)

### Tier 1 — 빠른 교정 · 미션 직결 (작음, 차단 없음)
1. **arsenal 기존 31건 데이터 정리** — 영입 전용 소스로 재정의 전의 여자팀/잡다 기사가 DB · 서빙 페이지에 남아 노출 중. 정리.
2. **`dup_count` 버그 수정** — run.py가 항상 0으로 기록 → 중복률 SLO 근거 오염. 실제 중복 수 집계.
3. **이적 키워드 필터** — BBC · football.london이 아스날 일반 뉴스를 전부 수집 → 이적 (transfer · sign · deal · loan 등)만 통과. `HtmlAdapter.title_contains` 패턴 재사용.

### Tier 2 — 신규 UX 기능 (사용자 핵심 요구, 큰 수직 기능)
4. **전체 본문 번역 + 3줄 요약 + 기사 상세 페이지 + 웹 UI 개편** — 한 덩어리 기능:
   - EN 소스 본문 (body) 수집 (어댑터) → 본문 번역 필드 · 3줄 요약 프롬프트 (enrich) → 상세 페이지 · 라우팅 · 디자인 (serve).
   - 규모 큼 → 착수 시 별도 brainstorming/spec로 데이터 모델 · 서빙 방식 확정.

### Tier 3 — v1/SLO 완성 (설계 약속 잔여)
5. **신선도 (dbt freshness) + 증분 워터마크** (SLO-5).
6. **수집량 이상 탐지 연결 + 알림** (SLO-6) — `volume_anomaly()`를 run.py에 연결, 알림 채널 추가.
7. **수집 현황 모니터링 뷰 + dbt 마트** (tier_distribution · slo_rollup) (§4).
8. **병렬화 ~70% 실측 · 기록** (SLO-1) + README SLO 표 채우기.

### Tier 4 — 소스 다양성 복구 (v1 필수)
9. **x_afcstuff (ITK X) 복구** — ⚠️ 사용자가 버너 X 계정 자격증명 (.env `REPLACE`) 입력 선행 필요.
10. **goal (Playwright) 복구** — 셀렉터/동의창 드리프트 대응.

### Tier 5 — 폴리시
11. 요약 말투 미세조정 ('합니다체' 잔존).
12. 캡처 2건 · README · SLO 문서 갱신.

---

## Stretch (완성 범위 제외, 향후)
- 교차 corroboration 스코어링 (다수 소스 보도 시 신뢰도↑)
- 번역/요약 정확도 역번역 스팟체크
- 삭제 감지 (현재 revision은 변경만), LLM 출력 스키마 검증 강화 (pydantic)
- 모니터링 대시보드 고도화, 소스 추가, AWS 배포

## 참조
- 초기 설계: `docs/superpowers/specs/2026-05-27-bullet-in-design.md` (§4 · §8 · §10 · §13 · §15)
- 직전 완료: PR #6 (라이브 e2e 부트스트랩), PR #7 (fmkorea 퍼가기 금지 정책)
- 상태 스냅샷: 메모리 `bullet-in-status`
