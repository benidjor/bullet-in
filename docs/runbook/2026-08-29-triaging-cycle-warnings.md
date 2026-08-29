# 회차가 남긴 경고를 사람이 확인하는 절차 (2026-08-29)

회차는 정상 종료해도 「사람이 봐야 할 것」 을 로그에 남긴다.
2026-08-29 06:02 회차를 실제로 훑으면서 밟은 절차를 경고 종류별로 적는다.
경고마다 확인할 자리가 다르고, 그중 둘은 엉뚱한 자리를 보면 「문제 없음」 이 나온다.

## 0. 준비

VM 접속은 `ubuntu@155.248.164.17` · 키 `~/.ssh/seoulnow_deploy`.

- **DB 클라이언트 이름은 `mariadb` 다** — 컨테이너에 `mysql` 이 없다 (`executable file not found`).
- **호스트에는 클라이언트가 없다** — 반드시 `docker exec bullet-in-mariadb-1` 을 거친다.
- **긴 본문을 꺼낼 때는 `TO_BASE64` 로 감싼다** — 본문에 탭 · 줄바꿈이 들어 있어 TSV 가 깨진다.
`TO_BASE64` 는 76자마다 줄바꿈을 넣으므로 `REPLACE(TO_BASE64(x), "\n", "")` 로 벗긴다.

회차 로그는 이렇게 뜬다.

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'journalctl -u bullet-in.service --since "2026-08-29 06:02" --until "2026-08-29 06:07" --no-pager -o cat'
```

## 1. 회차 자체가 정상이었는지

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'systemctl show bullet-in.service -p Result -p ExecMainStartTimestamp -p ExecMainExitTimestamp'
```

`Result=success` 이고 로그 끝의 요약 (`{'new_or_changed': N, 'errors': {}, 'success_rate': 1.0}`) 과 wrangler 업로드 줄이 있으면 수집부터 배포까지 다 돈 것이다.

## 2. 신선도 stale — 어댑터를 단독으로 돌려 가른다

```
INFO 신선도 판정: 감시 7소스 · stale 1 · 발송 0 · 재알림 대기 1 [bbc_sport 93.1h — 다음 알림까지 26.9h]
```

**워터마크의 뜻을 먼저 안다.** 판정 기준은 Mongo `raw_items` 의 소스별 `MAX(fetched_at)` 이고, 중복 `content_hash` 는 저장을 건너뛴다.
그래서 이 값은 **「그 소스에서 처음 보는 내용을 마지막으로 받은 때」** 다.
같은 회차에 그 소스의 후보가 잡혀 있어도 이미 본 기사면 워터마크는 안 움직인다 — 모순이 아니다.

가를 것은 하나다.
**소스가 정말 새 기사를 안 낸 것인가, 아니면 셀렉터가 드리프트해 목록을 못 읽는 것인가.**
단위 테스트는 모킹이라 이것을 못 잡으므로 어댑터를 단독으로 돌린다.

```python
# 목록 셀렉터 · 제목 셀렉터 · 제목 키워드 필터를 단계별로 센다
items = soup.select(cfg["item_selector"])
for a in items:
    t = a.select_one(cfg["title_selector"])
```

**여기서 밟은 함정** — 목록 셀렉터가 11건을 잡고 그중 8건에서 제목이 안 잡히는 것을 보고 드리프트로 읽었다.
실제로는 그 8건이 「Read more」 · 「Want more transfer stories?」 같은 **본문 안 링크**였고, 기사 카드는 3건뿐이었다.
셋 중 이적 키워드를 통과한 1건의 발행 시각이 워터마크와 맞아떨어져 **경보가 참**이었다.

- **링크 수와 카드 수를 가르기 전에 드리프트라고 부르지 않는다.**
- 임계는 소스마다 다르고 임시로 낮춰 둔 자리가 있다 (`config/sources.yaml` 의 `freshness_hours` 주석을 함께 읽는다).

## 3. 재작성 게이트 잔존 — 원문과 번역을 나란히 잘라 본다

```
WARNING 재작성 게이트 잔존 content_hash=... 잔존율=0.437 누락=['2023', '24'] 시도=3
```

**잔존율이 임계 (0.75) 아래여도 이 경고는 뜬다.** 조건이 OR 이라 누락 · 신규 수치 · 인용 훼손 · 인명 · 구단 다섯 축 중 하나만 걸려도 남는다.
그러니 **잔존율 숫자가 아니라 걸린 축을 먼저 읽는다.**

```bash
docker exec bullet-in-mariadb-1 mariadb -uroot -pbulletin bulletin -N -B -e \
  'SELECT content_hash, source_id, LEFT(title_ko,60), url FROM articles WHERE content_hash IN (...)'
```

빠진 수치가 원문 어디에 있었는지는 창을 잘라 보면 바로 갈린다.
연도가 군더더기 문장에 있었으면 손댈 것이 없고, 이적료 · 계약 기간처럼 뜻을 바꾸는 자리면 재번역 대상이다.

## 4. 원문에 없는 구단명 — `summary_ko` 를 본다

```
WARNING 원문에 없는 구단명 잔존 — 수동 확인 content_hash=... 구단=['맨체스터 시티']
```

**`body_ko` 만 뒤지면 「없음」 이 나온다.** 이 게이트는 번역 4필드를 전부 대조하고, 트윗처럼 원문이 한 문장인 기사에서는 대개 **요약문이 배경지식을 채워 넣는다.**

```bash
... -e 'SELECT title_original, summary_ko, body_ko, body_level FROM articles WHERE content_hash="..."'
```

2026-08-29 사례는 원문이 `Arsenal are increasingly likely to sign Julian Alvarez.` 한 줄인데 요약문이 「맨체스터 시티의 공격수」 를 붙였다.
원문에 없을 뿐 아니라 사실도 아니었다 (그 선수는 아틀레티코 마드리드 소속이다).

## 5. 중복 후보 의심 — 병합 절차

```
WARNING 중복 후보 의심 — 병합은 사람이 판단: Christian Mosquera ↔ Cristhian Mosquera(id 183)
```

**자동 병합 규칙을 만들지 않는다** — 맞아 보이는 규칙 셋을 913건에 대 보고 전부 기각한 기록이 있다 (`2026-08-28-three-rules-that-looked-right-and-broke-more.md`).
사람이 같은 인물이라고 판단한 뒤 아래 순서로 옮긴다.

**5.1. 백업**

```bash
docker exec bullet-in-mariadb-1 mariadb-dump -uroot -pbulletin bulletin players article_players \
  > /home/ubuntu/backup_players_<날짜시각>.sql
```

**5.2. 충돌 확인** — `article_players` 의 기본키가 `(content_hash, player_id)` 라, 정본 쪽에 같은 기사 귀속이 이미 있으면 옮기다 막힌다.

```sql
SELECT ap.player_id, ap.content_hash,
       (SELECT COUNT(*) FROM article_players x
         WHERE x.content_hash = ap.content_hash AND x.player_id IN (<정본들>)) AS canon_has
  FROM article_players ap WHERE ap.player_id IN (<중복들>);
```

**5.3. 한 트랜잭션으로 적용**

```sql
START TRANSACTION;
UPDATE article_players SET player_id = <정본> WHERE player_id = <중복>;
DELETE FROM players WHERE id IN (<중복들>);
COMMIT;
```

**5.4. 전후 대조** — 귀속 총량 · 선수 행 수 · 정본별 귀속 수를 같은 쿼리로 앞뒤에 찍는다.
2026-08-29 실제 값은 귀속 총량 3,624 로 불변 · 선수 행 528 → 526 · 정본 두 명이 각각 +1 이었다.

**주의 둘.**

- **`archived` 행은 건드리지 않는다** — `status` 를 만지면 인명 사전과 fmkorea 수집 필터가 함께 움직인다 (`2026-08-27-archiving-a-player-narrowed-the-collection-filter.md`).
- **화면 반영은 다음 회차의 렌더다** — 병합 직후에 사이트를 열면 그대로다.

## 6. 동성 복수 slug — 손댈 것이 없다

```
동성 복수 — slug 를 id 로 떨어뜨림: Yan Diomande → diomande-181
```

성이 겹치는 선수가 둘 있으면 선수 페이지 주소를 `surname-id` 로 떨어뜨리는 정상 폴백이다.
2026-08-29 이전에는 `WARNING` 이라 사고처럼 보였고, 그 뒤로 `INFO` 다.
