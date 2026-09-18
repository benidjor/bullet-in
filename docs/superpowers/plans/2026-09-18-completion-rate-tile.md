# 완주율 타일 구현 계획

**Goal:** 수집 현황 화면 (`ops.html`) 에 「완주율 · 07-20 이후」 타일을 둔다.

**Architecture:** 매시 도는 `bullet_in.airflow_watch` 가 저널과 Airflow 실행 목록을 세어 `state/completion.json` 을 쓰고, 회차의 `publish` 태스크 (`write_ops`) 가 그 파일을 읽어 타일을 그린다.
새 표 · 새 유닛 · 새 태스크는 없다.

**Spec:** `docs/superpowers/specs/2026-09-18-completion-rate-tile-design.md`.

## Global Constraints

- 셈은 스펙 §1 그대로다. 진행 중 실행은 분모에서 뺀다.
- 파일이 없거나 분모가 0 이면 타일은 「—」 다. 빈 칸끼리 나누지 않는다.
- `docs/` 문서는 서식 훅을 통과해야 한다.
- 테스트 이름은 그 파일의 관례를 따른다 (`test_airflow_watch.py` 는 영어 · `test_ops_view.py` · `test_serve_ops.py` 는 한국어).
- 파이썬 환경 · 워크트리 · 브랜치 규율은 메모리 `standing-session-rules` 그대로다.

## Task 1 · 셈 함수 (`airflow_watch.py`)

- [ ] `journal_counts(text) -> dict` — 「Starting」 · 「Finished」 · 「Failed with result」 줄 수.
- [ ] `airflow_counts(list_runs_json) -> dict` — success · failed · in_progress · started (success + failed) · first_start · last_end.
- [ ] `completion(journal, airflow) -> tuple[int, int]` — (완주, 시작).
- [ ] 테스트: 진행 중 제외 · failed 포함 · manual 포함 · structlog 앞줄 무시 · 빈 목록.

## Task 2 · 감시가 파일을 쓴다 (`airflow_watch.main`)

- [ ] `_journal()` 서브프로세스 (`journalctl -u bullet-in.service --no-pager -q -o short-iso`).
- [ ] `COMPLETION_PATH = Path("state/completion.json")` · list-runs 성공일 때만 쓴다 · journalctl 실패면 이전 파일의 `journal` 블록 유지 + 경고.
- [ ] 테스트: 정상 경로에 파일이 생기고 값이 맞다 · journalctl 실패에 이전 값 유지 · list-runs 실패에 파일 무변경.

## Task 3 · 뷰모델 타일 (`serve/ops_view.py` · `serve/render.py`)

- [ ] `build_ops_view(..., completion: dict | None = None)` — `_tiles` 에 타일 추가 (Success Rate 오른쪽) · Success Rate 보조 줄 「소스 단위 · SLO-2 목표 99%」.
- [ ] `write_ops(..., completion_path=None)` — JSON 을 읽어 넘긴다 (없으면 None) · `run.py` 호출부에 `completion_path="state/completion.json"`.
- [ ] 템플릿: 타일이 일곱이면 `tiles seven` 클래스 · `_dash.html.j2` 에 `.tiles.seven{grid-template-columns:repeat(7,1fr)}`.
- [ ] 테스트: 파일 있음 (값 · 보조 줄) · 없음 (「—」) · 분모 0 · 렌더에 7열 클래스.

## Task 4 · 문서

- [ ] README 는 이 PR 에서 손대지 않는다 (PR #485 가 같은 문단을 고치는 중이라 충돌을 피한다 · 머지 뒤 별도 한 줄).
- [ ] 런북 `docs/runbook/2026-09-04-running-the-cycle-under-airflow.md` 에 「완주율 타일이 「—」 이면」 한 절 (감시 타이머 · `state/completion.json`).

## 검증

- [ ] `uv run --project . --extra dev pytest -q` 전체 통과 · 수집 수 기준선 대비 증가분 기록.
- [ ] 머지 뒤: 감시 타이머 한 번 (`sudo systemctl start bullet-in-airflow-watch.service`) → `state/completion.json` 확인 → 다음 회차 `ops.html` 타일 값이 손 셈과 같은지.
