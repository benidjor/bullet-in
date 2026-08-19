# 살아 있는 소스가 오래됐다고 찍힌다 — 워터마크는 소식이 아니라 소스 이름을 잰다 (2026-08-20)

## 1. 증상

신선도 알림을 고쳐 배포한 첫 회차에 경고가 나갔다.

```
🕰️ 신선도 경고 — 오래된 소스 1건
감시 7소스: stale 1 · 정상 6 · 워터마크 없음 0

 [David Ornstein (X) (x_ornstein)]
 - ⏳ 438.0h 경과 (임계 120h)
 - 마지막 수집: 18일 전 ( 2026년 8월 1일 오후 9:03 )
 - 이번 회차 후보 5건 — 경로는 응답하나 새 글이 없습니다
```

**그런데 그 소스는 죽지 않았다.**
그 회차에 같은 날 아침 올라온 트윗을 실제로 가져왔다.

알림이 스스로 적어 놓은 숫자와 어긋나는 결론을 냈다.
「후보 5건」 안에 그날 새로 올라온 트윗이 들어 있었는데도 「새 글이 없습니다」 라고 적었다.

## 2. 확인 절차

**저장 결과만 보면 이 문제는 안 보인다.**
원본 수집과 저장 결과를 따로 세어 대조해야 드러난다.

### 2.1. 원본 수집 (Mongo)

```javascript
db.raw_items.find({source_id: "x_ornstein"})
  .sort({fetched_at: -1}).limit(8)
  .forEach(d => print([d.fetched_at, (d.raw_payload||{}).created_at, d.url].join(" | ")))
```

| 수집 시각 | 트윗 작성 시각 | 주소 |
| --- | --- | --- |
| 08-19 15:05 | 08-19 13:42 | The Athletic — 콘사 영입 합의 |
| 08-19 12:03 | 08-19 10:32 | The Athletic — 콘사 영입 근접 |
| 08-14 18:03 | 08-14 15:45 | The Athletic — 마르티넬리 |
| 08-14 12:05 | 08-14 10:08 | The Athletic — 콴사 |

수집 시각과 작성 시각이 같은 날이다.
**경로가 살아 있을 뿐 아니라 새 내용을 실제로 받고 있다.**

### 2.2. 저장 결과 (MariaDB)

```sql
SELECT url, fetched_at FROM articles
WHERE source_id = 'x_ornstein' ORDER BY fetched_at DESC LIMIT 3;
```

마지막 행이 08-01 이다.
**2.1 의 네 건이 하나도 행으로 남지 않았다.**

### 2.3. 그 소식이 어디로 갔는가

```sql
SELECT source_id, journalist, outlet, tier, fetched_at
FROM articles WHERE url LIKE '%7510407%';
```

| source_id | journalist | outlet | tier |
| --- | --- | --- | --- |
| fmkorea | David Ornstein | The Athletic | 1 |

**소식을 놓친 것은 아니다.**
같은 기사가 fmkorea 경로로 들어와 `The Athletic` · tier 1 로 서빙되고 있고, 기자 이름까지 David Ornstein 으로 붙어 있다.

## 3. 원인 — 설계된 동작 둘이 겹친다

**① 트윗의 주소가 원문 기사 주소로 바뀐다.**
`x_playwright` 어댑터는 `self_source` 소스에서 `resolve_card_urls` 로 트윗 카드의 링크를 따라가 원문 주소를 채운다.
그래서 온스테인 트윗은 `x.com/...` 이 아니라 The Athletic 기사 주소를 갖는다.

**② 같은 주소에 본문이 더 충실한 행이 있으면 새 행을 안 만든다.**

```
dedup.classify  →  new_body_level > last_level 이면 upgrade · 아니면 blocked
```

같은 기사를 fmkorea 가 한국어 전문으로 들고 온다.
30단어짜리 트윗은 본문 등급이 낮아 `blocked` 가 되고 **행 자체가 안 생긴다** (회차당 blocked 3 ~ 6건).

**두 동작 다 옳다.**
①이 없으면 트윗이 원문과 안 묶이고, ②가 없으면 같은 기사가 두 벌로 쌓인다.
문제는 그 결과를 신선도 감시가 잘못 읽는 것이다.

## 4. 왜 신선도 감시는 이 둘을 구분하지 못하나

신선도 감시는 `articles` 의 `MAX(fetched_at)` 을 워터마크로 쓴다 (`MartStore.source_watermarks`).

**그 값이 답하는 질문은 「이 소스 이름으로 마지막에 저장된 때가 언제인가」 이지 「이 소스에서 소식을 받았는가」 가 아니다.**

두 질문은 보통 같은 답을 내지만 다른 소스의 행으로 흡수되는 소스에서는 답이 달라진다.
그런 소스는 수집이 멀쩡해도 워터마크가 영영 움직이지 않으므로 **임계를 아무리 잘 맞춰도 언젠가는 반드시 stale 이 된다.**

지금은 `x_ornstein` 하나다.
트윗을 기사로 흡수하는 설계 (`docs/superpowers/specs/2026-08-14-tweet-article-absorption-design.md`) 가 구현되면 `x_afcstuff` 도 같은 자리에 선다.

## 5. 처방

**신선도 신호를 저장 결과가 아니라 원본 수집 기준으로 바꾼다** (사용자 판단 2026-08-20).

- Mongo `raw_items` 의 소스별 마지막 수집 시각을 보면 「수집이 끊겼다」 와 「수집됐으나 다른 행으로 흡수됐다」 가 구분된다.
- 설계 변경이라 별도 스펙이 앞선다.
- 잔여 안건 메모리의 **안건 θ (흡수 소스의 신선도)** 가 이 일을 맡는다.

**기각한 임시 처방** — 그 소스에 `freshness_hours: 0` 을 주어 감시에서 뺀다.
설정 한 줄로 즉시 조용해지지만 **그 소스가 진짜로 죽어도 모르게 된다.**
감시 제외는 `arsenal_official` 처럼 소식이 없는 기간이 얼마나 길어져도 정상인 이벤트 구동 소스를 위한 장치이지, 신호가 틀린 것을 덮는 장치가 아니다.

## 6. 다음에 같은 문제를 알아보는 법

**「이 소스가 살아 있는가」 를 저장 결과로 재고 있지 않은지 본다.**

저장은 수집 뒤에 오는 여러 판단 (중복 · 본문 등급 · 필터) 을 통과한 결과다.
그 판단이 모두 정상으로 동작해도 저장이 0 일 수 있으므로 **저장 0 을 수집 0 으로 읽으면 멀쩡한 소스를 고장이라고 부르게 된다.**

- 알림이 소스가 죽었다고 하면 **먼저 원본 저장소에서 그 소스의 마지막 수집 시각을 본다.**
- 원본에 새 것이 있는데 저장에 없으면 그 사이 단계를 따라간다 (중복 판정 · 본문 등급 · 관련성 필터).
- 같은 계열의 함정 — 화면 · DB · 저장값이 같은 이름으로 다른 값을 내는 자리는 `docs/troubleshooting/2026-08-14-suspect-the-yardstick-not-the-data.md` 에 정리돼 있다.

**이것은 「저자 미상」 과 같은 실수다.**
`docs/troubleshooting/2026-08-15-unknown-author-means-we-could-not-read-it.md` §1 이 그 문장을 이미 적어 뒀다
— 파이프라인의 상태 이름은 데이터가 어떻다는 말이 아니라 우리 처리가 어떻다는 말이다.

거기서는 「저자가 비어 있다」 를 「원문에 저자가 없다」 로 읽었고, 여기서는 「워터마크가 낡았다」 를 「소스가 죽었다」 로 읽을 뻔했다.
**둘 다 우리 쪽 상태를 바깥 세계의 사실로 옮겨 적은 것이다.**

## 7. 참고

- 신선도 감시 운영 — `docs/runbook/2026-07-13-freshness-watermark-ops.md`.
- 이 알림을 고친 설계 — `docs/superpowers/specs/2026-08-14-slo5-freshness-alert-blind-spot-design.md` (PR #290 으로 구현).
- 억제가 침묵이 된 경위 (같은 알림의 앞 사건) — `docs/troubleshooting/2026-08-15-alert-suppression-becomes-silence.md`.
- 트윗을 기사로 흡수하는 설계 — `docs/superpowers/specs/2026-08-14-tweet-article-absorption-design.md`.
- 같은 구조가 서빙 쪽에도 있다 (재려는 값과 실제로 세는 층이 어긋남) — `docs/troubleshooting/2026-08-20-rendered-values-are-not-raw-data.md`.
