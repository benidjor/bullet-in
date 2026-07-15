# JSON-LD 저자 추출 함정 — 제어 문자 · HTML 엔티티 · 공저 결합 (2026-07-16)

## 배경

기자 중심 트랙 (PR #54) 은 기사 페이지의 저자를 추출해 기자 facet · 신뢰도 보정에 쓴다.
라이브 실측에서 html 5소스 (bbc_sport · goal · football_london · skysports · arsenal_official) 가 모두 JSON-LD 로 저자를 노출하는 것을 확인하고, 소스별 CSS 셀렉터 대신 공통 파서 `meta.extract_authors` 를 채택했다.
JSON-LD 는 SEO 용 구조화 데이터라 CSS 셀렉터보다 안정적이라는 판단이었다.

그 판단 자체는 유효했으나, JSON-LD 라도 **소스가 규격을 지키지 않는 세 방식**이 있었다.
셋 다 모킹 단위 테스트를 통과한 뒤 라이브 검증에서만 드러났다.

## 증상

skysports 만 저자 채움이 11건 중 7건에 그쳤다 (다른 4소스는 100%).
누락 4건의 기사 페이지를 직접 열어보니 JSON-LD 에 `author` 키가 **존재**했다 — 파서가 있는 저자를 놓치고 있었다.

## 원인

### 1. raw 제어 문자 → strict JSON 파싱 거부 → 블록 통째 스킵

Sky Sports 의 `NewsArticle` LD 는 문자열 안에 raw 제어 문자를 담는다.
`json.loads` 는 기본 strict 모드에서 이를 거부한다.

```
JSONDecodeError: Invalid control character at: line 2 column 374 (char 374)
```

파서는 `except json.JSONDecodeError: continue` 로 그 블록을 통째 버렸고, 그 안에 **등재 기자 (Dharmesh Sheth, tier 1.5) 가 들어 있었다**.
저자만 잃은 게 아니라 tier 보정 경로까지 통째로 놓쳤다.

`json.loads(raw, strict=False)` 로 재시도하면 같은 블록이 정상 파싱된다.

```
lenient type= NewsArticle | author= {"@type": "Person", "name": "Keith Downie &amp; Dharmesh Sheth"}
```

### 2. JSON-LD 안의 HTML 엔티티

위 값에서 보이듯 `&amp;` 가 이스케이프된 채 들어 있다.
JSON 문자열이므로 JSON 이스케이프만 풀리고 HTML 엔티티는 그대로 남는다.
저장하면 바이라인에 `&amp;` 가 노출되고 레지스트리 매칭도 깨진다.

### 3. 공저를 한 `Person.name` 에 결합

Sky Sports 는 공저자를 `author` 배열로 나열하지 않고 **한 Person 의 `name` 에 영어 나열 관례로 결합**한다.

```
'Keith Downie &amp; Dharmesh Sheth'
'Keith Downie, Dharmesh Sheth &amp; Kaveh Solhekol'
```

이 문자열은 레지스트리의 어떤 기자와도 매칭되지 않는다.
결과적으로 등재 기자가 포함된 기사인데도 미등재로 취급돼 tier 보정이 조용히 누락된다.
BBC 는 같은 상황에서 `author` 배열에 Person 2개를 넣는다 — 규격 준수 여부가 소스마다 다르다.

### 공통 원인

**모킹 픽스처는 규격을 지킨다.** 픽스처는 사람이 스펙을 보고 쓰므로 제어 문자 · 엔티티 · 결합 문자열이 등장하지 않는다.
JSON-LD 를 "구조화 데이터라 안정적" 으로 본 판단이 "따라서 값도 규격대로일 것" 이라는 가정으로 미끄러진 것이 근본이다.

## 발견 — 라이브 어댑터 단독 fetch

머지 전 어댑터 단독 `fetch()` 라이브 검증 (`docs/troubleshooting/2026-06-12-live-source-selector-drift.md` 이후의 상시 절차) 이 세 함정을 모두 잡았다.
소스별 채움률을 출력한 것이 결정적이었다 — 총합만 봤다면 "8/11 이면 충분" 으로 넘어갔을 것이다.

```
bbc_sport: 2건 · authors 채움 2건
skysports: 11건 · authors 채움 7건    ← 이 비대칭이 조사 착수 근거
```

## 해결

`meta.extract_authors` · `_normalize_authors` 에 세 가지를 반영했다.

- **제어 문자** — `json.loads(raw)` 가 `JSONDecodeError` 를 내면 버리기 전에 `json.loads(raw, strict=False)` 로 재시도.
- **엔티티** — `html.unescape` 로 해제 (파일의 함수 인자명이 `html` 이라 `import html as _html` 별칭 필요).
- **결합 저자** — `re.split(r"\s*[,&]\s*")` 로 분리해 개별 저자로 취급. 대표 선정 (`pipeline.select_journalist`) 이 그중 등재자를 고른다.

수정 후 실측:

```
skysports: 11건 · authors 채움 8건
   복수 ['Keith Downie', 'Dharmesh Sheth', 'Kaveh Solhekol'] → 대표 'Dharmesh Sheth'
```

잔여 3건은 `author` 가 `{"@id": "#Publisher"}` 인 무기명 기사 (Paper Talk 등) 로, 저자 없음이 정상이다.

## 함정 안의 함정 — 1회 실측이 패턴을 다 보여주지 않는다

1차 fix 는 ` & ` **만** 분리했다.
당시 실측에 그 패턴만 잡혔고, 관찰되지 않은 구분자를 넣지 않는 것이 YAGNI 라고 판단했다.

재검증에서 라이브 기사 집합이 바뀌면서 쉼표 결합 (`'Keith Downie, Dharmesh Sheth & Kaveh Solhekol'`) 이 드러나 그 판단이 뒤집혔다.
`['Keith Downie, Dharmesh Sheth', 'Kaveh Solhekol']` — 첫 원소가 매칭 불가라 결함이 그대로 남아 있었다.

**라이브 소스는 회차마다 다른 표본을 준다.** 1회 실측의 부재는 "그 패턴이 없다" 가 아니라 "이번 표본에 없었다" 이다.
값 형태에 대한 YAGNI 판단은 표본 1회로 확정하지 말고, 그 소스의 표기 관례 (여기서는 영어 나열 `A, B & C`) 를 근거로 삼는 편이 안전하다.

## 예방

- **파서 계약** — 외부 구조화 데이터는 "구조는 안정적, 값은 임의" 로 가정한다. 파싱 관용 (`strict=False`) · 엔티티 해제 · 구분자 분리를 정규화 단계에 둔다.
- **라이브 검증 출력** — 총합이 아니라 **소스별** 채움률을 찍는다. 비대칭이 조사 착수 신호다.
- **회귀 테스트** — 실측된 실제 값 (제어 문자 포함 문자열 · `&amp;` · `A, B & C`) 을 픽스처로 고정한다. 규격을 지킨 픽스처만으로는 재발을 못 막는다.
- **fix 후 재검증** — 라이브 검증은 fix 후 반드시 다시 돌린다. 이번 3회차 재검증이 쉼표 패턴을 잡았다.
- **실패 격리 유지** — 저자는 부가 정보다. 어떤 파싱 실패도 빈 목록으로 폴백해 기사 적재를 막지 않는다 (이 계약 덕에 세 함정이 데이터 손실이 아니라 채움률 저하로만 나타났다).

## 참고

- PR #54 · spec: `docs/superpowers/specs/2026-07-16-journalist-track-design.md` · plan: `docs/superpowers/plans/2026-07-16-journalist-track.md`.
- 같은 계열 (라이브만 잡는 외부 의존 결함): `docs/troubleshooting/2026-06-12-live-source-selector-drift.md` — 그쪽은 셀렉터 자체가 깨짐, 이쪽은 셀렉터는 맞고 값이 규격 밖.
- 가정 파기 선례: `docs/troubleshooting/2026-07-15-guardian-api-body-image-elements.md` — 문서화된 API 의 필드 가정이 라이브에서 파기된 사례.
- 운영: `docs/runbook/2026-07-16-journalist-backfill-ops.md`.
