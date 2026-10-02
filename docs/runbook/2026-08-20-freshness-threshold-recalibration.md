# 신선도 임계 재측정 (2026-08-20)

## 목적

소스별 `freshness_hours` 를 실측으로 다시 정하는 절차.

- **언제 쓰는가** — 안건 ι · 임계계절성 착수 시 (이적 시장 마감 뒤 14일 표본 확보) · 새 소스를 붙인 뒤 · 한 소스의 stale 비율이 20% 를 넘을 때.
- **왜 절차가 필요한가** — 표본 구간을 잘못 자르면 값이 열 배 틀리고 (`docs/troubleshooting/2026-08-20-gap-samples-contain-our-own-downtime.md`), 임계와 알림 건수의 관계가 직관과 달라 후보를 훑어 봐야 한다.
- **전제** — 신선도 신호가 원본 수집 (`raw_items`) 기준으로 옮겨진 뒤다 (설계 `docs/superpowers/specs/2026-08-20-absorbed-source-freshness-signal-design.md`).
  옮기기 전 이력으로 재면 흡수당하는 소스의 값이 통째로 틀린다.

## 1. 표본 유효 구간부터 확인한다

**이 단계를 건너뛰면 나머지가 전부 무의미하다.**

```sql
SELECT DATE(started_at) d, COUNT(*) runs FROM pipeline_runs
GROUP BY d ORDER BY d;
```

- 하루 회차 수가 정상 (현재 8회) 인 구간만 표본으로 쓴다.
- 회차가 빠진 날의 공백은 소스의 침묵이 아니라 우리 정지다.
- **2026-08-20 기준 유효 시작일은 2026-07-25** 다.
- 유효 구간이 14일 미만이면 재측정하지 말고 기다린다.

## 2. 소스별 원본 공백 분포를 낸다

`raw_items` 는 `content_hash` 가 처음 보는 값일 때만 문서를 넣으므로, 문서 사이 간격이 곧 「새 소식이 없던 시간」 이다.

```javascript
// VM: docker exec bullet-in-mongo-1 mongosh bulletin --quiet --eval "..."
db.raw_items.find({}, {source_id: 1, fetched_at: 1, _id: 0})
  .forEach(d => print(d.source_id + "," + d.fetched_at))
```

**`fetched_at` 은 BSON 날짜가 아니라 ISO-8601 문자열이다.**

- `RawItem.model_dump(mode="json")` 를 거쳐 저장되기 때문이다.
- Mongo 의 날짜 연산자를 쓰면 `TypeError: d.fetched_at.toISOString is not a function` 이 난다.
- 저장된 값이 전부 `...Z` 로 끝나는 같은 형식이라 **사전식 비교가 시간순 비교와 일치한다** (2026-08-20 · 1,369건 전수 확인).
  구간을 자를 때는 `{fetched_at: {$gte: "2026-07-25T00:00:00Z"}}` 처럼 문자열로 비교하면 된다.

받은 목록을 소스별로 정렬해 이웃 간격 (시간) 을 구하고 중앙값 · 95 백분위 · 최대를 낸다.
**한 시각에 여러 문서가 들어오므로 시각을 집합으로 만든 뒤 센다** (안 그러면 간격 0 이 분포를 덮는다).

## 3. 후보 임계별 알림 건수를 시뮬레이션한다

**공백 백분위만 보고 임계를 정하지 않는다.**
실제로 몇 번 울리는지는 회차 간격 (3시간) 과 48시간 재알림 규칙이 함께 정한다.

```sql
SELECT source_id, checked_at FROM source_freshness
WHERE checked_at >= '2026-07-25' ORDER BY checked_at;
```

2026-10-02 부터 임계는 조용함 표시선일 뿐이라 알림 건수 시뮬레이션은 더 필요하지 않다.
공백 분포만 쓴다 (§8 참조).
아래는 옛 알림 규칙 기준의 기록이다.

```
경과 <= 임계            → 정상
경과 > 임계             → 단계 = (경과 - 임계) // 48
단계가 직전 회차보다 크면 → 발송 1건
```

후보는 12 · 18 · 24 · 36 · 48 · 72 · 96 · 120 · 168 · 192h 정도면 충분하다 (운영이 읽기 쉬운 24h 배수 위주).
**표 하나에 「전체 기간 알림 / 최근 14일 알림」 을 함께 적는다** — 뒤 값이 지금의 계절을 반영한다.

## 4. 값을 고른다

**기준 — 최근 14일 알림이 소스당 1건 이하가 되는 가장 작은 임계.**

- 작을수록 고장을 빨리 알지만 정상 침묵에서 울린다.
- 한 칸 내렸는데 알림이 몇 배로 뛰면 그 소스는 이미 최소치에 있다 (2026-08-20 실측에서 `bbc_gossip` · `fmkorea` · `x_afcstuff` 가 24h 에서 그랬다).
- **분포가 넓히라고 하는 소스를 좁히지 않는다** — 저빈도 개인 계정은 95 백분위가 임계보다 클 수 있다.
- `freshness_hours: 0` 은 정상 공백에 상한이 없는 이벤트 구동 소스에만 쓴다 (`arsenal_official`).
  신호가 틀린 것을 덮는 데 쓰지 않는다.

## 5. 적용과 되돌리기

`config/sources.yaml` 의 소스별 `freshness_hours` 한 줄씩이고 코드 변경이 아니다.

- **한시적으로 바꾸는 값에는 원래 값과 원복 날짜를 주석에 함께 적는다.**
  적어 두지 않으면 되돌릴 시점에 무엇으로 되돌릴지가 남지 않는다.
- 신호를 바꾸는 배포와 임계를 바꾸는 배포는 **분리하고 사이에 정기 회차를 하나 이상 둔다.**
  같이 나가면 알림이 변한 이유를 둘로 나눠 볼 수 없다.
- 되돌리기는 그 줄을 주석에 적힌 값으로 되돌리는 것뿐이다.

## 6. 배포 뒤 확인

- **임계를 고친 회차는 알림이 한 번 몰린다** — 직전 회차 판정을 새 임계로 다시 쓸 수 없어, 그 시점에 stale 인 소스가 전부 한 번씩 알린다.
  도배로 읽지 말 것 (`docs/runbook/2026-07-13-freshness-watermark-ops.md` 의 같은 항목).
- 저널 한 줄로 판정 결과를 본다.

```bash
journalctl -u bullet-in.service --since '-1 day' | grep '신선도 판정'
```

- 며칠 뒤 stale 비율을 다시 본다.

```sql
SELECT source_id, COUNT(*) checks, ROUND(MAX(age_hours),1) max_age, SUM(stale) stale_n
FROM source_freshness WHERE checked_at >= NOW() - INTERVAL 30 DAY
GROUP BY source_id ORDER BY stale_n DESC;
```

## 7. 참고

- 표본 구간 함정 — `docs/troubleshooting/2026-08-20-gap-samples-contain-our-own-downtime.md`.
- 신호 교체 설계 — `docs/superpowers/specs/2026-08-20-absorbed-source-freshness-signal-design.md` (§5 가 마감 전 임시 임계와 그 근거).
- 임계 · 재알림 규칙의 원 설계 — `docs/superpowers/specs/2026-08-14-slo5-freshness-alert-blind-spot-design.md`.
- 알림 해석과 진단표 — `docs/runbook/2026-07-13-freshness-watermark-ops.md`.

## 8. 상한과 제목 확인 비율 (2026-10-02 추가)

### 8.1. 무엇이 바뀌었나

SLO-5 는 이제 「끊긴 소스」 만 센다 (스펙 `docs/superpowers/specs/2026-10-02-slo5-broken-source-signal-design.md`).

`freshness_hours` 는 끊김 판정에서 빠지고, 수집 현황 화면에서 「조용함」 을 표시하는 기준선이 됐다.
이 런북의 재측정 절차는 조용함 표시선을 고를 때 그대로 쓴다.
조용함 표시선은 수집 현황 화면에서 목록이 응답하는 소스를 조용함으로 표시하는 기준선이다 (알림은 없다).

### 8.2. 끊김을 정하는 값

| 값 | 위치 | 뜻 |
| --- | --- | --- |
| 무응답 2회 연속 | 코드 (`quality.evaluate_states`) | 목록이 응답하지 않으면 끊김 |
| 제목 확인 비율 절반 | 코드 (`quality.responded`) | HTML 목록에서 제목까지 확인된 링크가 절반보다 적으면 무응답 |
| `list_unchanged_cap_hours: 48` | `config/sources.yaml` | 목록이 48시간 넘게 그대로면 끊김 |
| `blocked_miss_runs: 8` | `config/sources.yaml` (fmkorea) | 검색 전부 430 (일시 차단) 만 이어지면 8회 (24시간) 째에 끊김 |

무응답이 처음 한 번이면 화면에 「응답 없음 1회」 만 보이고 알림은 없다.
연속 두 번째에 끊김이 되어 알림이 가고, 끊긴 동안은 48시간마다 다시 알린다.

fmkorea 의 일시 차단은 화면에 「차단 N회 (430)」 으로 보이고, 8회째까지는 알림이 없다.
차단 사이에 다른 사유 (연결 오류 · 검색 결과 0) 가 끼면 그 회차부터 2회 연속 규칙으로 돌아간다.
8 을 고른 계산과 근거는 설계 문서 `docs/superpowers/specs/2026-10-02-slo5-broken-source-signal-design.md` §8.3 에 있다.

### 8.3. 상한을 다시 볼 때

배포 뒤 「신선도 판정」 로그에서 소스마다 목록이 바뀐 간격을 모은다.
어느 소스든 정상일 때 목록이 48시간 넘게 그대로인 일이 있으면, 그 근거를 적고 상한을 올린다.
상한을 소스마다 다르게 두는 것은 그런 근거가 생긴 뒤에 정한다.
