# 잘린 채 저장된 트윗 원문을 되돌리는 절차 (2026-08-30)

수집이 트윗을 잘라 저장한 행을 전문으로 바꾸는 일이다.
원인과 배경은 `docs/troubleshooting/2026-08-30-the-timeline-handed-us-half-a-tweet.md` 에 있다.

**값 하나를 고치는 일이 아니라 신원을 옮기는 일이다.**
`content_hash = sha256(원문 제목 | canonical_url(url))` 이라 제목을 고치면 해시가 갈리고,
그 해시를 `article_players` (PK 의 한 축) · `players.first_seen` · 상세 페이지 파일명이 참조한다.
주소 축의 같은 절차는 `2026-08-29-url-identity-migration.md` 에 있다.

## 1. 대상을 실물로 판정한다

**대리 지표로 세면 모자란다.** 따옴표 불균형으로 세면 30건인데 실물은 43건이었다
(잃은 부분이 출처 대괄호뿐인 경우를 원리상 못 본다).

`status` 페이지를 열어 저장값과 길이를 대 본다. 대상은 **임계 260자 이상**만 본다
— 타임라인이 자르는 지점이 고정이라 (저장 최대 280자) 그 아래는 잘릴 자리가 없다.
**이건 추론이고 전수 확인이 아니다.**

```bash
# 세션 스크래치의 probe 스크립트와 같은 모양 — 상태 파일을 두어 중간에 끊겨도 이어서 받는다
#   대상: partition_bodyless_tweets 로 고른 행 중 needs_expansion 이 참인 것
#   요청 간격 1.2초 · 결과는 {content_hash: 전문} 으로 저장
```

- 라이브 요청이 **91회**였다. afcstuff 접근은 막힌 이력이 있으니 한 번만 돌린다.
- 받은 것은 전부 파일로 남기고 **확인 목적으로 다시 받지 않는다.**
- 길이 차이가 **공백뿐인 행은 뺀다** (2026-08-30 에 44건 중 2건).

## 2. 백업 — 표 셋을 함께 뜬다

`articles` 만 뜨면 참조 이동을 못 되돌린다.

```bash
ssh <vm> 'mkdir -p ~/backups && set -a && . ~/bullet-in/.env && set +a
  PW=$(printf "%s" "$MARIADB_URL" | sed -E "s#.*://[^:]+:([^@]+)@.*#\1#")
  TS=$(date +%Y%m%d_%H%M%S)
  docker exec bullet-in-mariadb-1 mariadb-dump -uroot -p"$PW" bulletin \
    articles article_players players > ~/backups/tweet_fulltext_backup_${TS}.sql'
```

## 3. 브랜치 코드로 돌리되 VM 체크아웃은 안 바꾼다

정기 회차가 `~/bullet-in` 을 그대로 실행하므로 그 체크아웃을 미머지 브랜치로 바꾸면 안 된다
(`2026-08-08-onetime-db-batch-via-tunnel.md` §1). 터널이 막힌 환경이면 경로로 같은 목적을 이룬다.

```bash
tar czf /tmp/newsrc.tgz -C src bullet_in
scp /tmp/newsrc.tgz <vm>:/tmp/
ssh <vm> 'rm -rf /tmp/newsrc && mkdir -p /tmp/newsrc && tar xzf /tmp/newsrc.tgz -C /tmp/newsrc'
```

**어느 파일이 import 됐는지 찍어서 확인한다.**
editable 설치가 경로 우선순위를 가져갈 수 있어, 안 찍으면 「새 코드로 돌렸다」 가 확인이 아니라 가정이 된다.

```python
import sys; sys.path.insert(0, "/tmp/newsrc")
import bullet_in.backfill_tweet_full_text as bf
print("import 된 backfill:", bf.__file__)
assert bf.__file__.startswith("/tmp/newsrc"), "옛 코드가 잡혔다 — 중단"
```

## 4. dry-run 으로 대상 수를 세어 보이고 승인을 받는다

운영 데이터 수정이다. 실행 직전에 다시 센다 — 회차나 다른 세션이 대상 수를 움직인다.

```bash
uv run python -m bullet_in.backfill_tweet_full_text --texts full.json --dry-run
# 대상 43건 · 적용 예정 43건 (해시 갈림 43건) · 건너뜀 0건
```

배치가 건너뛰는 세 경우를 사유와 함께 돌려준다.

- 전문이 더 길지 않음 (이미 반영됐거나 잘린 적 없음 · 멱등)
- 새 해시가 이미 다른 행의 것 (그 자리로 옮기면 남의 행을 덮는다)
- 전문을 안 받은 행

## 5. 실행 — 한 트랜잭션에서 넷을 함께

`backfill_tweet_full_text` 가 행마다 이렇게 한다.

1. `content_hash` 를 새 제목으로 다시 계산
2. **참조를 먼저 옮긴다** (`migrate_url_identity._move_refs` 재사용) — 순서가 뒤바뀌면 그 사이에 고아가 생긴다
3. `title_original` 과 `content_hash` 를 갱신
4. **번역 4필드를 NULL 로** — 원문이 달라졌으니 옛 번역은 다른 글의 번역이다

## 6. 대조 잣대 — 총량이 아니라 자리

**고아는 「0」 이 아니라 「증가 0」 을 본다.** 기존 고아가 이미 있다 (2026-08-30 에 259건).

```
before: {'articles': 933, 'article_players': 3632, 'orphans': 259, 'first_seen_set': 488}
after : {'articles': 933, 'article_players': 3627, 'orphans': 253, 'first_seen_set': 488}
```

**고아가 줄면 그것도 파고든다.** 2026-08-30 에 6건 줄었는데, 파 보니 새 해시 넷이
소급 이전 `article_players` 에 있었고 `articles` 에는 없었다
— 그 트윗들이 예전에 전문으로 수집돼 있었다는 증거였고, 해시 왕복의 원인을 밝히는 실마리가 됐다.
귀속 행이 5건 준 것은 `UPDATE IGNORE` 가 같은 선수 중복을 병합한 결과다.

## 7. 회차 · 배포 순서

**수집 수정이 배포된 뒤에 회차가 와야 한다.**
소급한 행 중 아직 타임라인에 남아 있는 것이 있으면, 옛 코드로 도는 회차가 다시 잘라 되돌린다
(2026-08-30 에 43건 중 1건이 그 상태였다).

1. 코드 머지 → VM `git pull`
2. **코드가 도착했는지 인터프리터로 확인** — 파일이 최신인 것과 값이 읽히는 것은 다르다
3. 회차를 기다린다 (소급이 번역을 NULL 로 밀었으므로 회차가 새 원문으로 다시 만든다)
4. 회차 뒤 저널 · DB · **렌더된 화면**을 본다

## 8. 확인할 것

- 저널에 `트윗 펼침 status_id=… N자 → M자` 가 남는가
- `title_ko` 가 비어 있던 행이 0 이 됐는가
- **주소가 바뀌었다** — 해시가 갈렸으므로 옛 상세 페이지 URL 은 404 다
- 렌더된 화면에서 지어낸 문장이 사라졌는가 (DB 값만 보고 판정하지 않는다)

## 9. 이 절차가 안 보는 것

- **기자 타임라인 경로** — `_scrape_journalists` 가 읽는 텍스트도 접힐 수 있다 (미확인)
- **임계 아래** — 260자 미만은 안 열어 봤다 (잘릴 자리가 없다는 추론)
- **옛 주소로 들어오는 방문자** — 리다이렉트를 두지 않았다
