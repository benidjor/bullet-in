# 언론사 · 기자 facet tier 정렬 설계 (2026-07-16)

기자 트랙 ( PR #54 ) 후속 3트랙 중 ① 번.
기자 추출 · 기자 facet 이 들어오면서 사이드바가 74줄로 불어났고, 정렬이 건수순이라 물량 많은 저신뢰 소스가 최상단을 차지한다.
이 문서는 facet 을 신뢰도 순으로 재편하는 설계를 확정한다.

## 1. 배경 · 문제

- **건수순 정렬이 신뢰도를 뒤집음** — football.london 205건 ( Tier 4 ) 이 The Athletic 12건 ( Tier 1 ) 보다 위에 선다.
  "누가 말했나로 거른다" 는 제품 논지와 사이드바가 정면으로 어긋난다.
- **사이드바 74줄** — 언론사 12줄 + 기자 62줄.
  기자 62줄 중 56줄이 미등재이고, 그중 34명이 football.london 스태프다.
- **BBC 가 세 갈래로 분열** — `outlet_display()` 가 `display_name` 으로 폴백해 `BBC Sport` · `BBC Football Gossip` 이라는 문자열을 만드는데, 이 문자열은 `credibility.yaml` 에 없다.
  결과적으로 BBC 47건 중 46건이 tier 조회에 실패한다.
  `render.py:64` 의 기자 정규화 주석이 경고하던 함정 ( 같은 주체가 facet 에서 갈라짐 ) 이 언론사에도 그대로 있었다.
- **신뢰도 facet 에 1.5 부재** — `facet_counts()` 가 `int(t)` 로 내림해 Tier 1.5 기사 13건이 Tier 1 에 합산된다.
  Tier 헤더를 도입하면 소스 facet 은 `TIER 1.5` 를 보여주는데 신뢰도 facet 에는 1.5 가 없는 불일치가 드러난다.
- **tier 표기 불일치** — 카드 칩 · 신뢰도 facet 은 소문자 `tier 1`, ops 뷰는 대문자 `Tier 1 — 공식 · 1군 언론`.

## 2. 목표 · 비목표

- **목표** — 언론사 · 기자 facet 을 `tier` → `이름` 오름차순으로 정렬.
- **목표** — Tier 그룹 헤더 · 더보기 3단계 ( 빈 tier 건너뜀 ) · 등재 / 미등재 구분선.
- **목표** — BBC 통합 ( `BBC` Tier 1 · `BBC Football Gossip` Tier 4 로 분리 ).
- **목표** — Tom Canton 을 Tier 4 로 등재.
- **목표** — 신뢰도 facet 에 Tier 1.5 추가.
- **목표** — 화면 표기를 `Tier` 로 통일하고 tier 라벨을 공신력 단일 척도로 정리.
- **비목표 ( 트랙 ③ )** — football.london 의 Tom Canton 외 147건 서빙 숨기기.
  기자 단위 숨김은 신규 필터 차원이고, 정렬 키가 tier → 이름이라 건수가 바뀌어도 순서는 안 바뀌므로 두 트랙은 독립이다.
- **비목표 ( 별건 )** — `arsenal_official` 소스가 기사를 0건 생산 중인 문제.
  현재 목록의 `Arsenal.com` 5건은 전부 fmkorea 가 `[공홈]` 말머리로 귀속시킨 것이다.
- **비목표 ( YAGNI )** — 전개한 더보기를 되돌리는 접기 버튼 없음.
- **비목표 ( YAGNI )** — 언론사 · 기자 facet 통합 ( §3.5 에서 검토 후 기각 ).

## 3. 결정 사항

### 3.1. 정렬 = tier → 이름 오름차순

- **규칙** — tier 오름차순으로 묶고, 같은 tier 안에서는 표시명 오름차순 ( 대소문자 무시 ).
- **건수는 순서에 영향을 주지 않는다** — Tier 1 안에서 The Athletic 12건이 BBC 7건보다 아래에 선다.
- **미등재 구간도 이름 오름차순** — tier 가 없어 tier 키가 안 걸리는 구간이지만, 한 목록 안에서 정렬 규칙이 둘이 되지 않도록 이름순으로 통일한다.
  기존 `_ranked()` 의 건수 내림차순을 대체한다.
- **기각한 대안 — tier 내 건수 내림차순** — 실데이터가 반증한다.
  Ornstein 3건 · Mokbel 6건인데 요구된 순서는 `David Ornstein → Sami Mokbel` 이다.
- **기각한 대안 — `credibility.yaml` 등재 순서** — yaml 은 The Athletic 이 BBC 보다 먼저라 요구된 `BBC → The Athletic` 과 어긋난다.
  신규 등재마다 사람이 위치를 정해야 하는 비용도 있다.

### 3.2. 더보기 = 3단계 · 미등재는 Tier 4 와 동시 전개

- **초기 노출** — Tier 1.5 까지 ( Tier 0 · 1 · 1.5 ).
- **단계** — `Tier 2` → `Tier 3` → `Tier 4 + 미등재`.
- **빈 tier 는 건너뛴다** — 항목이 0개인 tier 는 단계에서 제외하고 다음으로 항목이 있는 tier 를 연다.
  기자 facet 은 Tier 2 가 0명이라 첫 더보기가 바로 `Tier 3` 을 연다.
- **버튼 라벨** — `더보기 · Tier N`. 마지막 단계는 `더보기 · Tier 4 · 미등재`.
- **기각한 대안 — 미등재를 단독 마지막 단계로** — 클릭이 4번으로 늘고, 미등재가 tier 와 동급의 단계처럼 보인다.
- **기각한 대안 — tier 더보기 + 미등재 더보기 버튼 2개** — 사이드바에 버튼이 둘씩 쌓인다.

### 3.3. Tier 라벨 = 공신력 단일 척도

| tier | 라벨 |
|---|---|
| 0 | `Tier 0 · 공식` |
| 1 | `Tier 1 · 공신력 최상` |
| 1.5 | `Tier 1.5 · 공신력 상` |
| 2 | `Tier 2 · 공신력 중` |
| 3 | `Tier 3 · 공신력 하` |
| 4 | `Tier 4 · 공신력 최하` |

- **단일 척도로 통일** — 상위는 공신력, 하위는 성격 ( `ITK · 루머` · `가십` ) 으로 섞으면 한 목록 안에서 척도가 두 개가 된다.
- **ops 뷰 `TIER_BUCKETS` 도 같은 어휘로** — `Tier 1 — 공식 · 공신력 최상` · `Tier 2 — 공신력 중` · `Tier 3 — 공신력 하`.
  기존 `1군 언론` · `2군 · 애그리게이터` · `ITK · 루머` 는 사라진다.
- **화면 표기는 `Tier`** — 카드 칩 · facet · 더보기 버튼 · ops 제목.
  `data-tier` · URL 파라미터 `?tier=` 등 코드 식별자는 소문자를 유지한다.

### 3.4. BBC 통합 = outlet 폴백 추가 + bbc_gossip 의 outlet 제거

- **`outlet_display()` 폴백 사슬** — `기사.outlet` → `소스.outlet` → `소스.display_name`.
  가운데 단계가 신설이다.
- **`sources.yaml` 의 `bbc_gossip` 에서 `outlet: BBC` 를 제거** — 제거해야 `display_name` 인 `BBC Football Gossip` 으로 폴백해 Tier 4 에 남는다.
  제거하지 않으면 가십 41건이 `BBC` 로 합쳐져 Tier 1 로 승격된다.
- **tier 조회 사슬** — `credibility.yaml` 의 outlet tier → `sources.yaml` 의 소스 `tier` → 미등재.
  `BBC Football Gossip` 은 credibility 에 없으므로 소스 tier 4 를 쓴다.
- **주의 · 부작용** — `sources.yaml` 의 `outlet` 은 죽은 설정이 아니다.
  `credibility.py:96` 의 소속 일치 보정이 `src.get("outlet")` 을 읽어 `min(j_tier, tier)` 승격을 건다.
  따라서 `bbc_gossip` 의 `outlet` 제거는 "등재된 BBC 기자가 gossip 에 쓰면 Tier 1 로 승격" 경로를 막는다.
  현재 데이터에서는 41건 전부 `journalist = "BBC Gossip"` ( 통칭 라벨 ) 이라 보정이 애초에 걸리지 않아 **결과는 중립**이지만, 원리상 동작 변경이므로 구현 시 회귀 테스트로 고정한다.
- **파급** — `outlet_display()` 는 카드 칩 · 상세 · ops 표기의 공용 경로다.
  BBC Sport 기사의 출처 칩이 `BBC Sport` → `BBC` 로 바뀐다 ( 의도된 변경 ).

### 3.5. 언론사 · 기자 facet 통합 = 검토 후 기각

- **검토한 안** — 언론사 facet 을 없애고, 등재 기자는 `기자 ( 언론사 )` 로 · 미매핑 항목은 언론사 이름만으로 한 목록에 합친다.
- **이득** — 실데이터 투영 결과 74줄 → 17줄, 초기 노출 9줄.
- **기각 사유 — 같은 언론사가 여러 줄로 흩어진다** — The Athletic 16건이 `The Athletic 9` · `David Ornstein ( The Athletic ) 3` · `James McNicholas ( The Athletic ) 4` 세 줄로 갈려 "The Athletic 전체" 를 보려면 세 번 체크해야 한다.
  BBC · Sky Sports · The Independent 도 같다.
- **부수 확인** — 통합 시 미등재가 `afcstuff` 5건 한 줄로 줄어 등재 / 미등재 구분선이 사실상 무의미해진다.
  두 facet 을 유지하면 미등재 55명이 남아 구분선이 의미를 지킨다.

### 3.6. Tom Canton = Tier 4 등재

- **등재 내용** — `credibility.yaml` 의 `journalists` 에 `{name: Tom Canton, tier: 4, outlet: football.london}` 추가.
- **tier 중립** — `credibility.py:96` 의 보정은 `min(j_tier, tier)` 인데 그의 소속 tier 와 소스 tier 가 둘 다 4라 `min(4, 4) = 4` 로 변화가 없다.
- **라벨 무변화** — `journalist_entry()` 가 이미 `Tom Canton (football.london)` 을 만든다.
- **효과** — 기자 facet 에서 미등재 → Tier 4 구간으로 이동. 미등재 56명 → 55명.
- **tier 외 파급 · 대표 기자 선정** — `pipeline.py:37-40` 의 `select_journalist()` 는 추출 저자 중 **등재 기자를 첫 저자보다 우선**한다.
  따라서 Tom Canton 이 공저자로 끼되 첫 저자가 아닌 football.london 기사는 앞으로 대표 기자가 첫 저자에서 그로 바뀐다.
  이미 적재된 행의 `journalist` 값은 그대로이고 신규 수집 · 백필에만 적용된다.
  기존 테스트 `test_select_journalist_falls_back_to_first_author` 가 Tom Canton 을 미등재 예시로 쓰고 있어 픽스처를 교체한다.
  이 변화는 받아들인다 — 알려진 기자에게 귀속하는 편이 facet 의 목적에 맞는다.
- **선례** — PR #51 `chore(credibility): Independent 3티어 등재` 와 같은 성격의 config 변경이다.

### 3.7. 신뢰도 facet = Tier 1.5 추가

- **tier 목록** — `0` · `1` · `1.5` · `2` · `3` · `4` ( 기존 `range(5)` 대체 ).
- **`facet_counts()` 의 `int(t)` 내림 제거** — Tier 1 이 32건 → 19건으로 갈리고 Tier 1.5 13건이 신설된다.
- **문자열 계약** — `app.js:74` 는 `tiers.includes(card.dataset.tier)` 로 문자열 동등 비교를 한다.
  따라서 `data-tier` 와 facet 의 `data-value` 가 같은 포매터를 써야 한다.

## 4. 데이터 계약

### 4.1. tier 표기 포매터

DB 의 `tier` 는 `FLOAT` 이고 실제 값은 `0.0` · `1.0` · `1.5` · `2.0` · `3.0` · `4.0` 이다.
표기 · 비교에 쓰는 문자열은 한 곳에서만 만든다.

| 용도 | 입력 | 출력 |
|---|---|---|
| `tier_key(t)` — `data-tier` · `data-value` · URL | `1.0` | `"1"` |
| `tier_key(t)` | `1.5` | `"1.5"` |
| `tier_label(t)` — 카드 칩 | `1.5` | `"Tier 1.5"` |
| `tier_label(None)` | `None` | `"Tier ?"` |

### 4.2. DOM 계약 변경

- `a.card[data-tier]` — `int` 내림에서 `tier_key()` 로 교체. `1.5` 기사가 `"1"` 이 아니라 `"1.5"` 로 찍힌다.
- URL 계약 `?tier=` 는 같은 문자열을 쓴다 ( `?tier=1.5` 가 유효해진다 ).
- 기존 북마크의 `?tier=1` 은 Tier 1.5 기사를 더 이상 포함하지 않는다 ( 의도된 변경 ).

## 5. 실데이터 투영 (308건)

### 5.1. 언론사 facet

| Tier | 항목 | 건수 |
|---|---|---|
| 0 | Arsenal.com | 5 |
| 1 | BBC | 7 |
| 1 | The Athletic | 12 |
| 1.5 | Sky Sports | 10 |
| 2 | L'Équipe | 1 |
| 2 | The Telegraph | 1 |
| 3 | The Independent | 1 |
| 4 | BBC Football Gossip | 41 |
| 4 | football.london | 205 |
| 4 | Goal.com | 12 |
| 미등재 | afcstuff (aggregator) | 13 |

### 5.2. 기자 facet

| Tier | 항목 | 건수 |
|---|---|---|
| 1 | David Ornstein (The Athletic) | 3 |
| 1 | Sami Mokbel (BBC) | 6 |
| 1.5 | Dharmesh Sheth (Sky Sports) | 3 |
| 1.5 | Fabrizio Romano | 2 |
| 1.5 | James McNicholas (The Athletic) | 4 |
| 3 | Miguel Delaney (The Independent) | 1 |
| 4 | Tom Canton (football.london) | 58 |
| 미등재 | 55명 | 213 |

### 5.3. 신뢰도 facet

| Tier | 건수 ( 현재 ) | 건수 ( 변경 후 ) |
|---|---|---|
| 0 | 5 | 5 |
| 1 | 32 | 19 |
| 1.5 | 없음 | 13 |
| 2 | 5 | 5 |
| 3 | 1 | 1 |
| 4 | 265 | 265 |

## 6. 건드리는 곳

| 파일 | 변경 |
|---|---|
| `src/bullet_in/serve/render.py` | `outlet_display()` 폴백 · `tier_key()` 신설 · `tier_label()` 대문자 · `facet_counts()` 정렬 · tier 그룹화 · `TIER_BUCKETS` 라벨 |
| `src/bullet_in/serve/templates/_layout.html.j2` | Tier 헤더 · 구분선 · 더보기 버튼 · 신뢰도 facet tier 목록 |
| `src/bullet_in/serve/templates/index.html.j2` | `data-tier` 를 `tier_key()` 로 |
| `src/bullet_in/serve/static/app.js` | 더보기 단계 전개 |
| `src/bullet_in/serve/static/style.css` | Tier 헤더 · 구분선 |
| `config/sources.yaml` | `bbc_gossip` 의 `outlet: BBC` 제거 |
| `config/credibility.yaml` | Tom Canton 등재 |

## 7. 검증

- **정렬** — Tier 1 안에서 `BBC` 가 `The Athletic` 보다 먼저, 기자 Tier 1 안에서 `David Ornstein` 이 `Sami Mokbel` 보다 먼저 나오는 테스트.
  건수는 각각 7 < 12 · 3 < 6 이므로 건수순 회귀를 동시에 잡는다.
- **빈 tier 건너뜀** — 기자 facet 의 첫 더보기가 `Tier 3` 을 여는 테스트.
- **BBC 분리** — `BBC` 가 Tier 1 · `BBC Football Gossip` 이 Tier 4 로 갈리고 두 항목의 건수 합이 48인 테스트.
- **보정 중립** — `bbc_gossip` 의 `outlet` 제거 후 41건의 tier 가 전부 4로 유지되는 회귀 테스트.
- **Tom Canton 중립** — 등재 전후로 그의 58건 tier 가 4로 유지되는 테스트.
- **tier 문자열 계약** — `tier_key(1.0) == "1"` · `tier_key(1.5) == "1.5"` 와, 렌더된 `data-tier` 값 집합이 신뢰도 facet 의 `data-value` 집합에 포함되는 테스트.
- **육안** — `uv run python -m bullet_in.run` 후 `site/index.html` 사이드바가 §5 투영과 일치하는지 확인.
