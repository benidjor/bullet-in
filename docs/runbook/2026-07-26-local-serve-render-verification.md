# 로컬 serve 렌더 검증 루프

serve/ (render.py · 템플릿 · app.js · style.css) 변경을 VM 접촉 없이 로컬에서 검증하는 절차.
필터 도달 수정 (#133) 과 탐색 확장 (#138) 검증에서 실제로 쓴 루프를 표준화한다.
재현 스크립트가 세션 임시 폴더에만 있어 재부팅마다 사라지던 것을 여기로 고정한다.

## 전제

- docker compose 의 mariadb 가 떠 있고 로컬 `bulletin` DB 에 기사 행이 있음.
- 행이 없거나 낡았으면 VM 덤프 적재 절차는 `docs/runbook/2026-07-22-mockup-rerender-from-vm.md` 참조
  (별도 DB 를 쓸 경우 아래 접속 URL 만 바꾸면 됨).

## 1. 렌더 스크립트

임시 폴더에 아래를 저장한다 (예: `/tmp/render_local.py`).
**앱의 로더 · 상수를 import 하는 것이 핵심** — 옮겨 적으면 하네스가 프로덕션과 어긋나 가짜 원인을 만든다
(`docs/troubleshooting/2026-07-26-repro-harness-loader-mismatch.md`).
players 이관 (`migrate_roster`) 이 안 된 DB 로 렌더하면 사건 묶음이 조용히 꺼진다 — 먼저 이관 여부를 확인한다.

```python
"""로컬 bulletin DB → write_site 재현 렌더 (run.py 렌더 블록과 동일 인자)."""
import os
import sys

os.environ.setdefault("MARIADB_URL", "mysql+pymysql://root:bulletin@localhost:3306/bulletin")

REPO = "<저장소 루트 절대 경로>"
sys.path.insert(0, f"{REPO}/src")
os.chdir(REPO)                       # config/*.yaml 상대 경로 때문에 필요

from sqlalchemy import create_engine, text
from bullet_in.run import SERVING_SELECT_SQL
from bullet_in.score import load_sources
from bullet_in.serve.render import write_site
from bullet_in.credibility import load_registry, journalist_directory, outlet_directory

engine = create_engine("mysql+pymysql://root:bulletin@localhost:3306/bulletin")
with engine.connect() as c:
    rows = [dict(r) for r in c.execute(text(SERVING_SELECT_SQL)).mappings().all()]

sources = load_sources("config/sources.yaml")
registry = load_registry("config/credibility.yaml")

out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/bullet-in-site"
write_site(rows, sources, out,
           directory=journalist_directory("config/credibility.yaml"),
           registry=registry,
           outlet_dir=outlet_directory("config/credibility.yaml"))
print(f"rendered {len(rows)} rows -> {out}")
```

```bash
uv run python /tmp/render_local.py            # 워크트리에서 실행하면 그 워크트리의 serve 코드로 렌더됨
```

## 2. 서빙 · 브라우저 확인

```bash
cd /tmp/bullet-in-site && python3 -m http.server 8931   # 아무 빈 포트
```

- 브라우저에서 `http://localhost:8931/index.html` 과 `all.html` 을 연다.
- **캐시 주의**: 로컬 정적 서버는 캐시 헤더가 없어 CSS · JS 변경이 안 보이면 하드 리로드
  (`docs/troubleshooting/2026-07-23-css-cache-stale.md` 계열의 로컬판).

## 3. 확인 포인트 (변경 부위에 맞춰 선별)

- 필터: 소스 · 공신력 · 단계 · 검색어 각각 걸고 상태줄 건수가 사이드바 건수와 일치하는지
  (#133 이후 기사 단위 — 루머 등 단계 건수는 정확히 일치해야 함).
- 더보기 · 접기: 초기 컷 → 7일씩 펼침 → "접기" 라벨 전환 → 초기 복귀 · 필터 후 초기화 시 버튼 복원.
- 초기 화면 원상: 밴드 표시 · 재출현 카드 (.dupcard) 비노출 · 관련 보도 접힘.
- 테마: 라이트 · 다크 전환 (배지 · 테두리 색 변수 확인).
- JS 콘솔 에러 0 (개발자 도구).

## 함정

- 하네스 로더 불일치 — 위 트러블슈팅 참조. 스크립트를 수정할 때도 import 원칙 유지.
- 이 프로젝트는 dotenv 미사용 — DB URL 등을 환경변수로 바꿔 쓰려면 셸 export 필요.
- 로컬 DB 는 스냅샷이라 라이브와 건수가 다르다 — 건수 비교는 로컬 기준으로 닫아서 할 것
  (전후 비교는 같은 DB 상태에서).
