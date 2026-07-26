# 재현 하네스가 프로덕션 로더와 다르면 가짜 원인을 쫓는다

2026-07-25 필터 버튼 버그 (#133) 진단 중, 디버깅용 재현 스크립트가 프로덕션과 다른 방식으로 설정을 읽어
실재하지 않는 결함을 원인 후보로 한동안 추적했다.
문서 스니펫 드리프트 (2026-07-19 runbook-snippet-logic-drift) 와 같은 뿌리의 함정이 디버깅 하네스에서 재발한 사례.

## 증상 (가짜)

- 로컬 재현 렌더에서 사이드바 소스 facet 이 "Sky Sports" 와 "skysports" 두 항목으로 분열.
- 카드의 언론사 표시도 원시 source_id (bbc_sport · skysports) 그대로 노출.
- 이를 "outlet 어휘 분열" 이라는 원인 후보로 세우고 추적을 시작함.

## 실제 원인 — 하네스의 로더 불일치

- 재현 스크립트가 `config/sources.yaml` 을 `yaml.safe_load` 로 직접 읽어 **리스트 구조 그대로** `write_site` 에 넘김.
- 프로덕션 (`run.py`) 은 `score.load_sources()` 로 **source_id 키 dict** 로 변환해서 넘긴다.
- 렌더의 `sources.get(row["source_id"])` 가 리스트 구조에서는 항상 빈 값
→ outlet 폴백이 전부 실패해 원시 source_id 가 노출된 것.

## 발각 경로

- 라이브 사이트 (bullet-in.pages.dev) 의 facet 어휘를 curl 로 대조하니 분열이 없었음
→ 재현 환경만의 현상 = 하네스 결함으로 판정.
- 로더를 `load_sources()` 로 교체하자 가짜 증상이 사라지고, 진짜 원인 (필터 DOM 도달 공백) 만 남았다.

## 교훈 · 예방

- **재현 하네스는 앱의 로더 · 상수를 import 한다** — 옮겨 적거나 직접 파싱하지 않는다.
`SERVING_SELECT_SQL` (run.py) · `load_sources` (score.py) · `write_site` 인자 구성을 그대로 가져다 쓴다.
- 재현 결과가 라이브와 다르게 보이면, 원인 추적 전에 **하네스 자체를 라이브와 대조**한다 (공개 페이지 curl 이면 충분).
- 재현할 때는 런북 `2026-07-26-local-serve-render-verification.md` 의 표준 스크립트를 쓴다.

## 관련

- `docs/troubleshooting/2026-07-19-runbook-snippet-logic-drift.md` — 같은 원리 (스니펫에 로직을 옮겨 적으면 어긋난다) 의 문서판.
- PR #133 — 이 진단이 도달한 진짜 원인 (필터가 대표 카드만 토글) 의 수정.
