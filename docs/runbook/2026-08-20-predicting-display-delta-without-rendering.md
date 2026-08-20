# 렌더 없이 표시 델타를 미리 재는 절차 (2026-08-20)

설정 변경이 화면을 어떻게 바꾸는지 **머지 전에** 알고 싶을 때 쓴다.
운영 저장값을 읽어 표시 함수를 직접 부른 뒤 바뀌기 전과 후를 대조한다.

**실측으로 값을 확인한 절차다** — 언론사 24종 등재 (#306) 의 델타를 이 방법으로 예고했더니 배포 뒤 회차 산출물이 그 예고와 전부 맞았다.

## 1. 언제 이 절차를 쓰는가

이미 있는 무거운 절차와 갈라 쓴다.

| 절차 | 무엇이 필요한가 | 무엇을 답하나 |
| --- | --- | --- |
| 운영 사본 렌더 (`2026-08-11-premerge-screen-check-with-prod-copy.md`) | DB 사본 복제 · 전체 렌더 · 브라우저 | 화면 그대로 · 배치 · 상호작용까지 |
| **이 절차** | ssh 터널 + 파이썬 몇 줄 | **표시명이 어떻게 바뀌는지 (델타)** |

**표시명 · 접기 · 항목 수만 보면 되는 변경에 쓴다** (등재 · 별칭 추가 · 저장값 정정).
배치 · 정렬 · 배지 위치처럼 눈으로 봐야 하는 것은 사본 렌더로 간다.

## 2. 절차

### 2.1. 터널을 세션 전용 포트로 연다

```bash
ssh -i ~/.ssh/seoulnow_deploy -o ExitOnForwardFailure=yes -f -N \
  -L 3319:127.0.0.1:3306 ubuntu@155.248.164.17
```

포트는 세션마다 다르게 잡는다 — 남의 터널에 붙으면 그쪽이 닫을 때 끊긴다.
읽기만 하므로 백업은 필요 없다.

### 2.2. 바뀌기 전 설정을 뜬다

```bash
git show origin/main:config/credibility.yaml > /tmp/cred_before.yaml
```

**기준선은 `origin/main` 이다.**
내 브랜치에서 뜨면 이미 바뀐 값이 들어온다.

### 2.3. 서빙이 쓰는 것과 같은 입력으로 부른다

```python
import sys; sys.path.insert(0, 'src')
from sqlalchemy import create_engine, text
from bullet_in.credibility import outlet_directory, journalist_directory
from bullet_in.serve.render import outlet_display
from bullet_in.run import serving_rows, SERVING_SELECT_SQL, LINKED_HASHES_SQL
from bullet_in.storage.players import PlayerStore

eng = create_engine("mysql+pymysql://root:<pw>@127.0.0.1:3319/bulletin")
with eng.connect() as c:
    rows = [dict(r) for r in c.execute(text(SERVING_SELECT_SQL)).mappings().all()]
    linked = set(c.execute(text(LINKED_HASHES_SQL)).scalars().all())

# 명단은 설정이 아니라 DB 에서 온다 (§3.2)
names = PlayerStore(eng).confirmed_ko_names()
kept, hidden = serving_rows(rows, relevance_terms=terms, player_names=names, linked=linked)

def tally(cfg_path):
    d, jd = outlet_directory(cfg_path), journalist_directory(cfg_path)
    # 인자를 write_site 와 1:1 로 맞춘다 (§3.1)
    return Counter(outlet_display(r, sources, directory=jd, outlet_dir=d) for r in kept)
```

### 2.4. 전후를 집합으로 대조한다

```python
b, a = tally("/tmp/cred_before.yaml"), tally("config/credibility.yaml")
print("사라진 항목:", sorted(set(b) - set(a)))
print("새로 생긴 항목:", sorted(set(a) - set(b)))
print("건수가 바뀐 항목:", {k: (b[k], a[k]) for k in set(a) & set(b) if a[k] != b[k]})
```

### 2.5. 끝나면 터널을 닫는다

```bash
pkill -f "ssh.*3319:127.0.0.1:3306"
```

## 3. 반드시 밟는 함정 둘

### 3.1. 표시 함수의 인자를 호출부와 1:1 로 맞춘다

`outlet_display` 는 사전을 **둘** 받는다.

| 인자 | 없으면 |
| --- | --- |
| `directory` (기자 소속) | X 소스 행이 인용 기자 소속으로 접히는 경로를 못 타고 소스 폴백 (`display_name`) 으로 떨어진다 |
| `outlet_dir` (언론사 표기) | 표기 접기와 조직 계정 핸들 접기가 빠진다 |

**하나만 빠져도 없던 표시명이 생긴다.**
실제로 `directory` 를 빼고 재니 항목이 48종이 아니라 49종으로 나왔다.
늘어난 하나는 `David Ornstein (X)` 이었다.

**호출부는 `run.py` 의 `write_site(...)` 다** — 거기 인자 목록을 그대로 베낀다.

### 3.2. 파이프라인 입력의 출처를 코드에서 확인한다

`serving_rows` 의 `player_names` 는 `config/sources.yaml` 이 아니라 **운영 DB 명단**에서 온다.

```python
adapters = build_adapters(cfg, fmkorea_player_names=pstore.confirmed_ko_names())   # run.py
```

설정에서 읽으면 이름 매칭이 통째로 빠져 **조용히 과잉 필터**가 된다.
실측에서 숨김이 26건으로 나왔는데 운영 로그의 실제 값은 20건이었다.

**맞았는지 확인하는 법** — 회차 로그의 「fmkorea 무관 글 서빙 제외 N건」 과 숨김 수를 맞춰 본다.
붙으면 같은 필터를 돌린 셈이다.

## 4. 이 절차가 답하는 것과 못 답하는 것

| 물음 | 답하나 |
| --- | --- |
| 어떤 표기가 사라지고 무엇이 새로 서는가 | **답한다** |
| 항목 수가 늘거나 주는가 · 병합이 나는가 | **답한다** |
| 카드 건수가 어떻게 옮겨 가는가 | **답한다** |
| 사이드바 항목의 절대 수 | **인자를 정확히 맞췄을 때만** (§3.1) |
| facet 정렬 · 접힘 · 「기타」 처리 | **못 답한다** — 사본 렌더로 간다 |

**델타는 인자를 빠뜨려도 맞을 수 있다.**
전후 양쪽을 같은 (틀린) 호출로 재면 그 오류가 상쇄되기 때문이다.
그래서 **절대값을 한 번은 다른 방법으로 확인한다** (배포된 산출물의 태그를 세거나 배포 세션의 값과 대조한다).

## 5. 실측 근거 — #306 의 예고와 회차 결과

| 값 | 이 절차의 예고 | 배포 뒤 회차 |
| --- | --- | --- |
| 언론사 항목 총수 | 불변 (16종 1대1 교체) | **48 → 48** |
| `Marca` | 11 | **11** |
| 표기가 바뀐 카드 | 33 저장값 + 1 핸들 | **34장** |
| 공신력 배지 | 무이동 | **0장** |
| 등재에서 뺀 `A BOLA` · 「빌트」 | 남아 있어야 함 | 각 1건 그대로 |

**`Marca` 만 10 이 아니라 11 이었다.**
`@marca` 를 인용한 트윗 1건이 조직 계정 핸들 접기 경로로 함께 들어왔다.
예고 단계에서 이 값이 튀어 원인을 찾아 두었으므로 회차에서 놀라지 않았다.

**예상 밖 값이 나오면 반례로 읽기 전에 원인을 찾는다** — 별칭을 더하면 **접기 (항목이 준다) 와 신설 (항목이 는다) 이 함께 일어난다.**
같은 회차의 기자 등재에서도 항목이 203 → 205 로 늘었다 (늘 공저자 자리라 대표가 된 적 없던 이름이 대표 자격을 얻는다).
**「몇 종이 줄어든다」 로 규모를 예상하면 빗나간다.**

## 6. 배포 세션에 넘길 때

이 절차의 값은 **예고**다.
배포와 회차 확인을 다른 세션이 맡으면 **잣대를 함께 넘긴다.**

- 무엇을 쟀는가 (저장값 + 함수 · 렌더 산출물이 아님)
- 무엇이 판정 기준인가 (예: 「언론사 항목 총수 불변」)
- 예상 밖으로 보일 값과 그 원인 (예: 「`Marca` 는 10 이 아니라 11」)

**잣대를 안 붙여 보내면 받는 쪽이 자기 잣대의 값으로 옮겨 적는다** (`2026-08-20-the-check-ran-but-asked-the-wrong-thing.md` §5).

## 7. 참조

- 무거운 절차 — `docs/runbook/2026-08-11-premerge-screen-check-with-prod-copy.md`.
- 인자 · 기준선 · 입력 출처를 잘못 잡은 사례 — `docs/troubleshooting/2026-08-20-the-check-ran-but-asked-the-wrong-thing.md`.
- 측정 코드가 서빙 코드를 우회하는 자리 — `docs/troubleshooting/2026-08-14-suspect-the-yardstick-not-the-data.md`.
- 터널 · 백업 · 실행 창 — `docs/runbook/2026-08-08-onetime-db-batch-via-tunnel.md`.
