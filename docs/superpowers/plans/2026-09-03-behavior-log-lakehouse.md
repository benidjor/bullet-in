# 행동 기록 레이크하우스 구현 계획 (2026-09-03)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 구글 애널리틱스에만 쌓이던 방문자 행동 기록을 우리 Iceberg 레이크하우스로 들여 원자료 · 평탄화 · 집계까지 잇고, 그 결과를 볼 수 있는 페이지 하나를 배포한다.

**Architecture:** 이미 도는 변경 이력 적재 타이머에 갈래를 하나 더한다.
`google-cloud-bigquery` 로 하루치 내보내기 테이블을 Arrow 로 받아 `behavior.ga4_events` 에 그대로 넣고, 같은 회차 안에서 평탄화해 `behavior.ga4_events_flat` 을 만들고, 거기서 `behavior.fact_card_click` 과 `behavior.dim_date` 를 세운다.
집계 결과는 작은 JSON 으로 떨어뜨리고 회차의 렌더가 그것을 읽어 `site/behavior.html` 을 그린다.

**Tech Stack:** Python 3.11 · uv · google-cloud-bigquery · PyIceberg 0.11.1 · PyArrow · Jinja2 · Google Lakehouse Iceberg REST 카탈로그 · GCS

**Spec:** `docs/superpowers/specs/2026-09-02-behavior-log-bronze-design.md`

## Global Constraints

- Python 3.11 · 의존 추가는 `pyproject.toml` 의 `dependencies` 에 넣는다.
- 이 프로젝트는 dotenv 를 쓰지 않는다.
  설정은 환경변수로 받고 systemd 는 `EnvironmentFile` 로 준다.
- 기존 `dbt/models/gold/` 3모델과 `src/bullet_in/run.py` 의 수집 · 정제 흐름은 한 글자도 건드리지 않는다.
- `warehouse.py` 는 회차 안에서 돌지 않는다.
  게이트가 배포를 막는 자리라 그 위에 네트워크와 인증을 더 얹지 않는다 (모듈 첫 주석).
- 테스트 함수 이름은 한국어로 쓴다 (`tests/test_warehouse.py` 관례).
- 순수 판정 함수와 부수효과 함수를 파일 안에서 절로 나눈다 (`src/bullet_in/warehouse.py` 관례).
- 관리형 Iceberg 테이블을 만들지 않는다.
  `BigLake Table Management` SKU 가 시간당 165.99 KRW 다.
- `google-cloud-bigquery-storage` 는 넣지 않는다.
  REST 경로로 중첩까지 받는 것을 2026-09-02 에 확인했다.
- 표면 (`card_surface`) 값의 목록을 코드에 박지 않는다.
  행동 기록은 과거 배포본의 흔적을 담아 지금 화면에 없는 값이 들어 있다 (스펙 §1.4).
- 새 유닛을 만들지 않는다.
  이미 도는 `bullet-in-warehouse.timer` 에 얹는다.
- 커밋 메시지는 `docs/conventions/2026-06-11-commit-pr-convention.md` 를 따른다.

---

## 스펙이 열어 둔 결정 셋을 여기서 가른다

스펙은 세 가지를 「구현 계획에서 정한다」 로 남겨 두었다.
코드를 쓰기 전에 셋을 정한다.

### 결정 1 — 집계는 파이썬으로 만든다

스펙 §3.5 가 파이썬과 DuckDB 를 두고 「게이트에 위험을 더하지 않는 것」 을 기준으로 남겨 두었다.

DuckDB 로 Iceberg 를 읽으려면 `iceberg` 확장을 받아야 하고 REST 카탈로그 자격을 DuckDB 쪽에도 붙여야 한다.
게이트가 쓰는 DuckDB 와 같은 프로세스는 아니지만, 같은 저장소 안에서 DuckDB 를 쓰는 자리가 둘이 되고 확장 내려받기라는 새 실패면이 생긴다.
안건 2ν 가 열려 있는 동안에는 그쪽을 늘리지 않는다.

파이썬으로 하면 새 의존이 0이다.
PyIceberg 가 이미 Arrow 로 돌려주고, 하루 821행 · 전체 13,035행이라 `collections.Counter` 로 세는 것으로 끝난다.

### 결정 2 — 화면에는 집계 JSON 을 거쳐 값을 넘긴다

`warehouse.py` 의 첫 주석이 「회차 안에서 돌지 않는다」 이므로 렌더가 Iceberg 를 직접 읽으면 그 규율이 깨진다.
회차마다 카탈로그 인증과 GCS 왕복이 붙고, 그것이 실패하면 게이트 앞에서 회차가 흔들린다.

그래서 적재 타이머가 집계까지 마치고 `state/behavior_metrics.json` 을 쓴다.
회차의 렌더는 그 파일만 읽는다.
파일이 없으면 페이지를 안 그리고 넘어간다 — 첫 적재 전이나 적재가 실패한 뒤에도 회차는 그대로 끝난다.

### 결정 3 — `n_clicks` 는 팩트의 컬럼이 아니라 집계의 컬럼이다

팩트의 알갱이가 「클릭 한 건이 한 행」 이라 행마다 값이 1인 컬럼을 두는 것은 뜻이 없다.
스펙이 요구하는 것은 「표본이 적다는 사실이 결과에 늘 함께 보이는 것」 이므로, 집계를 내는 함수가 모든 행에 `n_clicks` 를 함께 낸다.

여기에 하나를 더 붙인다.
등급별 클릭 수만으로는 「등급이 높을수록 더 눌리는가」 에 답할 수 없다 — 등급이 높은 기사가 더 많이 실렸으면 클릭도 그냥 더 많다.
그래서 `mart_history.articles_snapshot` 에서 같은 축의 기사 수를 세어 기사당 클릭을 함께 낸다.
디멘션을 참조하는 이유가 이것이고, 화면에는 세 값 (클릭 · 기사 수 · 기사당 클릭) 이 나란히 선다.

---

## 파일 구조

| 파일 | 책임 |
| --- | --- |
| `src/bullet_in/warehouse.py` (수정) | 네임스페이스 매개변수화 · 적재 날짜 판정 · BigQuery 읽기 · 평탄화 · 팩트 · 집계 · CLI |
| `tests/test_warehouse.py` (수정) | 위의 순수 판정 부분 전량 |
| `src/bullet_in/serve/render.py` (수정) | `render_behavior` · `write_behavior` |
| `src/bullet_in/serve/templates/behavior.html.j2` (생성) | 행동 지표 페이지 |
| `tests/test_behavior_view.py` (생성) | 렌더 계약 |
| `src/bullet_in/run.py` (수정) | 회차 끝에서 `write_behavior` 호출 (실패 격리) |
| `pyproject.toml` (수정) | `google-cloud-bigquery` 의존 추가 |
| `.gitignore` (수정) | `state/` |
| `.env.example` (수정) | `GA4_DATASET` |
| `docs/runbook/2026-09-02-warehouse-history-load.md` (수정) | 행동 기록 갈래의 운영 절차 |

`warehouse.py` 가 530줄이고 이번에 250줄 안팎이 는다.
그래도 하나로 둔다 — 적재 대상마다 파일을 가르면 카탈로그 접속 · Arrow 변환 · 적재 시각 컬럼이 세 곳으로 흩어지고, 이 저장소는 `backup.py` 도 426줄에 세 기능과 CLI 를 담고 있다.

---

## Task 1: 검증하지 않은 셋에서 먼저 막힌다

스펙 §4.2 가 세 가지를 검증하지 않은 채로 남겼다.
셋 다 실패하면 뒤 태스크가 전부 헛일이 되므로 코드를 한 줄도 쓰기 전에 여기서 막힌다.

| 항목 | 왜 아직 모르나 |
| --- | --- |
| 서비스 계정으로 프로젝트를 건너 읽기 | 로컬 검증을 사용자 계정으로 했다 |
| 중첩 구조를 Iceberg 에 실제로 커밋하기 | 스키마 변환까지만 확인했고 쓰기는 안 해 봤다 |
| 스키마 진화 | 새 키가 나타나야 도는 경로다 |

**Files:**
- Modify: `docs/superpowers/specs/2026-09-02-behavior-log-bronze-design.md` (§6 위험표의 낡은 칸 하나)
- Modify: `docs/runbook/2026-08-24-wiring-analytics-and-proving-it-arrives.md` (검증 결과 절 추가)

**Interfaces:**
- Consumes: 없음
- Produces: 뒤 태스크가 기대는 사실 셋 — 서비스 계정이 읽는가 · 중첩이 커밋되는가 · `union_by_name` 으로 컬럼이 느는가

- [ ] **Step 1: 프로젝트를 건너 읽는 권한 둘을 붙인다**

```bash
gcloud projects add-iam-policy-binding bullet-in-analytics \
  --member=serviceAccount:bullet-in-lakehouse@bullet-in-lakehouse.iam.gserviceaccount.com \
  --role=roles/bigquery.dataViewer
```

```bash
gcloud projects add-iam-policy-binding bullet-in-analytics \
  --member=serviceAccount:bullet-in-lakehouse@bullet-in-lakehouse.iam.gserviceaccount.com \
  --role=roles/bigquery.jobUser
```

- [ ] **Step 2: 권한이 실제로 붙었는지 정책에서 확인한다**

```bash
gcloud projects get-iam-policy bullet-in-analytics \
  --flatten=bindings[].members \
  --filter=bindings.members:bullet-in-lakehouse@bullet-in-lakehouse.iam.gserviceaccount.com \
  --format='value(bindings.role)'
```

기대: `roles/bigquery.dataViewer` 와 `roles/bigquery.jobUser` 두 줄.
한 줄만 나오면 앞 단계가 반쯤 돌았다는 뜻이므로 없는 쪽을 다시 붙인다.

- [ ] **Step 3: 시험용 스크립트를 VM 에 두고 서비스 계정으로 읽어 본다**

VM 에만 서비스 계정 키가 있다.
로컬에서 도는 것은 사용자 계정이라 이 태스크가 재려는 것을 못 잰다.

`/tmp/probe_behavior.py` 로 VM 에 올린다 (저장소에 커밋하지 않는다).

```python
"""Task 1 — 서비스 계정 읽기 · 중첩 커밋 · 스키마 진화를 한 번에 확인한다."""
import os
import pyarrow as pa
from google.cloud import bigquery
from pyiceberg.catalog.rest import RestCatalog

DATASET = "bullet-in-analytics.analytics_551139164"

catalog = RestCatalog("bullet_in", **{
    "uri": os.environ["ICEBERG_CATALOG_URI"],
    "warehouse": os.environ["ICEBERG_WAREHOUSE"],
    "auth": {"type": "google",
             "google": {"scopes": ["https://www.googleapis.com/auth/cloud-platform"]}},
})

# ① 서비스 계정으로 프로젝트를 건너 읽는다.
client = bigquery.Client(project="bullet-in-lakehouse")
names = [t.table_id for t in client.list_tables(DATASET)]
print("표", len(names), names[:3])
arrow = client.list_rows(f"{DATASET}.{names[-1]}").to_arrow()
print("읽음", arrow.num_rows, "행", len(arrow.schema), "컬럼")

# ② 중첩 구조를 진짜 카탈로그에 커밋한다.
try:
    catalog.create_namespace("probe")
except Exception as e:                      # NamespaceAlreadyExists
    print("네임스페이스", type(e).__name__)
t = catalog.create_table("probe.nested", schema=arrow.schema)
t.append(arrow)
print("커밋됨", t.scan().to_arrow().num_rows, "행")

# ③ 새 컬럼이 나타나면 스키마가 자라는가.
wider = arrow.append_column(pa.field("probe_new_key", pa.string()),
                            pa.array(["x"] * arrow.num_rows, type=pa.string()))
with t.update_schema() as u:
    u.union_by_name(wider.schema)
t = catalog.load_table("probe.nested")
t.append(wider)
print("진화 뒤 컬럼", len(t.schema().fields),
      "probe_new_key 있나", "probe_new_key" in [f.name for f in t.schema().fields])
print("진화 뒤 행", t.scan().to_arrow().num_rows)
```

```bash
scp -i ~/.ssh/seoulnow_deploy /tmp/probe_behavior.py ubuntu@155.248.164.17:/tmp/probe_behavior.py
```

- [ ] **Step 4: VM 에서 돌린다**

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  "env GOOGLE_APPLICATION_CREDENTIALS=/home/ubuntu/.bullet-in-lakehouse.json \
   ICEBERG_CATALOG_URI=https://biglake.googleapis.com/iceberg/v1/restcatalog \
   ICEBERG_WAREHOUSE=gs://bullet-in-lakehouse-prod \
   /home/ubuntu/.local/bin/uv run --project /home/ubuntu/bullet-in \
   --with google-cloud-bigquery python /tmp/probe_behavior.py"
```

기대하는 출력의 모양은 이렇다.

```
표 6 ['events_20260824', 'events_20260828', 'events_20260829']
읽음 821 행 31 컬럼
커밋됨 821 행
진화 뒤 컬럼 32 probe_new_key 있나 True
진화 뒤 행 1642
```

**세 줄이 각각 무엇을 증명하는지 헷갈리지 말 것.**
「읽음」 이 나오면 ①, 「커밋됨」 이 나오면 ②, 「진화 뒤 컬럼 32」 가 나오면 ③ 이다.
`403` 이 나면 ① 에서 막힌 것이고 권한 전파를 1분 기다렸다 다시 돌린다.
중첩 커밋에서 죽으면 스펙 §6 의 대비책 (원본을 평탄화된 형태로만 받기) 으로 돌리고, 그때는 이 계획의 Task 4 와 Task 5 를 하나로 합친다.

- [ ] **Step 5: 시험용 자국을 지운다**

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  "env GOOGLE_APPLICATION_CREDENTIALS=/home/ubuntu/.bullet-in-lakehouse.json \
   ICEBERG_CATALOG_URI=https://biglake.googleapis.com/iceberg/v1/restcatalog \
   ICEBERG_WAREHOUSE=gs://bullet-in-lakehouse-prod \
   /home/ubuntu/.local/bin/uv run --project /home/ubuntu/bullet-in python -c \
   'import os
from pyiceberg.catalog.rest import RestCatalog
c = RestCatalog(\"bullet_in\", uri=os.environ[\"ICEBERG_CATALOG_URI\"], warehouse=os.environ[\"ICEBERG_WAREHOUSE\"], auth={\"type\": \"google\", \"google\": {\"scopes\": [\"https://www.googleapis.com/auth/cloud-platform\"]}})
c.drop_table(\"probe.nested\")
c.drop_namespace(\"probe\")
print(\"지웠다\", c.list_namespaces())'"
```

기대: 마지막 줄의 목록에 `probe` 가 없다.

- [ ] **Step 6: 결과를 런북에 적고 스펙의 낡은 칸을 고친다**

`docs/runbook/2026-08-24-wiring-analytics-and-proving-it-arrives.md` 끝에 절을 하나 더한다.
확인한 값 셋 (읽은 행 수 · 커밋된 행 수 · 진화 뒤 컬럼 수) 을 그대로 적는다.

스펙 §6 위험표의 「표본 편중을 잊고 수치를 읽는 것」 행이 아직 「화면은 만들지 않는다」 라고 적혀 있다.
§2.1 과 §3.8 이 화면을 만든다고 고쳐졌으므로 이 칸만 「화면에도 표본 수를 함께 적는다」 로 바꾼다.

- [ ] **Step 7: 커밋**

```bash
git add docs/runbook/2026-08-24-wiring-analytics-and-proving-it-arrives.md \
        docs/superpowers/specs/2026-09-02-behavior-log-bronze-design.md
git commit -m "docs(warehouse): 프로젝트를 건너 읽는 권한과 중첩 커밋을 실물로 확인"
```

---

## Task 2: 의존을 더하고 네임스페이스를 매개변수로 연다

`NAMESPACE = "mart_history"` 가 모듈 상수라서 지금 코드는 네임스페이스를 하나만 다룬다.
`behavior` 를 더하려면 이 자리를 먼저 열어야 한다.

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/bullet_in/warehouse.py:25` (`NAMESPACE` 곁에 `BEHAVIOR_NS` 추가) · `241-269` (`ensure_namespace` · `ensure_table`) · `445-495` (`_existing_tables` · `run_maintenance` · `run_show`)
- Test: `tests/test_warehouse.py`

**Interfaces:**
- Consumes: Task 1 이 확인한 사실 셋
- Produces:
  - `warehouse.BEHAVIOR_NS: str` — `"behavior"`
  - `warehouse.ensure_namespace(catalog, namespace: str = NAMESPACE) -> None`
  - `warehouse.ensure_table(catalog, name: str, schema, namespace: str = NAMESPACE)`
  - `warehouse._existing_tables(catalog, namespace: str = NAMESPACE) -> list[str]`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_warehouse.py` 의 「카탈로그 · 테이블」 절 끝에 붙인다.

```python
def test_다른_네임스페이스에_같은_이름의_표를_따로_만든다(local_catalog):
    # mart_history 와 behavior 가 이름이 겹쳐도 서로를 덮지 않아야 한다.
    warehouse.ensure_namespace(local_catalog, warehouse.BEHAVIOR_NS)
    a = warehouse.ensure_table(local_catalog, "t", _schema())
    b = warehouse.ensure_table(local_catalog, "t", _schema(),
                               namespace=warehouse.BEHAVIOR_NS)
    assert a.name() != b.name()


def test_표_목록은_네임스페이스마다_따로_센다(local_catalog):
    warehouse.ensure_namespace(local_catalog, warehouse.BEHAVIOR_NS)
    warehouse.ensure_table(local_catalog, "only_mart", _schema())
    warehouse.ensure_table(local_catalog, "only_behavior", _schema(),
                           namespace=warehouse.BEHAVIOR_NS)
    assert warehouse._existing_tables(local_catalog) == ["only_mart"]
    assert warehouse._existing_tables(
        local_catalog, warehouse.BEHAVIOR_NS) == ["only_behavior"]
```

- [ ] **Step 2: 실패하는 것을 눈으로 본다**

```bash
uv run --project . --extra dev pytest tests/test_warehouse.py -k 네임스페이스 -v
```

기대: `TypeError: ensure_namespace() takes 1 positional argument but 2 were given` 로 실패.
**통과가 나오면 멈춘다** — 이름을 잘못 짚었거나 이미 있는 함수를 부르고 있다는 뜻이다.

- [ ] **Step 3: 매개변수를 연다**

`src/bullet_in/warehouse.py` 의 `NAMESPACE` 바로 아래에 더한다.

```python
NAMESPACE = "mart_history"
# 행동 기록은 성격이 달라 같은 이름 아래 두면 이름과 내용이 어긋난다 (설계 §3.1).
BEHAVIOR_NS = "behavior"
```

세 함수의 서명을 바꾼다.

```python
def ensure_namespace(catalog, namespace: str = NAMESPACE) -> None:
    """네임스페이스를 멱등하게 만든다."""
    from pyiceberg.exceptions import NamespaceAlreadyExistsError
    try:
        catalog.create_namespace(namespace)
    except NamespaceAlreadyExistsError:
        pass


def ensure_table(catalog, name: str, schema, namespace: str = NAMESPACE):
    """테이블을 멱등하게 만들고 돌려준다.

    원본에 컬럼이 늘어나는 저장소라 (`schema.sql` 이 ALTER 를 계속 더하고,
    행동 기록은 계측이 새 키를 심는다) 있는 테이블에는 union_by_name 으로 새
    컬럼을 붙인다.
    """
    from pyiceberg.exceptions import NoSuchTableError

    ident = f"{namespace}.{name}"
    try:
        table = catalog.load_table(ident)
    except NoSuchTableError:
        return catalog.create_table(ident, schema=schema,
                                    properties=TABLE_PROPERTIES)
    with table.update_schema() as u:
        u.union_by_name(schema)
    return table


def _existing_tables(catalog, namespace: str = NAMESPACE) -> list[str]:
    """네임스페이스 안의 테이블 이름. 아직 아무것도 없으면 빈 목록이다.

    네임스페이스가 없는 것은 고장이 아니라 「아직 한 번도 안 실었다」 는 뜻이다.
    그대로 예외를 올리면 유지보수 타이머가 적재보다 먼저 도는 첫날에 유닛이 실패하고
    `OnFailure` 가 헛알림을 보낸다.
    """
    from pyiceberg.exceptions import NoSuchNamespaceError

    try:
        return [t[-1] for t in catalog.list_tables(namespace)]
    except NoSuchNamespaceError:
        return []
```

- [ ] **Step 4: 유지보수와 보기가 두 네임스페이스를 함께 돌게 한다**

`run_maintenance` 와 `run_show` 의 루프를 네임스페이스 바깥 루프로 감싼다.

```python
def run_maintenance(now: datetime | None = None) -> None:
    """컴팩션 · 스냅샷 만료 · 오래된 파티션 솎기를 한 번에."""
    from pyiceberg.exceptions import NoSuchTableError

    now = now or datetime.now(timezone.utc)
    catalog = load_catalog()
    for ns in (NAMESPACE, BEHAVIOR_NS):
        for name in _existing_tables(catalog, ns):
            try:
                table = catalog.load_table(f"{ns}.{name}")
            except NoSuchTableError:
                continue
            if name.endswith("_snapshot"):
                drop_old_snapshot_dates(table, now.date())
            compact(table)
            expire(table, now)
            # 남은 스냅샷 수를 남긴다 — 1 MB 한도까지 얼마나 남았는지 보는 눈이다.
            log.info("%s.%s — 남은 스냅샷 %d개", ns, name,
                     len(table.metadata.snapshots))
```

```python
def run_show() -> None:
    """쌓인 테이블의 행 수 · 파일 수 · 남은 스냅샷 수를 보여 준다.

    파일 수와 스냅샷 수가 함께 보이는 것이 요점이다 — 앞은 컴팩션이,
    뒤는 만료가 도는지를 말해 준다.
    """
    catalog = load_catalog()
    for ns in (NAMESPACE, BEHAVIOR_NS):
        for name in sorted(_existing_tables(catalog, ns)):
            t = catalog.load_table(f"{ns}.{name}")
            files = list(t.scan().plan_files())
            size = sum(f.file.file_size_in_bytes for f in files)
            print(f"{ns}.{name:28} {t.scan().to_arrow().num_rows:>8,}행  "
                  f"파일 {len(files):>3}개  {size:>12,}B  "
                  f"스냅샷 {len(t.metadata.snapshots):>3}개")
```

- [ ] **Step 5: 의존을 더한다**

`pyproject.toml` 의 `dependencies` 에서 `pyiceberg` 줄 아래에 넣는다.

```toml
  "google-cloud-bigquery>=3.25",        # 행동 기록 원본 — storage 패키지 없이 REST 로 중첩까지 받는다
```

- [ ] **Step 6: 테스트가 통과하는 것을 본다**

```bash
uv run --project . --extra dev pytest tests/test_warehouse.py -v
```

기대: 새 둘을 포함해 전량 PASS.
기존 47개가 하나라도 깨지면 기본값을 안 준 자리가 있다는 뜻이다.

- [ ] **Step 7: 커밋**

```bash
git add pyproject.toml uv.lock src/bullet_in/warehouse.py tests/test_warehouse.py
git commit -m "feat(warehouse): 네임스페이스를 매개변수로 열고 BigQuery 의존을 더한다"
```

---

## Task 3: 어느 날짜를 실을지 판정한다

부수효과가 없는 판정 둘이다.
날짜가 판정 단위라 같은 날을 두 번 넣지 않는다 (스펙 §3.4).

**Files:**
- Modify: `src/bullet_in/warehouse.py` (「판정」 절 끝)
- Test: `tests/test_warehouse.py`

**Interfaces:**
- Consumes: `warehouse.BEHAVIOR_NS`
- Produces:
  - `warehouse.EVENTS_TABLE_RE: re.Pattern`
  - `warehouse.event_dates_of(table_ids: Iterable[str]) -> list[str]` — `"20260901"` 꼴의 오름차순 목록
  - `warehouse.dates_to_load(available: list[str], loaded: set[str]) -> list[str]`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_warehouse.py` 에 새 절로 붙인다.

```python
# --- 행동 기록 · 실을 날짜 판정 ---------------------------------------------

def test_일별_표에서_날짜만_뽑는다():
    got = warehouse.event_dates_of(["events_20260901", "events_20260828"])
    assert got == ["20260828", "20260901"]


def test_반쯤_찬_당일_표는_거른다():
    # GA4 가 스트리밍 내보내기를 켜면 events_intraday_* 를 만든다. 그날이 끝나면
    # 사라지고 완결된 표로 갈리므로 실으면 반쯤 찬 하루가 영구히 남는다.
    got = warehouse.event_dates_of(["events_20260901", "events_intraday_20260902"])
    assert got == ["20260901"]


def test_이벤트_표가_아닌_이름은_무시한다():
    assert warehouse.event_dates_of(["pseudonymous_users_20260901", "sessions"]) == []


def test_이미_실은_날짜는_대상에서_빠진다():
    got = warehouse.dates_to_load(["20260828", "20260829", "20260901"],
                                  {"20260828", "20260901"})
    assert got == ["20260829"]


def test_실을_날짜는_오래된_것부터다():
    got = warehouse.dates_to_load(["20260901", "20260824"], set())
    assert got == ["20260824", "20260901"]


def test_다_실었으면_대상이_없다():
    assert warehouse.dates_to_load(["20260901"], {"20260901"}) == []
```

- [ ] **Step 2: 실패하는 것을 눈으로 본다**

```bash
uv run --project . --extra dev pytest tests/test_warehouse.py -k "날짜 or 표" -v
```

기대: `AttributeError: module 'bullet_in.warehouse' has no attribute 'event_dates_of'`.

- [ ] **Step 3: 구현한다**

`warehouse.py` 의 `import` 에 `re` 를 더하고 판정 절 끝에 넣는다.

```python
# 일별 내보내기 표만 고른다. `events_intraday_*` 는 그날이 끝나면 사라지고 완결된
# 표로 갈리므로 실으면 반쯤 찬 하루가 영구히 남는다.
EVENTS_TABLE_RE = re.compile(r"^events_(\d{8})$")


def event_dates_of(table_ids) -> list[str]:
    """내보내기 표 이름 목록에서 날짜만 오름차순으로 뽑는다."""
    return sorted(m.group(1) for t in table_ids
                  if (m := EVENTS_TABLE_RE.match(t)))


def dates_to_load(available: list[str], loaded: set[str]) -> list[str]:
    """아직 안 실은 날짜를 오래된 것부터.

    상태 파일을 두지 않는다 — 실린 결과 자체가 워터마크라 둘이 어긋날 수 없다
    (`read_watermark` 와 같은 규율).
    """
    return [d for d in sorted(available) if d not in loaded]
```

- [ ] **Step 4: 통과하는 것을 본다**

```bash
uv run --project . --extra dev pytest tests/test_warehouse.py -v
```

기대: 전량 PASS.

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/warehouse.py tests/test_warehouse.py
git commit -m "feat(warehouse): 행동 기록에서 실을 날짜를 고르는 판정"
```

---

## Task 4: bronze 로 하루치를 그대로 옮긴다

BigQuery 가 준 31컬럼을 손대지 않고 넣는다.
겹친 행도 그대로 둔다 — 원자료는 도착한 그대로여야 하고 겹침을 지우는 것은 다음 층의 일이다 (스펙 §3.2).

**Files:**
- Modify: `src/bullet_in/warehouse.py` (「적재」 절 · `run_load`)
- Test: `tests/test_warehouse.py`

**Interfaces:**
- Consumes: `warehouse.event_dates_of` · `warehouse.dates_to_load` · `warehouse.ensure_table` · `warehouse.BEHAVIOR_NS`
- Produces:
  - `warehouse.GA4_TABLE: str` — `"ga4_events"`
  - `warehouse.with_load_columns(table: pa.Table, loaded_at: datetime) -> pa.Table`
  - `warehouse.loaded_event_dates(table) -> set[str]`
  - `warehouse.load_ga4_events(catalog, now: datetime) -> int` — 넣은 행 수

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
# --- 행동 기록 · 적재 시각 컬럼 ---------------------------------------------

def test_중첩을_지키면서_적재_컬럼을_붙인다():
    # 중첩 컬럼을 행 딕셔너리로 되돌리지 않는 것이 요점이다 — 되돌리면
    # event_params 배열이 뭉개진다.
    params = pa.array([[{"key": "card_hash", "value": {"string_value": "abc"}}]],
                      type=pa.list_(pa.struct([
                          ("key", pa.string()),
                          ("value", pa.struct([("string_value", pa.string())]))])))
    src = pa.table({"event_date": pa.array(["20260901"]), "event_params": params})
    got = warehouse.with_load_columns(src, _t(2026, 9, 2, 3))
    assert got.column(warehouse.LOADED_DATE).to_pylist() == ["2026-09-02"]
    assert got.column("event_params").to_pylist()[0][0]["key"] == "card_hash"
    assert got.num_rows == 1


def test_적재_컬럼은_행마다_같은_값이다():
    src = pa.table({"event_date": pa.array(["20260901", "20260901"])})
    got = warehouse.with_load_columns(src, _t(2026, 9, 2, 3))
    assert got.column(warehouse.LOADED_AT).to_pylist() == [_t(2026, 9, 2, 3)] * 2
```

그리고 적재 경로 테스트를 「적재」 절에 붙인다.

```python
@pytest.fixture
def fake_ga4(monkeypatch):
    """BigQuery 자리에 메모리 위의 하루치를 둔다.

    재려는 것은 BigQuery 가 아니라 적재 경로다 — 어느 날짜를 고르고, 두 번 돌면
    어떻게 되는지. Iceberg 쪽은 진짜로 돈다.
    """
    state = {"days": {}}

    def _list(dataset):
        return sorted(state["days"])

    def _read(dataset, table_id):
        day = table_id.removeprefix("events_")
        return pa.table({"event_date": pa.array([day] * state["days"][day]),
                         "event_name": pa.array(["bi_card_click"] * state["days"][day])})

    monkeypatch.setattr(warehouse, "_bq_table_ids", _list)
    monkeypatch.setattr(warehouse, "_bq_read_day", _read)
    monkeypatch.setenv("GA4_DATASET", "p.d")
    return state


def test_아직_안_실은_날짜만_실린다(local_catalog, fake_ga4):
    fake_ga4["days"] = {"20260901": 3}
    assert warehouse.load_ga4_events(local_catalog, _t(2026, 9, 2, 3)) == 3
    fake_ga4["days"]["20260902"] = 2
    assert warehouse.load_ga4_events(local_catalog, _t(2026, 9, 3, 3)) == 2
    t = local_catalog.load_table(f"{warehouse.BEHAVIOR_NS}.{warehouse.GA4_TABLE}")
    assert t.scan().to_arrow().num_rows == 5


def test_같은_날을_두_번_실어도_행이_안_는다(local_catalog, fake_ga4):
    fake_ga4["days"] = {"20260901": 3}
    warehouse.load_ga4_events(local_catalog, _t(2026, 9, 2, 3))
    assert warehouse.load_ga4_events(local_catalog, _t(2026, 9, 2, 12)) == 0
    t = local_catalog.load_table(f"{warehouse.BEHAVIOR_NS}.{warehouse.GA4_TABLE}")
    assert t.scan().to_arrow().num_rows == 3


def test_설정이_없으면_조용히_넘어간다(local_catalog, fake_ga4, monkeypatch):
    monkeypatch.delenv("GA4_DATASET")
    assert warehouse.load_ga4_events(local_catalog, _t(2026, 9, 2, 3)) == 0
```

- [ ] **Step 2: 실패하는 것을 눈으로 본다**

```bash
uv run --project . --extra dev pytest tests/test_warehouse.py -k "적재_컬럼 or 실은_날짜 or 두_번_실어도 or 조용히" -v
```

기대: `AttributeError: ... has no attribute 'with_load_columns'`.

- [ ] **Step 3: 구현한다**

「적재」 절 끝, `load_ops` 아래에 넣는다.

```python
# --- 행동 기록 (BigQuery -> bronze) ----------------------------------------

GA4_TABLE = "ga4_events"


def with_load_columns(table: pa.Table, loaded_at: datetime) -> pa.Table:
    """중첩을 그대로 둔 채 적재 시각 두 컬럼만 덧붙인다.

    `to_arrow()` 를 쓰지 않는다 — 그쪽은 행 딕셔너리에서 세우는 길이라
    `event_params` 배열과 `device` 레코드가 뭉개진다.
    """
    n = table.num_rows
    ts = pa.timestamp("us", tz="UTC")
    return (table
            .append_column(pa.field(LOADED_AT, ts),
                           pa.array([loaded_at] * n, type=ts))
            .append_column(pa.field(LOADED_DATE, pa.string()),
                           pa.array([loaded_at.date().isoformat()] * n,
                                    type=pa.string())))


def loaded_event_dates(table) -> set[str]:
    """이미 실린 날짜. 비어 있으면 빈 집합이다."""
    scan = table.scan(selected_fields=("event_date",)).to_arrow()
    if scan.num_rows == 0:
        return set()
    return set(scan.column("event_date").to_pylist())


def _bq_client():
    """읽기 전용 BigQuery 클라이언트.

    자격은 `GOOGLE_APPLICATION_CREDENTIALS` 가 가리키는 서비스 계정이고,
    그 계정은 `bullet-in-analytics` 에 `bigquery.dataViewer` 를 받아 두었다.
    """
    from google.cloud import bigquery
    return bigquery.Client(project=os.environ.get("GA4_BILLING_PROJECT")
                           or "bullet-in-lakehouse")


def _bq_table_ids(dataset: str) -> list[str]:
    return [t.table_id for t in _bq_client().list_tables(dataset)]


def _bq_read_day(dataset: str, table_id: str) -> pa.Table:
    return _bq_client().list_rows(f"{dataset}.{table_id}").to_arrow()


def load_ga4_events(catalog, now: datetime) -> int:
    """아직 안 실은 날짜를 오래된 것부터 원본 그대로 넣는다.

    `GA4_DATASET` 이 없으면 아무것도 안 한다 — 개발 환경에는 이 설정이 없고,
    없다는 것이 고장은 아니다.
    """
    dataset = os.environ.get("GA4_DATASET")
    if not dataset:
        log.info("%s — GA4_DATASET 이 없어 넘어간다", GA4_TABLE)
        return 0

    from pyiceberg.exceptions import NoSuchTableError

    # 자기 표를 담을 자리는 자기가 챙긴다 — 부르는 쪽 순서에 기대면 이 함수만
    # 따로 돌릴 수 없다.
    ensure_namespace(catalog, BEHAVIOR_NS)
    try:
        loaded = loaded_event_dates(
            catalog.load_table(f"{BEHAVIOR_NS}.{GA4_TABLE}"))
    except NoSuchTableError:
        loaded = set()

    days = dates_to_load(event_dates_of(_bq_table_ids(dataset)), loaded)
    if not days:
        log.info("%s — 새로 실을 날짜가 없다 (실린 날 %d일)", GA4_TABLE, len(loaded))
        return 0

    total = 0
    for day in days:
        arrow = with_load_columns(_bq_read_day(dataset, f"events_{day}"), now)
        table = ensure_table(catalog, GA4_TABLE, arrow.schema,
                             namespace=BEHAVIOR_NS)
        table.append(arrow)
        log.info("%s — %s %d행 적재", GA4_TABLE, day, arrow.num_rows)
        total += arrow.num_rows
    return total
```

- [ ] **Step 4: `run_load` 에 갈래를 더한다**

앞의 적재가 이 갈래 때문에 죽지 않게 가른다 (스펙 §6).

```python
def run_load(now: datetime | None = None) -> None:
    """이번 회차의 적재를 끝낸다."""
    from sqlalchemy import create_engine

    now = now or datetime.now(timezone.utc)
    engine = create_engine(_require_env("MARIADB_URL"))
    catalog = load_catalog()
    ensure_namespace(catalog)

    for plan in plans_for(now, _last_daily_at(catalog)):
        if plan.mode == "changes":
            load_changes(engine, catalog, plan, now)
        elif plan.mode == "snapshot":
            load_snapshot(engine, catalog, plan, now)
        else:
            load_ops(engine, catalog, now)

    # 행동 기록은 출처가 다르고 하루 늦게 도착한다. 여기서 실패해도 위의 적재는
    # 이미 끝났으므로 회차를 통째로 죽이지 않는다.
    try:
        load_ga4_events(catalog, now)
    except Exception:
        log.warning("행동 기록 적재 실패 — 마트 이력 적재는 끝났다", exc_info=True)
```

- [ ] **Step 5: 통과하는 것을 본다**

```bash
uv run --project . --extra dev pytest tests/test_warehouse.py -v
```

기대: 전량 PASS.

- [ ] **Step 6: 일부러 깨뜨려 테스트가 진짜 보는지 확인한다**

`dates_to_load` 의 `if d not in loaded` 를 `if True` 로 바꾸고 돌린다.

```bash
uv run --project . --extra dev pytest tests/test_warehouse.py -k 두_번_실어도 -v
```

기대: FAIL (`assert 6 == 3`).
**통과하면 테스트가 엉뚱한 자리를 보고 있는 것이다** — 되돌리기 전에 테스트를 고친다.
확인 뒤 `if d not in loaded` 로 되돌린다.

- [ ] **Step 7: 커밋**

```bash
git add src/bullet_in/warehouse.py tests/test_warehouse.py
git commit -m "feat(warehouse): 행동 기록 하루치를 bronze 로 그대로 옮긴다"
```

---

## Task 5: 평탄화를 순수 함수로 만든다

여기까지가 첫 회차다.
평탄화는 부수효과가 없어 통째로 테스트가 된다.

**Files:**
- Modify: `src/bullet_in/warehouse.py` (「판정」 절)
- Test: `tests/test_warehouse.py`

**Interfaces:**
- Consumes: 없음 (순수)
- Produces:
  - `warehouse.FLAT_BASE_TYPES: dict[str, pa.DataType]`
  - `warehouse.NESTED_COLUMNS: dict[str, tuple[str, ...]]`
  - `warehouse.flatten_rows(rows: list[dict]) -> list[dict]`
  - `warehouse.dedupe_events(rows: list[dict]) -> list[dict]`
  - `warehouse.flat_schema(rows: list[dict]) -> pa.Schema`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
# --- 행동 기록 · 평탄화 -----------------------------------------------------

def _event(name="bi_card_click", ts=1_756_000_000_000_000, params=None, **extra):
    row = {"event_date": "20260901", "event_timestamp": ts, "event_name": name,
           "user_pseudo_id": "u1", "platform": "WEB",
           "device": {"category": "mobile", "operating_system": "iOS",
                      "web_info": {"browser": "Safari"}},
           "geo": {"country": "South Korea", "region": "Seoul"},
           "traffic_source": {"source": "google", "medium": "organic",
                              "name": "(direct)"},
           "event_params": params or []}
    row.update(extra)
    return row


def _p(key, **value):
    return {"key": key, "value": {"string_value": None, "int_value": None,
                                  "float_value": None, "double_value": None,
                                  **value}}


def test_파라미터_키가_컬럼이_된다():
    got = warehouse.flatten_rows([_event(params=[_p("card_hash", string_value="abc")])])
    assert got[0]["card_hash"] == "abc"


def test_값이_어느_칸에_있든_문자열로_모은다():
    # 같은 키가 두 타입으로 오는 자리가 실제로 있다 (session_engaged · card_tier).
    got = warehouse.flatten_rows([_event(params=[
        _p("session_engaged", int_value=1), _p("card_tier", double_value=2.5)])])
    assert got[0]["session_engaged"] == "1"
    assert got[0]["card_tier"] == "2.5"


def test_중첩_축이_컬럼으로_펴진다():
    got = warehouse.flatten_rows([_event()])
    assert got[0]["device_category"] == "mobile"
    assert got[0]["device_browser"] == "Safari"
    assert got[0]["geo_country"] == "South Korea"
    assert got[0]["traffic_source"] == "google"


def test_없는_중첩_축은_널로_남는다():
    got = warehouse.flatten_rows([_event(geo=None)])
    assert got[0]["geo_country"] is None


def test_수집_시각이_시각_타입으로_간다():
    got = warehouse.flatten_rows([_event(ts=1_756_000_000_000_000)])
    assert got[0]["event_at"] == datetime(2026, 8, 24, 1, 46, 40, tzinfo=timezone.utc)


def test_KST_날짜는_UTC_와_다를_수_있다():
    # UTC 2026-08-24 20:00 은 KST 로 2026-08-25 다.
    got = warehouse.flatten_rows([_event(ts=1_756_065_600_000_000)])
    assert got[0]["event_date_kst"] == "2026-08-25"


def test_기사_클릭_판정은_해시가_있을_때만_참():
    with_hash = warehouse.flatten_rows(
        [_event(params=[_p("card_hash", string_value="abc")])])
    without = warehouse.flatten_rows(
        [_event(params=[_p("card_slug", string_value="saka")])])
    assert with_hash[0]["is_article_click"] is True
    assert without[0]["is_article_click"] is False


def test_빈_값을_채우지_않는다():
    # card_hash 가 없다는 것은 기사 카드가 아니라는 뜻이고 채우면 거짓이 된다.
    got = warehouse.flatten_rows([_event(params=[])])
    assert got[0].get("card_hash") is None


def test_겹친_행을_하나로_접는다():
    rows = warehouse.flatten_rows([
        _event(params=[_p("bi_cid", string_value="c1"),
                       _p("bi_ts", string_value="2026-09-01T00:00:00Z")]),
        _event(ts=1_756_000_009_000_000,
               params=[_p("bi_cid", string_value="c1"),
                       _p("bi_ts", string_value="2026-09-01T00:00:00Z")]),
    ])
    assert len(warehouse.dedupe_events(rows)) == 1


def test_식별자가_없는_행은_안_접는다():
    # 자동 수집 이벤트에는 bi_cid 가 없다. 널을 키로 접으면 3분의 2가 사라진다.
    rows = warehouse.flatten_rows([_event(name="page_view"),
                                   _event(name="page_view")])
    assert len(warehouse.dedupe_events(rows)) == 2


def test_스키마는_나타난_키_전량으로_선다():
    rows = warehouse.flatten_rows([_event(params=[_p("새키", string_value="v")])])
    names = [f.name for f in warehouse.flat_schema(rows)]
    assert "새키" in names
    assert names[-2:] == [warehouse.LOADED_AT, warehouse.LOADED_DATE]


def test_기본_컬럼과_이름이_겹치면_갈라_둔다():
    rows = warehouse.flatten_rows([_event(params=[_p("event_name", string_value="x")])])
    assert rows[0]["event_name"] == "bi_card_click"
    assert rows[0]["event_name_param"] == "x"
```

- [ ] **Step 2: 실패하는 것을 눈으로 본다**

```bash
uv run --project . --extra dev pytest tests/test_warehouse.py -k "평탄화 or 파라미터 or 중첩_축 or 겹친 or 스키마는" -v
```

기대: `AttributeError: ... has no attribute 'flatten_rows'`.

- [ ] **Step 3: 구현한다**

판정 절에 넣는다.
`from datetime import ...` 에 이미 `timedelta` 가 있다.

```python
# --- 행동 기록 평탄화 (부수효과 없음) ---------------------------------------

KST = timezone(timedelta(hours=9))
# 공개일. 이 하루가 표본의 58% 라 집계에서 가른다 (설계 §2.1).
LAUNCH_DATE = date(2026, 8, 29)

# 평탄화 결과에서 타입을 주는 컬럼. 나머지는 전부 문자열이다.
FLAT_BASE_TYPES = {
    "event_date": pa.string(), "event_timestamp": pa.int64(),
    "event_name": pa.string(), "user_pseudo_id": pa.string(),
    "platform": pa.string(),
    "event_at": pa.timestamp("us", tz="UTC"),
    "event_date_kst": pa.string(), "is_article_click": pa.bool_(),
}

# 중첩 레코드에서 꺼내 컬럼으로 펴는 축.
NESTED_COLUMNS = {
    "device_category": ("device", "category"),
    "device_os": ("device", "operating_system"),
    "device_browser": ("device", "web_info", "browser"),
    "geo_country": ("geo", "country"),
    "geo_region": ("geo", "region"),
    "traffic_source": ("traffic_source", "source"),
    "traffic_medium": ("traffic_source", "medium"),
    "traffic_name": ("traffic_source", "name"),
}

# 파라미터 값이 네 칸에 나뉘어 온다. 있는 것 하나를 문자열로 모은다.
_PARAM_VALUE_FIELDS = ("string_value", "int_value", "float_value", "double_value")


def _dig(row: dict | None, path: tuple[str, ...]):
    """중첩 레코드를 따라 내려간다. 도중에 없으면 None."""
    cur = row
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _param_value(value: dict | None) -> str | None:
    for field in _PARAM_VALUE_FIELDS:
        got = (value or {}).get(field)
        if got is not None:
            return str(got)
    return None


def flatten_rows(rows: list[dict]) -> list[dict]:
    """원본 행을 컬럼 하나에 값 하나인 모양으로 편다.

    빈 값은 채우지 않는다 — `card_hash` 가 없다는 것은 기사 카드가 아니라는
    뜻이고 채우면 거짓이 된다 (설계 §3.3).
    """
    base = tuple(k for k in FLAT_BASE_TYPES if k not in ("event_at",
                                                         "event_date_kst",
                                                         "is_article_click"))
    out = []
    for row in rows:
        flat = {c: row.get(c) for c in base}
        for name, path in NESTED_COLUMNS.items():
            flat[name] = _dig(row, path)
        for param in (row.get("event_params") or []):
            key = param.get("key")
            if not key:
                continue
            # 계측이 심는 키라 기본 컬럼과 겹칠 수 있다. 겹치면 밑에 깔리므로 가른다.
            if key in FLAT_BASE_TYPES or key in NESTED_COLUMNS:
                key = f"{key}_param"
            flat[key] = _param_value(param.get("value"))

        micros = flat.get("event_timestamp")
        at = (datetime.fromtimestamp(micros / 1_000_000, tz=timezone.utc)
              if micros else None)
        flat["event_at"] = at
        flat["event_date_kst"] = at.astimezone(KST).date().isoformat() if at else None
        flat["is_article_click"] = bool(flat.get("event_name") == "bi_card_click"
                                        and flat.get("card_hash"))
        out.append(flat)
    return out


def dedupe_events(rows: list[dict]) -> list[dict]:
    """같은 행동이 두 번 도착한 것을 접는다 (실측 51건 · 설계 §1.5).

    `bi_cid` 가 없는 행은 접지 않는다 — 자동 수집 이벤트에는 그 값이 없어서
    키가 전부 널이 되고, 한 덩어리로 뭉쳐 3분의 2가 사라진다.
    """
    seen: set[tuple] = set()
    out = []
    for row in rows:
        cid = row.get("bi_cid")
        if not cid:
            out.append(row)
            continue
        key = (cid, row.get("bi_ts"), row.get("event_name"))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def flat_schema(rows: list[dict]) -> pa.Schema:
    """나타난 키 전량으로 스키마를 세운다.

    목록을 사람이 관리하지 않으므로 계측이 바뀌어도 낡지 않는다 (설계 §2 결정 7).
    새 키가 나타나면 `ensure_table` 의 union_by_name 이 컬럼을 늘린다.
    """
    names = list(FLAT_BASE_TYPES) + list(NESTED_COLUMNS)
    seen = set(names)
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                names.append(key)
    fields = [pa.field(n, FLAT_BASE_TYPES.get(n, pa.string())) for n in names]
    fields.append(pa.field(LOADED_AT, pa.timestamp("us", tz="UTC")))
    fields.append(pa.field(LOADED_DATE, pa.string()))
    return pa.schema(fields)
```

- [ ] **Step 4: 통과하는 것을 본다**

```bash
uv run --project . --extra dev pytest tests/test_warehouse.py -v
```

기대: 전량 PASS.

- [ ] **Step 5: 일부러 깨뜨려 확인한다**

`dedupe_events` 의 `if not cid: out.append(row); continue` 두 줄을 지우고 돌린다.

```bash
uv run --project . --extra dev pytest tests/test_warehouse.py -k 식별자가_없는 -v
```

기대: FAIL (`assert 1 == 2`).
확인 뒤 되돌린다.

- [ ] **Step 6: 커밋**

```bash
git add src/bullet_in/warehouse.py tests/test_warehouse.py
git commit -m "feat(warehouse): 행동 기록 평탄화와 겹침 접기를 순수 함수로"
```

---

## Task 6: 평탄화본을 silver 로 적재한다

원본에서 파생한다.
같은 회차 안에서 그 날짜분만 만들어 덧붙인다 (스펙 §3.3).

**Files:**
- Modify: `src/bullet_in/warehouse.py` (`load_ga4_events`)
- Test: `tests/test_warehouse.py`

**Interfaces:**
- Consumes: `warehouse.flatten_rows` · `warehouse.dedupe_events` · `warehouse.flat_schema` · `warehouse.to_arrow`
- Produces:
  - `warehouse.GA4_FLAT_TABLE: str` — `"ga4_events_flat"`
  - `warehouse.flatten_day(arrow: pa.Table) -> list[dict]` — 평탄화 · 겹침 접기까지 끝낸 행

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`fake_ga4` 픽스처의 `_read` 를 파라미터까지 담게 바꾸고 테스트를 더한다.

```python
def _read(dataset, table_id):
    day = table_id.removeprefix("events_")
    n = state["days"][day]
    params = pa.array(
        [[{"key": "bi_cid", "value": {"string_value": f"c{i}",
                                      "int_value": None,
                                      "float_value": None,
                                      "double_value": None}}]
         for i in range(n)],
        type=pa.list_(pa.struct([
            ("key", pa.string()),
            ("value", pa.struct([("string_value", pa.string()),
                                 ("int_value", pa.int64()),
                                 ("float_value", pa.float64()),
                                 ("double_value", pa.float64())]))])))
    return pa.table({"event_date": pa.array([day] * n),
                     "event_timestamp": pa.array([1_756_000_000_000_000] * n,
                                                 type=pa.int64()),
                     "event_name": pa.array(["bi_card_click"] * n),
                     "event_params": params})
```

```python
def test_평탄화본이_원본과_같은_날_함께_실린다(local_catalog, fake_ga4):
    fake_ga4["days"] = {"20260901": 3}
    warehouse.load_ga4_events(local_catalog, _t(2026, 9, 2, 3))
    flat = local_catalog.load_table(
        f"{warehouse.BEHAVIOR_NS}.{warehouse.GA4_FLAT_TABLE}").scan().to_arrow()
    assert flat.num_rows == 3
    assert "bi_cid" in flat.schema.names
    assert "event_params" not in flat.schema.names


def test_평탄화본도_같은_날을_두_번_안_넣는다(local_catalog, fake_ga4):
    fake_ga4["days"] = {"20260901": 3}
    warehouse.load_ga4_events(local_catalog, _t(2026, 9, 2, 3))
    warehouse.load_ga4_events(local_catalog, _t(2026, 9, 2, 12))
    flat = local_catalog.load_table(
        f"{warehouse.BEHAVIOR_NS}.{warehouse.GA4_FLAT_TABLE}").scan().to_arrow()
    assert flat.num_rows == 3
```

- [ ] **Step 2: 실패하는 것을 눈으로 본다**

```bash
uv run --project . --extra dev pytest tests/test_warehouse.py -k 평탄화본 -v
```

기대: `AttributeError: ... has no attribute 'GA4_FLAT_TABLE'`.

- [ ] **Step 3: 구현한다**

`GA4_TABLE` 곁에 이름을 더한다.

```python
GA4_TABLE = "ga4_events"
GA4_FLAT_TABLE = "ga4_events_flat"
```

`with_load_columns` 아래에 붙인다.

```python
def flatten_day(arrow: pa.Table) -> list[dict]:
    """하루치 원본에서 평탄화 · 겹침 접기까지 끝낸 행을 만든다."""
    return dedupe_events(flatten_rows(arrow.to_pylist()))
```

`load_ga4_events` 의 날짜 루프 안을 두 줄 늘린다.

```python
    total = 0
    for day in days:
        raw = _bq_read_day(dataset, f"events_{day}")
        arrow = with_load_columns(raw, now)
        table = ensure_table(catalog, GA4_TABLE, arrow.schema,
                             namespace=BEHAVIOR_NS)
        table.append(arrow)

        # 평탄화본은 원본에서 파생한다. 모양이 마음에 안 들면 통째로 지우고
        # 원본에서 다시 만들 수 있다 (설계 §3.3).
        flat = flatten_day(raw)
        schema = flat_schema(flat)
        flat_table = ensure_table(catalog, GA4_FLAT_TABLE, schema,
                                  namespace=BEHAVIOR_NS)
        flat_table.append(to_arrow(flat, schema, loaded_at=now))

        log.info("%s — %s 원본 %d행 · 평탄화 %d행 적재",
                 GA4_TABLE, day, arrow.num_rows, len(flat))
        total += arrow.num_rows
    return total
```

`to_arrow` 는 `bool` 컬럼을 다루지 않은 적이 없으므로 `is_article_click` 이 처음이다.
`pa.array([True, False], type=pa.bool_())` 는 그대로 통하므로 고칠 것이 없다.

- [ ] **Step 4: 통과하는 것을 본다**

```bash
uv run --project . --extra dev pytest tests/test_warehouse.py -v
```

기대: 전량 PASS.

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/warehouse.py tests/test_warehouse.py
git commit -m "feat(warehouse): 행동 기록 평탄화본을 silver 로 함께 적재"
```

---

## Task 7: gold — 팩트와 날짜 디멘션

디멘션 둘 (`dim_article` · `dim_player`) 은 이미 `mart_history` 에 있으므로 새로 만들지 않고 참조한다 (스펙 §3.5).
새로 세우는 것은 팩트와 날짜 디멘션 둘이다.

**Files:**
- Modify: `src/bullet_in/warehouse.py`
- Test: `tests/test_warehouse.py`

**Interfaces:**
- Consumes: `warehouse.flatten_day` · `warehouse.LAUNCH_DATE`
- Produces:
  - `warehouse.FACT_TABLE: str` — `"fact_card_click"` · `warehouse.DIM_DATE_TABLE: str` — `"dim_date"`
  - `warehouse.FACT_COLUMNS: tuple[str, ...]`
  - `warehouse.fact_rows(flat: list[dict]) -> list[dict]`
  - `warehouse.dim_date_rows(dates) -> list[dict]`
  - `warehouse.build_gold(catalog, now: datetime) -> int`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
# --- 행동 기록 · gold -------------------------------------------------------

def test_팩트는_카드_클릭만_담는다():
    flat = warehouse.flatten_rows([
        _event(name="bi_card_click", params=[_p("card_hash", string_value="abc")]),
        _event(name="page_view"),
    ])
    got = warehouse.fact_rows(flat)
    assert len(got) == 1
    assert got[0]["card_hash"] == "abc"


def test_팩트는_정한_컬럼만_남긴다():
    flat = warehouse.flatten_rows([
        _event(params=[_p("card_hash", string_value="abc"),
                       _p("ga_session_id", string_value="9")])])
    assert set(warehouse.fact_rows(flat)[0]) == set(warehouse.FACT_COLUMNS)


def test_날짜_디멘션이_공개일을_표시한다():
    got = {r["date"]: r for r in warehouse.dim_date_rows(["2026-08-29", "2026-08-30"])}
    assert got["2026-08-29"]["is_launch_day"] is True
    assert got["2026-08-30"]["is_launch_day"] is False
    assert got["2026-08-30"]["days_since_launch"] == 1


def test_날짜_디멘션은_같은_날을_한_번만_담는다():
    got = warehouse.dim_date_rows(["2026-08-30", "2026-08-30"])
    assert len(got) == 1


def test_gold_는_평탄화본에서_다시_세운다(local_catalog, fake_ga4):
    fake_ga4["days"] = {"20260901": 3}
    warehouse.load_ga4_events(local_catalog, _t(2026, 9, 2, 3))
    assert warehouse.build_gold(local_catalog, _t(2026, 9, 2, 3)) == 3
    # 두 번 돌려도 갈아 끼우므로 행이 안 는다.
    assert warehouse.build_gold(local_catalog, _t(2026, 9, 2, 4)) == 3
    fact = local_catalog.load_table(
        f"{warehouse.BEHAVIOR_NS}.{warehouse.FACT_TABLE}").scan().to_arrow()
    assert fact.num_rows == 3
```

- [ ] **Step 2: 실패하는 것을 눈으로 본다**

```bash
uv run --project . --extra dev pytest tests/test_warehouse.py -k "팩트 or 날짜_디멘션 or gold_는" -v
```

기대: `AttributeError: ... has no attribute 'fact_rows'`.

- [ ] **Step 3: 판정 둘을 구현한다**

평탄화 절 끝에 붙인다.

```python
# 팩트의 알갱이는 클릭 한 건이다. 표본 수 (`n_clicks`) 는 여기 두지 않고
# 집계 함수가 낸다 — 행마다 값이 1인 컬럼은 뜻이 없다.
FACT_COLUMNS = ("bi_cid", "event_at", "event_date_kst", "card_hash", "card_slug",
                "card_stage", "card_tier", "card_outlet", "card_surface",
                "page_location", "device_category", "geo_country")


def fact_rows(flat: list[dict]) -> list[dict]:
    """카드 클릭만 골라 정한 축만 남긴다."""
    return [{c: row.get(c) for c in FACT_COLUMNS}
            for row in flat if row.get("event_name") == "bi_card_click"]


def dim_date_rows(dates) -> list[dict]:
    """날짜 축. 공개일로부터 며칠째인지를 함께 담는다."""
    out = []
    for iso in sorted({d for d in dates if d}):
        day = date.fromisoformat(iso)
        out.append({"date": iso, "weekday": day.isoweekday(),
                    "days_since_launch": (day - LAUNCH_DATE).days,
                    "is_launch_day": day == LAUNCH_DATE})
    return out
```

- [ ] **Step 4: 세우는 쪽을 구현한다**

적재 절 끝에 붙인다.

```python
FACT_TABLE = "fact_card_click"
DIM_DATE_TABLE = "dim_date"

_FACT_TYPES = {"event_at": pa.timestamp("us", tz="UTC")}
_DIM_DATE_TYPES = {"date": pa.string(), "weekday": pa.int32(),
                   "days_since_launch": pa.int32(), "is_launch_day": pa.bool_()}


def _typed_schema(names, types: dict) -> pa.Schema:
    fields = [pa.field(n, types.get(n, pa.string())) for n in names]
    fields.append(pa.field(LOADED_AT, pa.timestamp("us", tz="UTC")))
    fields.append(pa.field(LOADED_DATE, pa.string()))
    return pa.schema(fields)


def build_gold(catalog, now: datetime) -> int:
    """평탄화본 전량에서 팩트와 날짜 디멘션을 다시 세운다.

    덧붙이지 않고 갈아 끼운다 — 원본이 남아 있어 언제든 다시 만들 수 있고,
    그래야 겹침 접기 규칙을 고쳤을 때 옛 결과가 안 남는다.
    """
    from pyiceberg.exceptions import NoSuchTableError

    try:
        flat_table = catalog.load_table(f"{BEHAVIOR_NS}.{GA4_FLAT_TABLE}")
    except NoSuchTableError:
        log.info("%s — 평탄화본이 아직 없다", FACT_TABLE)
        return 0

    flat = flat_table.scan().to_arrow().to_pylist()
    facts = fact_rows(flat)
    dims = dim_date_rows(r.get("event_date_kst") for r in flat)

    for name, rows, types in ((FACT_TABLE, facts, _FACT_TYPES),
                              (DIM_DATE_TABLE, dims, _DIM_DATE_TYPES)):
        names = FACT_COLUMNS if name == FACT_TABLE else tuple(_DIM_DATE_TYPES)
        schema = _typed_schema(names, types)
        table = ensure_table(catalog, name, schema, namespace=BEHAVIOR_NS)
        table.overwrite(to_arrow(rows, schema, loaded_at=now))
        log.info("%s — %d행 갈아 끼움", name, len(rows))
    return len(facts)
```

`run_load` 의 행동 기록 갈래에서 적재 뒤에 부른다.

```python
    try:
        load_ga4_events(catalog, now)
        build_gold(catalog, now)
    except Exception:
        log.warning("행동 기록 적재 실패 — 마트 이력 적재는 끝났다", exc_info=True)
```

- [ ] **Step 5: 통과하는 것을 본다**

```bash
uv run --project . --extra dev pytest tests/test_warehouse.py -v
```

기대: 전량 PASS.

- [ ] **Step 6: 일부러 깨뜨려 확인한다**

`build_gold` 의 `table.overwrite(...)` 를 `table.append(...)` 로 바꾸고 돌린다.

```bash
uv run --project . --extra dev pytest tests/test_warehouse.py -k gold_는 -v
```

기대: FAIL (`assert 6 == 3`).
확인 뒤 되돌린다.

- [ ] **Step 7: 커밋**

```bash
git add src/bullet_in/warehouse.py tests/test_warehouse.py
git commit -m "feat(warehouse): 행동 기록 gold 팩트와 날짜 디멘션"
```

---

## Task 8: 집계를 내고 JSON 으로 떨어뜨린다

여기까지가 둘째 회차다.
화면이 읽을 값을 만든다.

**Files:**
- Modify: `src/bullet_in/warehouse.py`
- Modify: `.gitignore`
- Test: `tests/test_warehouse.py`

**Interfaces:**
- Consumes: `warehouse.fact_rows` · `warehouse.LAUNCH_DATE`
- Produces:
  - `warehouse.METRICS_PATH: Path` — `Path("state/behavior_metrics.json")`
  - `warehouse.aggregate(facts: list[dict], articles: list[dict]) -> dict`
  - `warehouse.write_metrics(catalog, now: datetime) -> dict`

집계 결과의 모양은 이렇다.

```json
{
  "generated_at": "2026-09-03T02:40:00+00:00",
  "totals": {"all": 587, "launch_day": 341, "counted": 246},
  "dates": {"from": "2026-08-24", "to": "2026-09-01"},
  "axes": {
    "card_outlet": [{"value": "The Athletic", "n_clicks": 31,
                     "n_articles": 24, "per_article": 1.29}],
    "card_stage": [], "card_tier": [], "card_surface": []
  }
}
```

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
# --- 행동 기록 · 집계 -------------------------------------------------------

def _fact(outlet="The Athletic", day="2026-08-30", **extra):
    row = {c: None for c in warehouse.FACT_COLUMNS}
    row.update({"card_outlet": outlet, "event_date_kst": day,
                "card_hash": "h", "card_stage": "rumour", "card_tier": "1",
                "card_surface": "item"})
    row.update(extra)
    return row


def test_공개일_클릭은_집계에서_뺀다():
    got = warehouse.aggregate([_fact(day="2026-08-29"), _fact(day="2026-08-30")], [])
    assert got["totals"] == {"all": 2, "launch_day": 1, "counted": 1}


def test_축별로_클릭을_세고_표본_수를_함께_낸다():
    got = warehouse.aggregate([_fact(), _fact(), _fact(outlet="BBC")], [])
    outlets = got["axes"]["card_outlet"]
    assert outlets[0] == {"value": "The Athletic", "n_clicks": 2,
                          "n_articles": 0, "per_article": None}
    assert [o["value"] for o in outlets] == ["The Athletic", "BBC"]


def test_기사_수로_나눈_값을_함께_낸다():
    articles = [{"source_id": "The Athletic", "transfer_stage": "rumour",
                 "journalist_tier": "1"}] * 4
    got = warehouse.aggregate([_fact(), _fact()], articles)
    assert got["axes"]["card_outlet"][0]["n_articles"] == 4
    assert got["axes"]["card_outlet"][0]["per_article"] == 0.5


def test_값이_빈_축은_이름을_붙여_센다():
    got = warehouse.aggregate([_fact(outlet=None)], [])
    assert got["axes"]["card_outlet"][0]["value"] == "(없음)"


def test_클릭이_하나도_없으면_빈_집계가_나온다():
    got = warehouse.aggregate([], [])
    assert got["totals"] == {"all": 0, "launch_day": 0, "counted": 0}
    assert got["axes"]["card_outlet"] == []
```

- [ ] **Step 2: 실패하는 것을 눈으로 본다**

```bash
uv run --project . --extra dev pytest tests/test_warehouse.py -k "집계 or 축별 or 기사_수로" -v
```

기대: `AttributeError: ... has no attribute 'aggregate'`.

- [ ] **Step 3: 집계를 구현한다**

판정 절 끝에 붙인다.
`import` 에 `from collections import Counter` 를 더한다.

```python
# 화면이 읽는 집계. 축 이름은 팩트의 컬럼 이름이고, 짝은 마트에서 같은 축을 세는
# 컬럼이다 — 클릭 수만으로는 「등급이 높을수록 더 눌리는가」 에 답할 수 없어서
# 기사 수로 나눈 값을 함께 낸다.
METRIC_AXES = (("card_outlet", "source_id"),
               ("card_stage", "transfer_stage"),
               ("card_tier", "journalist_tier"),
               ("card_surface", None))

EMPTY_LABEL = "(없음)"


def aggregate(facts: list[dict], articles: list[dict]) -> dict:
    """축별 클릭 수 · 기사 수 · 기사당 클릭.

    공개일 (2026-08-29) 을 뺀다 — 그 하루가 표본의 58% 라 평균을 왜곡한다.
    뺀 사실과 뺀 양을 `totals` 에 함께 실어 화면이 그대로 적을 수 있게 한다.
    """
    launch = LAUNCH_DATE.isoformat()
    counted = [f for f in facts if f.get("event_date_kst") != launch]

    axes = {}
    for axis, article_column in METRIC_AXES:
        clicks = Counter(f.get(axis) or EMPTY_LABEL for f in counted)
        denom = (Counter(str(a.get(article_column) or EMPTY_LABEL) for a in articles)
                 if article_column else Counter())
        rows = []
        for value, n in clicks.most_common():
            n_articles = denom.get(value, 0)
            rows.append({"value": value, "n_clicks": n, "n_articles": n_articles,
                         "per_article": round(n / n_articles, 2) if n_articles
                         else None})
        axes[axis] = rows

    days = sorted({f.get("event_date_kst") for f in facts if f.get("event_date_kst")})
    return {"totals": {"all": len(facts),
                       "launch_day": len(facts) - len(counted),
                       "counted": len(counted)},
            "dates": {"from": days[0] if days else None,
                      "to": days[-1] if days else None},
            "axes": axes}
```

- [ ] **Step 4: 떨어뜨리는 쪽을 구현한다**

적재 절 끝에 붙인다.
`import json` 을 더한다.

```python
# 화면이 읽는 자리. 회차의 렌더가 Iceberg 를 직접 읽으면 게이트 앞에 인증과
# 네트워크가 붙으므로 (모듈 첫 주석) 파일 하나를 사이에 둔다.
METRICS_PATH = Path("state/behavior_metrics.json")


def write_metrics(catalog, now: datetime) -> dict:
    """팩트와 마트 스냅샷에서 집계를 내어 JSON 으로 떨어뜨린다."""
    from pyiceberg.exceptions import NoSuchTableError

    try:
        facts = catalog.load_table(
            f"{BEHAVIOR_NS}.{FACT_TABLE}").scan().to_arrow().to_pylist()
    except NoSuchTableError:
        log.info("%s — 팩트가 아직 없다", METRICS_PATH)
        return {}

    try:
        snap = catalog.load_table(f"{NAMESPACE}.articles_snapshot")
        latest = _max_of(snap, LOADED_AT)
        articles = snap.scan(
            row_filter=EqualTo(LOADED_DATE, latest.date().isoformat())
        ).to_arrow().to_pylist() if latest else []
    except NoSuchTableError:
        articles = []

    metrics = aggregate(facts, articles)
    metrics["generated_at"] = now.isoformat()
    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    METRICS_PATH.write_text(json.dumps(metrics, ensure_ascii=False, indent=1),
                            encoding="utf-8")
    log.info("%s — 클릭 %d건 (공개일 %d건 제외) 기준 집계",
             METRICS_PATH, metrics["totals"]["counted"],
             metrics["totals"]["launch_day"])
    return metrics
```

`EqualTo` 는 `load_snapshot` 이 함수 안에서 들여오는 것과 같으므로 `write_metrics` 안에서도 `from pyiceberg.expressions import EqualTo` 를 들여온다.

`run_load` 의 갈래를 한 줄 늘린다.

```python
    try:
        load_ga4_events(catalog, now)
        build_gold(catalog, now)
        write_metrics(catalog, now)
    except Exception:
        log.warning("행동 기록 적재 실패 — 마트 이력 적재는 끝났다", exc_info=True)
```

- [ ] **Step 5: `state/` 를 무시 목록에 넣는다**

`.gitignore` 의 `site/` 아래에 넣는다.

```
state/
```

- [ ] **Step 6: 통과하는 것을 본다**

```bash
uv run --project . --extra dev pytest tests/test_warehouse.py -v
```

기대: 전량 PASS.

- [ ] **Step 7: 일부러 깨뜨려 확인한다**

`aggregate` 의 `counted` 를 `counted = facts` 로 바꾸고 돌린다.

```bash
uv run --project . --extra dev pytest tests/test_warehouse.py -k 공개일_클릭 -v
```

기대: FAIL.
확인 뒤 되돌린다.

- [ ] **Step 8: 커밋**

```bash
git add src/bullet_in/warehouse.py tests/test_warehouse.py .gitignore
git commit -m "feat(warehouse): 행동 지표 집계를 내고 화면이 읽을 파일로 떨어뜨린다"
```

---

## Task 9: 행동 지표 페이지

`write_ops` 가 운영 뷰를 만드는 자리에 페이지를 하나 더 그린다 (스펙 §3.8).

**Files:**
- Create: `src/bullet_in/serve/templates/behavior.html.j2`
- Modify: `src/bullet_in/serve/render.py` (`write_ops` 아래)
- Modify: `src/bullet_in/run.py:555-560`
- Test: `tests/test_behavior_view.py`

**Interfaces:**
- Consumes: `warehouse.METRICS_PATH` 가 만든 JSON 의 모양 (Task 8 의 예시)
- Produces:
  - `render.render_behavior(metrics: dict) -> str`
  - `render.write_behavior(metrics_path, out_dir) -> bool` — 그렸으면 True

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_behavior_view.py` 를 만든다.

```python
"""행동 지표 페이지 — 표본 수가 늘 함께 보이는지."""
import json

from bullet_in.serve.render import render_behavior, write_behavior

METRICS = {
    "generated_at": "2026-09-03T02:40:00+00:00",
    "totals": {"all": 587, "launch_day": 341, "counted": 246},
    "dates": {"from": "2026-08-24", "to": "2026-09-01"},
    "axes": {
        "card_outlet": [{"value": "The Athletic", "n_clicks": 31,
                         "n_articles": 24, "per_article": 1.29},
                        {"value": "BBC", "n_clicks": 12,
                         "n_articles": 0, "per_article": None}],
        "card_stage": [], "card_tier": [], "card_surface": [],
    },
}


def test_클릭_수_곁에_표본_수가_함께_나온다():
    html = render_behavior(METRICS)
    assert "31" in html and "24" in html and "1.29" in html


def test_공개일을_뺐다는_사실을_적는다():
    html = render_behavior(METRICS)
    assert "341" in html and "246" in html


def test_기사_수가_0이면_기사당_값을_안_적는다():
    html = render_behavior(METRICS)
    # BBC 행은 나오되 나눈 값 자리는 비어 있어야 한다 — 0으로 나눈 값을 지어내지 않는다.
    assert "BBC" in html
    assert "0.00" not in html


def test_검색엔진에_안_실리게_막는다():
    assert 'name="robots"' in render_behavior(METRICS)


def test_집계_파일이_없으면_페이지를_안_그린다(tmp_path):
    assert write_behavior(tmp_path / "없다.json", tmp_path) is False
    assert not (tmp_path / "behavior.html").exists()


def test_집계_파일이_있으면_페이지를_그린다(tmp_path):
    p = tmp_path / "m.json"
    p.write_text(json.dumps(METRICS), encoding="utf-8")
    assert write_behavior(p, tmp_path) is True
    assert "The Athletic" in (tmp_path / "behavior.html").read_text(encoding="utf-8")
```

- [ ] **Step 2: 실패하는 것을 눈으로 본다**

```bash
uv run --project . --extra dev pytest tests/test_behavior_view.py -v
```

기대: `ImportError: cannot import name 'render_behavior'`.

- [ ] **Step 3: 템플릿을 만든다**

`src/bullet_in/serve/templates/behavior.html.j2`.
`ops.html.j2` 의 스타일 규약 (같은 색 변수 · `.hbar` 막대) 을 그대로 쓴다.

```jinja
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>bullet-in 행동 지표</title>
<style>
  :root { --surface:#fcfcfb; --ink:#0b0b0b; --sec:#52514e; --mut:#898781;
          --grid:#e1e0d9; --line:#c3c2b7; --blue:#2a78d6; }
  @media (prefers-color-scheme: dark) {
    :root { --surface:#1a1a19; --ink:#fff; --sec:#c3c2b7; --grid:#2c2c2a;
            --line:#383835; --blue:#3987e5; }
  }
  body { margin:0 auto; max-width:860px; padding:24px 16px; background:var(--surface);
         color:var(--ink); font:14px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif; }
  header { display:flex; justify-content:space-between; align-items:baseline; }
  h1 { font-size:18px; margin:0; }
  h2 { font-size:14px; margin:22px 0 6px; }
  .mut { color:var(--mut); font-size:11px; }
  .note { color:var(--sec); font-size:12px; margin:10px 0 0; }
  table { width:100%; border-collapse:collapse; margin:4px 0; }
  th { text-align:left; font-weight:600; color:var(--mut); font-size:10px;
       text-transform:uppercase; letter-spacing:.04em; padding:4px 8px;
       border-bottom:1px solid var(--line); }
  td { padding:4px 8px; border-bottom:1px solid var(--grid);
       font-variant-numeric:tabular-nums; }
  td.n { text-align:right; width:64px; }
  .hbar { height:12px; background:var(--blue); border-radius:3px;
          display:inline-block; vertical-align:middle; }
  footer { margin-top:20px; border-top:1px solid var(--grid); padding-top:8px; }
</style></head>
<body>
<header>
  <h1>행동 지표</h1>
  <span class="mut">{{ metrics.generated_at }}</span>
</header>

<p class="note">
  {{ metrics.dates["from"] }}에서 {{ metrics.dates.to }}까지 클릭
  {{ "{:,}".format(metrics.totals.all) }}건 중 공개일
  {{ "{:,}".format(metrics.totals.launch_day) }}건을 뺀
  <strong>{{ "{:,}".format(metrics.totals.counted) }}건</strong> 기준이다.
  표본이 작아 한 자릿수 칸은 그대로 읽지 않는다.
  「기사당」 은 클릭을 그 축의 기사 수로 나눈 값이고, 노출 수가 아니라 기사 수라
  같은 기사가 여러 번 보인 것은 못 가른다.
</p>

{% for axis, title in axes %}
<h2>{{ title }}</h2>
{% set rows = metrics.axes.get(axis, []) %}
{% if rows %}
{% set top = rows[0].n_clicks %}
<table>
  <tr><th>{{ title }}</th><th>클릭</th><th>기사</th><th>기사당</th><th></th></tr>
  {% for r in rows %}
  <tr>
    <td>{{ r.value }}</td>
    <td class="n">{{ r.n_clicks }}</td>
    <td class="n">{{ r.n_articles or "" }}</td>
    <td class="n">{{ r.per_article if r.per_article is not none else "" }}</td>
    <td><span class="hbar" style="width:{{ (r.n_clicks / top * 160) | round | int }}px"></span></td>
  </tr>
  {% endfor %}
</table>
{% else %}
<p class="mut">아직 없다.</p>
{% endif %}
{% endfor %}

<footer class="mut"><a href="ops.html">수집 현황</a></footer>
</body>
</html>
```

- [ ] **Step 4: 렌더 둘을 더한다**

`render.py` 의 `write_ops` 아래에 붙인다.

```python
# 행동 지표 페이지의 축과 제목. 팩트의 컬럼 이름이 축이다.
BEHAVIOR_AXES = (("card_outlet", "매체"), ("card_stage", "이적 단계"),
                 ("card_tier", "기자 등급"), ("card_surface", "화면"))


def render_behavior(metrics: dict) -> str:
    return _env().get_template("behavior.html.j2").render(
        metrics=metrics, axes=BEHAVIOR_AXES)


def write_behavior(metrics_path: str | Path, out_dir: str | Path) -> bool:
    """집계 파일이 있으면 site/behavior.html 을 그린다.

    집계는 회차가 아니라 웨어하우스 타이머가 만든다. 파일이 없다는 것은 아직
    한 번도 안 돌았거나 그쪽이 실패했다는 뜻이고, 둘 다 회차를 멈출 이유는 아니다.
    """
    src = Path(metrics_path)
    if not src.exists():
        return False
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "behavior.html").write_text(
        render_behavior(json.loads(src.read_text(encoding="utf-8"))),
        encoding="utf-8")
    return True
```

`render.py` 는 `import json` 을 이미 갖고 있으므로 import 는 손댈 것이 없다.

- [ ] **Step 5: 회차에 붙인다**

`run.py` 의 `write_ops` 호출을 감싼 `try` 바로 아래에 같은 모양으로 붙인다.

```python
    # 행동 지표 (behavior.html): 웨어하우스 타이머가 떨어뜨린 집계를 읽어 그린다.
    # 파일이 없으면 안 그리고 넘어간다 — 그쪽 타이머는 회차와 따로 돈다.
    try:
        write_behavior("state/behavior_metrics.json", "site")
    except Exception:
        logging.getLogger(__name__).warning(
            "행동 지표 뷰 생성 실패 — 파이프라인은 계속 진행", exc_info=True)
```

`run.py:25` 의 import 에 `write_behavior` 를 더한다.

- [ ] **Step 6: 통과하는 것을 본다**

```bash
uv run --project . --extra dev pytest tests/test_behavior_view.py -v
```

기대: 전량 PASS.

- [ ] **Step 7: 일부러 깨뜨려 확인한다**

템플릿의 `<td class="n">{{ r.n_articles or "" }}</td>` 줄을 지우고 돌린다.

```bash
uv run --project . --extra dev pytest tests/test_behavior_view.py -k 표본_수가 -v
```

기대: FAIL (`24` 를 못 찾는다).
확인 뒤 되돌린다.

- [ ] **Step 8: 전체 테스트를 돌린다**

```bash
uv run --project . --extra dev pytest -q
```

기대: 기존 통과 수 + 새 테스트.
실패가 있으면 그 자리를 고치고 다시 돌린다.

- [ ] **Step 9: 커밋**

```bash
git add src/bullet_in/serve/templates/behavior.html.j2 src/bullet_in/serve/render.py \
        src/bullet_in/run.py tests/test_behavior_view.py
git commit -m "feat(serve): 행동 지표 페이지를 회차 렌더에 더한다"
```

---

## Task 10: 배포하고 실물로 확인한다

셋째 회차의 끝이다.

**Files:**
- Modify: `.env.example`
- Modify: `docs/runbook/2026-09-02-warehouse-history-load.md`

**Interfaces:**
- Consumes: Task 1에서 Task 9까지 전부
- Produces: 운영에서 도는 행동 기록 갈래와 배포된 페이지

- [ ] **Step 1: 설정 이름을 예시 파일에 적는다**

`.env.example` 에 더한다.

```
# 행동 기록 원본 (GA4 BigQuery 내보내기). 없으면 그 갈래를 건너뛴다.
GA4_DATASET=bullet-in-analytics.analytics_551139164
```

- [ ] **Step 2: 커밋하고 PR 을 올린다**

```bash
git add .env.example
git commit -m "chore(warehouse): 행동 기록 데이터셋 설정 이름을 예시에 적는다"
git push -u origin worktree-behavior-log
```

PR 본문은 `.claude/tools/check-pr-format.py --body <파일> --title "<제목>"` 을 통과시킨 뒤 올린다.
**머지는 사용자가 한다.**

- [ ] **Step 3: 머지된 뒤 VM 을 최신으로 만들고 설정을 넣는다**

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  "cd /home/ubuntu/bullet-in && git pull --ff-only && /home/ubuntu/.local/bin/uv sync"
```

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  "grep -q GA4_DATASET /home/ubuntu/bullet-in/.env || \
   echo 'GA4_DATASET=bullet-in-analytics.analytics_551139164' >> /home/ubuntu/bullet-in/.env"
```

- [ ] **Step 4: 적재를 손으로 한 번 돌린다**

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  "sudo systemctl start bullet-in-warehouse.service"
```

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  "journalctl -u bullet-in-warehouse.service -n 40 --no-pager"
```

기대: `ga4_events — 20260824 ... 적재` 가 날짜 수만큼 · `fact_card_click — N행 갈아 끼움` · `state/behavior_metrics.json — 클릭 N건 ... 기준 집계`.
**로그를 한 번만 받아 여러 번 세라** — 같은 명령을 다시 치면 창이 밀려 앞줄이 사라진다.

- [ ] **Step 5: 쌓인 것을 센다**

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  "env GOOGLE_APPLICATION_CREDENTIALS=/home/ubuntu/.bullet-in-lakehouse.json \
   ICEBERG_CATALOG_URI=https://biglake.googleapis.com/iceberg/v1/restcatalog \
   ICEBERG_WAREHOUSE=gs://bullet-in-lakehouse-prod \
   /home/ubuntu/.local/bin/uv run --project /home/ubuntu/bullet-in \
   python -m bullet_in.warehouse show"
```

기대: `behavior.ga4_events` 가 13,035행 안팎 (내보내기가 하루 더 도착했으면 그만큼 많다) · `behavior.fact_card_click` 이 587행 안팎.
**원본 행 수를 BigQuery 쪽과 대 본다.**

```bash
bq --project_id=bullet-in-analytics query --use_legacy_sql=false --format=pretty \
  'SELECT COUNT(*) AS n FROM `bullet-in-analytics.analytics_551139164.events_*`'
```

두 값이 다르면 그 차이가 실은 날짜 수 차이인지부터 본다.

- [ ] **Step 6: 회차를 돌려 페이지를 배포한다**

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  "sudo systemctl start bullet-in.service"
```

- [ ] **Step 7: 배포본에서 페이지를 확인한다**

```bash
curl -s https://bullet-in.pages.dev/behavior.html -o /tmp/behavior.html -w '%{http_code}\n'
```

```bash
grep -c '<tr>' /tmp/behavior.html
```

기대: `200` 과 축 넷의 행 수 합.
**받아 둔 파일을 여러 번 세고 curl 을 다시 치지 않는다.**

- [ ] **Step 8: 런북에 절을 더한다**

`docs/runbook/2026-09-02-warehouse-history-load.md` 에 행동 기록 갈래를 적는다.
설정 이름 · 손으로 돌리는 법 · 도착이 하루 늦다는 것 · 집계 파일의 자리와 그것을 읽는 쪽을 담는다.

`humanize-korean` fast 를 1회 통과시킨다 (`docs/` 는 서술형).

- [ ] **Step 9: 커밋하고 PR 을 올린다**

```bash
git add docs/runbook/2026-09-02-warehouse-history-load.md
git commit -m "docs(warehouse): 행동 기록 갈래의 운영 절차"
git push
```

---

## 실행하면서 바꾼 것

계획서를 쓸 때와 다르게 간 자리를 여기 남긴다.

| 무엇 | 계획서 | 실제 | 왜 |
| --- | --- | --- | --- |
| 네임스페이스 확보 | `run_load` 가 만든다 | `load_ga4_events` 가 스스로 만든다 | 부르는 쪽 순서에 기대면 이 갈래만 따로 못 돌린다 · 테스트가 바로 걸렸다 |
| `.env.example` 과 VM 설정 | Task 10 | 회차 1 | bronze 만 배포해도 자료가 그날부터 쌓이고 실물 경로가 두 회차 먼저 검증된다 |
| 워크트리의 파이썬 | 적지 않았다 | `uv venv --python 3.11` 로 고정 | `uv` 가 3.14 를 골라 메인 · VM · CI (전부 3.11.15) 와 다른 것을 재고 있었다 |

## 자기 점검

**스펙 덮기.**
§3.1 네임스페이스는 Task 2, §3.2 bronze 는 Task 4, §3.3 silver 는 Task 5와 Task 6, §3.4 적재 흐름은 Task 4, §3.5 gold 는 Task 7, §3.6 권한은 Task 1, §3.8 화면은 Task 9 가 맡는다.
§3.7 선수 카드 식별자는 PR #439 에서 이미 끝났다.
§4.2 미검증 셋은 Task 1 이 첫 태스크로 받는다.

**빈칸.**
「나중에」 · 「적절히」 로 넘긴 자리가 없는지 훑었다.
모든 코드 단계에 실제로 붙여 넣을 코드가 있고, 모든 검증 단계에 돌릴 명령과 기대하는 출력이 있다.

**이름이 어긋난 곳.**
`ensure_table(catalog, name, schema, namespace=...)` 의 인자 순서를 Task 2 · 4 · 6 · 7 이 같게 쓴다.
`GA4_TABLE` · `GA4_FLAT_TABLE` · `FACT_TABLE` · `DIM_DATE_TABLE` 은 Task 4 · 6 · 7 에서 같은 이름이다.
`METRICS_PATH` 의 값 (`state/behavior_metrics.json`) 이 Task 8 의 상수와 Task 9 의 `run.py` 호출에서 같다.

**남는 위험 하나.**
Task 1 의 중첩 커밋이 실패하면 Task 4 와 Task 5 의 경계가 무너진다.
그때는 원본 테이블을 두지 않고 평탄화본만 만드는 쪽으로 돌리며, 그 판단은 Task 1 의 출력을 보고 내린다.
