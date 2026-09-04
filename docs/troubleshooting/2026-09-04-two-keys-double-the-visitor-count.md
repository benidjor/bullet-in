# 방문자를 두 키로 세면 두 배가 된다

2026-09-04 밤, 대시보드 개편 목업을 만들려고 행동 로그 bronze 에서 고유 방문자를 셌다.
첫 번째 답은 1,758명이었고 두 번째 답은 890명이었다.
같은 표, 같은 기간이었다.

## 1. 증상

- 첫 집계는 `bi_cid` 가 있으면 그것을, 없으면 `user_pseudo_id` 를 키로 썼다.
  → 사용자 1,758명
- 두 번째 집계는 `user_pseudo_id` 하나만 썼다.
  → 사용자 890명
- 날짜별로도 같은 배율로 벌어졌다 (공개일 08-29 가 첫 집계 1,205명, 두 번째 688명).

## 2. 원인

행동 로그 표 (`behavior.ga4_events_flat`) 에는 사용자 키가 둘 실려 있다.
`user_pseudo_id` 는 GA4 가 모든 이벤트에 붙이는 익명 id 이고, `bi_cid` 는 우리 계측 (`app.js`) 이 우리 이벤트 넷 (`bi_entry` · `bi_card_click` · `bi_filter_apply` · `bi_origin_exit`) 에만 붙이는 id 다.
GA4 자동 이벤트 (`page_view` · `session_start` · `user_engagement` · `scroll`) 에는 `bi_cid` 가 비어 있다.
14,315행 가운데 9,945행이 그렇다.

그래서 「있으면 `bi_cid`, 없으면 `user_pseudo_id`」 는 한 사람을 두 키로 나눠 센다.
그 사람의 `bi_entry` 행은 `bi_cid` 로, 같은 사람의 `page_view` 행은 `user_pseudo_id` 로 들어가 서로 다른 사람으로 잡힌다.
두 키의 값이 다르기 때문이다.

## 3. 확인

```python
# VM · ~/bullet-in · .env 소싱 · GOOGLE_APPLICATION_CREDENTIALS 는 레이크하우스 키
from bullet_in import warehouse as w
import pyarrow.compute as pc
t = w.load_catalog().load_table(f"{w.BEHAVIOR_NS}.{w.GA4_FLAT_TABLE}").scan().to_arrow()
print(pc.count_distinct(t["user_pseudo_id"]).as_py(), t["user_pseudo_id"].null_count)   # 891 · 0
print(pc.count_distinct(t["bi_cid"]).as_py(), t["bi_cid"].null_count)                   # 867 · 9945
```

`user_pseudo_id` 는 결측이 0 이고 `bi_cid` 는 결측이 9,945 다.
사람을 셀 키는 결측이 없는 쪽 하나여야 한다.

## 4. 처방

- 사용자 수 · DAU · 리텐션 · 퍼널의 사용자 단계는 `user_pseudo_id` 하나로 센다.
- `bi_cid` 는 우리 이벤트끼리 잇는 자연키 (`bi_cid` + `bi_ts`) 로만 쓴다.
  중복 제거 (`dedupe_events`) 가 이미 그렇게 쓴다.
- 두 키를 섞는 코드는 쓰지 않는다.
  「없으면 다른 키로」 는 결측을 메우는 것이 아니라 사람을 쪼갠다.

## 5. 함께 드러난 것 둘

**모든 방문자 수는 하한선이다.**
이 서비스의 운영자 본인은 광고 차단 확장을 쓰고 그 상태에서는 GA4 태그 자체가 안 실려 방문이 잡히지 않는다 (운영자가 직접 확인한 사실이다).
같은 이유로 차단 확장을 쓰는 다른 방문자도 빠진다.
그래서 890명은 「본인을 뺀 외부 방문자」 이면서 동시에 실제보다 작은 수다.
화면과 문서에는 「하한선」 을 붙여 적는다.

**공개일 하루가 표본의 대부분이다.**
7일 사용자 890명 가운데 688명 (77%), 카드 클릭 621건 가운데 306건 (49%) 이 08-29 하루의 것이다.
커뮤니티에 글이 올라간 직후 몰려온 사람들이라 평소의 사용 방식과 다르다.
총량과 시계열에는 넣고 평균 · 비율 · 분포에서는 뺀다.
집계 함수 `warehouse.aggregate` 가 이미 그 규칙을 쓰고 있고 화면에서는 절마다 「제외 · 포함」 을 고를 수 있게 한다.

## 6. 교훈

키가 둘인 표에서 「없으면 다른 키」 는 결측 보정이 아니라 이중 계수다.
사람 수는 결측이 없는 키 하나로 세고, 나머지 키는 잇는 데만 쓴다.

관련
— [2026-09-02 행동 로그 bronze 설계](../superpowers/specs/2026-09-02-behavior-log-bronze-design.md)
— [2026-09-04 bronze 에서 방문자 · 퍼널 · 리텐션을 세는 법](../runbook/2026-09-04-measuring-visitors-funnel-and-retention-from-bronze.md)
