# 표기 사전 확장 절차 — 규모 측정 · 안전 검사 · 소급 (2026-08-29)

같은 대상이 기사마다 다른 한글 표기로 나올 때 `config/glossary.yaml` 을 늘리는 절차다.
안건 υ 회차 (PR #375 · #378 · #381) 에서 실제로 돌린 것을 일반화했다.

**이 절차의 값은 「무엇을 넣을까」 가 아니라 「넣기 전에 무엇을 대 보는가」 에 있다.**
넣어서 깨지는 자리가 실측으로 넷 나왔고, 그중 하나는 그대로 넣었으면 멀쩡한 문장 4개를 깨뜨릴 뻔했다.

## 1. 규모부터 잰다 — 제품이 쓰는 입력과 함수로

렌더된 HTML 이 아니라 제품의 서빙 경로를 그대로 부른다.

```python
from bullet_in.run import SERVING_SELECT_SQL, LINKED_HASHES_SQL, serving_rows
from bullet_in.storage.players import PlayerStore

with engine.connect() as c:
    rows = [dict(r) for r in c.execute(text(SERVING_SELECT_SQL)).mappings().all()]
    linked = set(c.execute(text(LINKED_HASHES_SQL)).scalars().all())
fm = next(s["config"] for s in cfg["sources"] if s["source_id"] == "fmkorea")
kept, hidden, stale = serving_rows(rows,
    relevance_terms=fm.get("relevance_terms") or [],
    player_names=PlayerStore(engine).confirmed_ko_names(), linked=linked)
```

`serving_rows` 는 값을 **셋** 돌려준다 (남길 행 · 무관 제외 · 옛 글 제외).
런북 스니펫을 손으로 옮기지 말고 `confirm_player._render(engine)` 을 부르는 편이 낫다
— 그 함수가 `run.py` 서빙 경로와 1:1 로 유지되는 유일한 자리다.

축을 갈라 센다.
**사람 (서빙 사전 안 · 밖) · 구단 · 매체 · 기자 · 경기장**은 정본이 서로 다르기 때문이다.
안건 α (기자명) 와 γ (언론사) 가 이미 다룬 축은 남은 것이 적다.

## 2. 후보를 만든다 — 그리고 꼬리까지 읽는다

자모 편집거리로 후보 쌍을 뽑는다.
후보 목록은 길다 (이번 회차 2,694쌍).

**빈도순으로 정렬해 놓고 상위만 읽으면 안 된다.**
이번에 상위 60줄만 읽고 20종 안팎을 통째로 놓쳤다.
사용자가 특정 이름을 되물어서야 드러났다.

읽을 만한 분량으로 줄이는 방법 둘이다.

- **앵커를 사전의 통용 값으로 잡는다** — 이미 등재한 값 곁의 미등재 변이를 훑는다.
군 안에서 빈도 높은 변이만 옮겨 적다가 1~2행짜리를 흘리는 일을 막는다.
- **이름꼴 조건을 걸어 거른다** — 조사 · 어미로 끝나지 않고 코퍼스 최빈어가 아니며 외래어 음절 비율이 높은 것.

## 3. 넣기 전 검사 넷 — 하나라도 빠뜨리면 깨진다

### 3.1. 치환될 자리를 전수로 읽는다

오표기가 나온 모든 자리를 앞뒤 문맥과 함께 출력해 눈으로 읽는다.
**이 검사 하나가 이번에 넷을 걸러냈다.**

```
[스포팅]  4자리 · 전부 다른 뜻
     …MLS)의 스포팅 캔자스 시…       ← 스포팅 캔자스 시티 (MLS 구단)
     …아 베르타 스포팅 디렉터는 …     ← 직책
```

「스포팅 → 스포르팅」 을 넣었으면 멀쩡한 문장 4개가 깨졌다.
같은 갈래로 「에미레이트」 홑말도 뺐다 (86자리 중 21자리가 「에미레이트 항공」 · 항공사 공식 한글명).

### 3.2. 같은 대상인지 원문으로 확인한다

번역문 빈도가 아니라 원문의 영문 이름으로 판정한다.

```
콘사 / 콴사              → 원문 Konsa 81행 · Quansah 18행   ← 다른 선수
니코 윌리암스 / 네코 윌리엄스 → 원문 Nico 7행 · Neco 1행        ← 다른 선수
```

**원문을 자르고 검색하지 않는다.**
`LEFT(body_source, 700)` 으로 앞부분만 보고 「원문에 없다」 고 단정했다가 뒤집혔다.

**기각한 쌍도 검수한다.**
채택은 결과가 눈에 보여 저절로 검수가 되고, 기각은 아무 일도 안 일어나 그냥 지나친다.

### 3.3. 통용 값을 고르지 말고 가져온다

정본이 이미 저장소에 있다.

| 축 | 정본 |
| --- | --- |
| 사람 | `players.ko_full_name` · `ko_name` |
| 구단 | `config/club_map.yaml` 키 |
| 기자 · 매체 | `config/credibility.yaml` 별칭 |

**정본과 화면 다수가 어긋나면 사용자에게 묻는다.**
이번에 다섯이 그랬고 (니코 윌리암스 · 엔조 마레스카 · 사비 알론소 · 에미레이츠 스타디움 · 주제 무리뉴) 임의로 고르지 않았다.
사용자가 화면 다수를 고른 항목은 `players` 쪽 값도 함께 고쳐야 정본이 하나로 남는다 (별도 승인 · 안건 χ).

### 3.4. `club_map` 짝과 게이트 계수

구단 표기를 넣으면 **같은 PR 에서 `club_map` 에 원문 쪽 표기를 함께 등재한다** (규칙 ④ · 별칭 목록 동일).
안 하면 게이트가 오탐하고 기사의 `title_ko` 가 NULL 이 된다.
정본은 `docs/troubleshooting/2026-08-29-a-dictionary-entry-changes-what-the-next-gate-sees.md` 다.

넣기 전후로 게이트 계수를 잰다.
**총량이 아니라 어느 기사에서 늘고 줄었는지**를 본다.

## 4. 순서 · 순환 · 멱등

- **긴 표기를 먼저 둔다** — 짧은 표기가 앞서면 긴 규칙이 안 걸린다 (`메리에르` 가 `메리에` 보다 앞).
- **방향을 뒤집을 때는 역방향 규칙을 반드시 지운다** — 두 줄이 서로를 되돌려 사전이 순환한다.
기존 멱등 테스트가 잡지만, 지우는 일을 절차에 넣어 둔다.
- **홑말 키는 전량 대조 뒤에만 쓴다.**
「조제 무리뉴」 를 「주제 무리뉴」 로 바꿀 때 홑말 「조제」 를 키로 잡았으면
울브스 골키퍼 **조제 사 (José Sá)** 가 깨졌다 (실측 1자리).

## 5. 소급 — 백업 · dry-run · 직전 재계수 · 잔존 0

사전은 새 기사만 고친다.
저장된 행은 따로 태워야 하고 **운영 데이터 수정이라 대상 수를 세어 보이고 승인을 받는다.**

```bash
# 1. 백업 (articles 만 · 시각 포함 파일명)
ssh <vm> 'set -a; . ~/bullet-in/.env; set +a
  PW=$(printf "%s" "$MARIADB_URL" | sed -E "s#.*://[^:]+:([^@]+)@.*#\1#")
  TS=$(date +%Y%m%d_%H%M%S)
  docker exec bullet-in-mariadb-1 mariadb-dump -uroot -p"$PW" bulletin articles \
    > ~/backups/<이름>_backup_${TS}.sql'

# 2. dry-run → 3. 직전 재계수 → 4. 실행 → 5. 재실행으로 잔존 0 확인
```

- **치환은 제품 함수를 그대로 부른다** (`enrich.apply_glossary`).
여기서 규칙을 다시 구현하면 두 벌이 된다.
- **사전은 워크트리의 committed config 에서 읽는다.**
PR 내용과 어긋나는 일이 없게 한다.
- **직전에 다시 센다.**
회차나 다른 세션의 병합으로 대상 수가 움직인다.
- **`summary3_ko` 는 JSON 이 아니라 줄바꿈으로 이은 평문이다.**
JSON 으로 검사하면 전건이 「깨짐」 으로 나오는 헛경보가 뜬다.

### 5.1. 소급한 텍스트는 해시가 바뀌면 날아간다

`MartStore` 의 upsert 가 이렇게 생겼다 (`storage/mariadb.py`).

```sql
ON DUPLICATE KEY UPDATE
   title_ko=IF(articles.content_hash=VALUES(content_hash), articles.title_ko, NULL),
   summary_ko=..., summary3_ko=..., body_ko=...,   -- 같은 꼴
   content_hash=VALUES(content_hash)
```

**해시가 달라지면 번역 4필드가 NULL 로 지워지고 그 기사는 다시 번역된다.**
소급이 고친 것이 바로 그 네 필드다.

- `content_hash` 는 원문 제목과 정규화된 URL 로 만든다.
그래서 **원문 제목이 바뀌거나 URL 정규화 규칙이 바뀌면** 재수집 때 해시가 갈린다.
- **그래도 소급이 헛일이 되지는 않는다** — 사전이 배포돼 있으면 재번역이 통용 표기로 나온다.
- **뒤집어 말하면 사전 배포 없이 소급만 하면 그 고침은 취약하다.**
소급과 사전 머지를 같은 회차 안에 두는 편이 낫다.
- **해시 재료가 둘이라 방아쇠도 둘이다** — `content_hash = sha256(원문 제목 | canonical_url)`.
어느 쪽이 바뀌어도 그 기사의 번역이 지워지고 다시 번역된다.

| 방아쇠 | 누가 당기나 | 실물 (2026-08-29) |
| --- | --- | --- |
| **정규화된 URL 이 바뀐다** | 사람이 주소를 고치거나 `canonical_url` 규칙이 바뀐다 | 병렬 세션의 주소 재정규화가 기사 하나를 재번역 경로로 밀어 넣었고 거기서 `club_map` 짝 누락이 드러났다 |
| **원문 제목이 바뀐다** | **아무도 안 건드려도 난다** — 트윗이 수정되거나 파서 산출이 달라진다 | 18:02 회차에 afcstuff 행의 해시가 갈렸다 (`09f700c8` → `1a21f0d6`) · **URL 은 `x.com` 이라 위 재정규화 대상이 아니었고 `canonical_url` 개정도 skysports 전용이었다** |

- **그래서 「옆에서 주소를 고치는 작업이 도는가」 만 묻는 것으로는 모자란다.**
원문 제목 쪽은 물어볼 상대가 없다.
**사전을 먼저 배포해 두는 것이 유일한 일반 방어다** — 그러면 어느 방아쇠가 당겨져도 재번역이 통용 표기로 나온다.
- **주소를 고치는 쪽은 `migrate_url_identity` 를 쓴다** — 해시를 미리 맞춰 두면
다음 수집 때 `IF()` 조건이 참이 되어 번역이 보존된다.
기전은 `docs/troubleshooting/2026-08-29-the-rule-moved-but-the-stored-addresses-did-not.md` 에 있다.
- **18:02 건의 방아쇠가 트윗 수정인지 파서 산출 차이인지는 확인하지 않았다.**
파서 쪽을 볼 일이 있으면 그 자리다.

## 6. 배포 뒤 — 첫 회차를 자기 축으로 읽는다

- **VM `git pull` 뒤 로더를 직접 불러 적용값을 확인한다.**
파일이 도착한 것과 값이 적용되는 것은 다른 확인이다.
- **`club_map` 만 바뀌었으면 재렌더가 필요 없다** — 렌더 산출물에 안 쓰인다.
- **첫 회차 저널을 직접 읽는다.**
`success_rate` 1.0 이어도 내 축의 WARNING 은 따로 봐야 한다.
이번에 그 안에 게이트 오탐이 들어 있었다.
- **회차가 새로 세운 기사만 골라 옛 표기가 남았는지 센다.**
사전이 배선에 그치지 않고 실제로 도는지는 여기서만 보인다.

## 7. 사라진 상세 페이지를 되짚어야 할 때

**지금은 저널이 지운 파일명을 남긴다** (PR #377).
개수 줄 뒤에 열 개씩 끊어 붙는다.

```
INFO 잔여 페이지 6건 삭제 (DB 에서 빠진 기사)
INFO 잔여 페이지 삭제 목록 1-6 <해시>.html <해시>.html …
```

**아래 배포 이력 대조는 #377 이전 구간을 되짚을 때 쓴다.**
그때는 개수만 남아 있어 다른 방법이 없다.

**Cloudflare 배포는 각각 불변 URL 로 남는다.**
두 배포의 `all` 페이지에서 기사 해시를 뽑아 대면 무엇이 사라졌는지 나온다.

```python
import re
hashes = lambda f: set(re.findall(r"article/([0-9a-f]{64})", open(f).read()))
gone = hashes("before.html") - hashes("after.html")
```

제약 둘이다.
두 배포 URL 을 알아야 하고 Pages 보존 기간에 매인다.

**사라진 해시가 곧 사라진 기사는 아니다.**
`content_hash = sha256(원문 제목 | canonical_url)` 이라 원문 제목이나 정규화된 URL 이 바뀌면 해시가 바뀐다.
같은 URL 이 새 해시로 살아 있는지 먼저 본다.

**해시가 갈리는 기전은 upsert 다** (2026-08-29 에 병렬 세션이 확정했다).
`storage/mariadb.py` 의 `ON DUPLICATE KEY UPDATE` 마지막 줄에 `content_hash=VALUES(content_hash)` 가 있다.
URL 을 손으로 고친 행은 다음 재수집 때 같은 행이 새 해시로 다시 이름 붙고,
옛 해시의 상세 페이지와 `article_players` 가 함께 고아가 된다.

- 실측 — 주소 110행을 고친 뒤 두 회차 만에 **17행 중 8행의 해시가 갈렸고 고아 귀속이 213 → 256** 이 됐다.
- **주소를 고칠 때는 `migrate_url_identity` 를 쓴다** — 주소 · 해시 · 참조 둘을 한 트랜잭션에서 함께 옮긴다.
`UPDATE ... SET url = ...` 만 돌리면 위 고아가 생긴다.

관련 = `docs/runbook/2026-08-08-onetime-db-batch-via-tunnel.md` (터널 · 백업 일반 절차)
· `docs/troubleshooting/2026-08-29-a-dictionary-entry-changes-what-the-next-gate-sees.md`
· `docs/runbook/2026-07-19-enrich-only-pass.md` (재렌더)
