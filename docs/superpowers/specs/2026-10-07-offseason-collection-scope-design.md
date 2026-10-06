# 비수기 수집 범위 확대 설계 — 이적 + 선수 · 팀 소식 + 경기 평점 (2026-10-07)

안건 2ω (비수기 수집 기준) 의 조각 ⓑ 다.
구현 · 머지 · 배포는 2026-10-07 18:00 KST 실행 뒤에 한다 (§9.2).

## 1. 배경

### 1.1. 무엇이 문제인가

언론사 소스 셋 (BBC Sport · Sky Sports · The Guardian) 은 제목에 이적 낱말 (`config/sources.yaml` 의 `transfer_keywords` 20개) 이 있어야만 기사를 받는다.
이적 시장이 닫힌 비수기에는 이적 기사가 드물어, 이 소스들에서 들어오는 기사가 거의 없다.
공식 소스 (Arsenal.com) 도 구단 이적 태그나 제목의 이적 낱말 넷 (`joins` · `signs` · `transfer` · `loan`) 이 있어야 받는다.

2026-10-06 에 소스마다 목록을 한 번씩 받아 센 결과다.

| 소스 | 목록 | 지금 기준 통과 |
| --- | --- | --- |
| BBC Sport (아스날 RSS · 09-10 에서 10-03 까지) | 24 | 5 |
| Sky Sports (아스날 페이지) | 11 | 3 |
| The Guardian (아스날 태그) | 20 | 1 |
| Arsenal.com (최근 7일 · 1군 뉴스) | 29 | 0 |

### 1.2. 키워드 방식의 결함

비수기 공백 말고도 놓치는 것과 잘못 잡는 것이 함께 있다.

| 종류 | 예 |
| --- | --- |
| 놓침 | 「Bournemouth to resist interest in Scott until the summer」 (이적 기사인데 `interest` 가 키워드에 없다) |
| 잘못 잡음 | 「Arteta's suprise tactics to deal with travel issues」 (`deal with` 의 `deal` 이 부분 일치한다) |

### 1.3. 이 설계가 정한 것 (사용자 결정 · 2026-10-06)

| 항목 | 결정 |
| --- | --- |
| 수집 범위 | 이적 + 선수 · 팀 소식 (부상 · 복귀 · 재계약 · 유망주 · 대표팀 · 감독 발언) + 경기 평점 |
| 제외 | 리그 잡담 · 팬 의견 |
| 대상 소스 | BBC Sport · Sky Sports · The Guardian + Arsenal.com |
| 판정 방식 | 규칙 (키워드 + 명단 선수 이름 + 팀 낱말) · LLM 분류는 쓰지 않는다 (§7.1) |
| 적용 시기 | 연중 (이적 시장과 무관하게 같은 기준) |
| 화면 | 홈 맨 위 대표 기사 · 주요 소식은 「이적 우선」 · 나머지 화면은 그대로 |
| 놓침 관측 | 버린 제목을 실행마다 기록하고, 2주 뒤 LLM 보조가 필요한지 판단한다 |

대상에서 빠지는 소스는 이유가 있다.
Goal.com 과 football.london 은 수집을 멈춘 상태다 (`collect: false` · `enabled: false`).
BBC Gossip · X 두 계정 · fmkorea 는 이적 키워드를 쓰지 않는다.

## 2. 언론사 세 소스의 판정 규칙

### 2.1. 받는 조건

제목이 아래 넷 가운데 하나에 맞으면 받는다.

| 갈래 | 이름 (기록용) | 내용 |
| --- | --- | --- |
| 이적 키워드 | `keyword` | 지금의 `transfer_keywords` 20개 · 부분 일치 · 동작을 바꾸지 않는다 |
| 추가 낱말 | `extra` | `interest` · `ratings` · 낱말 단위 일치 · 대소문자 무시 |
| 명단 이름 | `name` | §2.2 · 낱말 단위 일치 · 대소문자 구분 |
| 팀 낱말 | `team` | `Emirates` · `stadium` · `Pro Ref` · `referee` · `academy` · `injury` · `fitness` · 낱말 단위 일치 · 대소문자 무시 |

판정 순서는 표의 위에서 아래이고, 처음 맞은 갈래 하나를 기록한다.
세 소스의 목록은 이미 아스날 전용이라 (아스날 RSS · 아스날 페이지 · 아스날 태그), 제목에 아스날 선수 이름이 있으면 곧 선수 소식이다.

지금 키워드의 부분 일치 (`deal` → 「deal with」) 는 이 설계에서 고치지 않는다.
고치면 지금 받는 기사가 줄어 범위 확대와 섞이므로 따로 둔다 (§8).

### 2.2. 이름 재료

명단 (`players` 표) 에서 `status='confirmed'` 이고 `category` 가 `squad` 또는 `manager` 인 사람의 `full_name` 과 `surname` 을 쓴다.
2026-10-06 기준 1군 40명과 감독 1명, 모두 41명이다.

명단에는 별칭 칸이 없어서, 설정 두 줄을 `config/sources.yaml` 에 둔다.

| 설정 | 뜻 | 처음 값 |
| --- | --- | --- |
| `scope_name_extras` | 명단에 없는 짧은 호칭 · 표기 변형 | `Gabriel` · `Bruno` · `Ødegaard` |
| `scope_name_full_only` | 성만으로는 인정하지 않는 이름 (흔한 낱말과 겹침) | `White` · `Rice` · `Jesus` · `Timber` · `Salmon` |

`scope_name_full_only` 에 든 성은 전체 이름 (예: 「Declan Rice」 · 「Ben White」) 으로만 맞는다.
「White Hart Lane」 같은 경우를 막기 위해서다.

명단은 수집 시작 때 한 번 읽어 어댑터에 넘긴다.
fmkorea 어댑터가 한글 이름을 받는 것과 같은 길이다 (`run.collect` → `build_adapters`).
DB 오류로 명단을 못 읽으면 이름 갈래만 빠진 채 나머지 갈래로 판정하고, 경고 로그를 남기며 수집은 계속한다.

### 2.3. 실제 제목에 대 본 결과 (2026-10-06)

갈래별로는 BBC 가 이적 키워드 5 · 추가 낱말 2 · 이름 7 · 팀 낱말 1, Sky 가 이적 키워드 3 · 이름 4, Guardian 이 이적 키워드 1 · 이름 6 · 팀 낱말 2 다.

| 소스 | 목록 | 지금 기준 | 이 규칙 |
| --- | --- | --- | --- |
| BBC Sport | 24 | 5 | 15 |
| Sky Sports | 11 | 3 | 7 |
| The Guardian | 20 | 1 | 9 |

새로 받는 것의 예는 이렇다.

- BBC — 「'Superstar' Dowman shows his class」 · 「Carsley urges patience over Dowman and England」 · 「Arsenal to contact Pro Ref over Konsa penalty」 · 「Guimaraes and Raya crucial - Sunderland v Arsenal player ratings」 · 「Bournemouth to resist interest in Scott」
- Sky — 「Havertz returning to Arsenal after suffering injury with Germany」 · 「Arteta: We didn't respect the game against Brighton」
- Guardian — 「'They deserved to win': Mikel Arteta left humbled by Brighton defeat」 · 「Arsenal shelve plans for major expansion of Emirates Stadium」 · 「Arsenal demand meeting with Pro Ref over penalty decision at Sunderland」

경계선으로 남는 것도 있다.

| 제목 | 이유 |
| --- | --- |
| 「Arteta helped me understand the game - Wilshere」 (BBC) | 감독 이름이 있지만 전 선수의 인터뷰다 |
| 「'It's absolutely crazy!' The tiny club that made Arteta, Alonso and Iraola」 (Sky) | 감독 이름이 있지만 특집 기사다 |
| 「What are the Premier League rules for academy players?」 (BBC) | 팀 낱말 `academy` 로 잡히지만 리그 일반 설명이다 |

버리는 것은 리그 잡담 (「10 talking points」 · 「title race」) · 팬 의견 (「Fans have their say」) · 중계 안내 (「How to watch」) · 경기 결과 기사 (「Brighton demolish champions Arsenal 3-0」) 다.

## 3. 공식 소스 (Arsenal.com)

### 3.1. 지금

| 채택 경로 | 조건 | 이적 단계 |
| --- | --- | --- |
| `tag` | 1군 (`Men`) 뉴스 + 구단 태그 `Transfer news` · `Contract news` | 「오피셜」 로 고정 (`transfer_stage.rule_stage`) |
| `title` | 1군 뉴스 + 제목에 `joins` · `signs` · `transfer` · `loan` (`quality.TRANSFER_TITLE_RE`) | LLM 판정 · 완료면 「오피셜」 로 올림 (`promote_official`) |

### 3.2. 새 채택 경로 `scope`

1군 뉴스 가운데 위 두 경로에 걸리지 않은 기사를 아래 조건으로 받는다.

- §2.1 의 `name` · `extra` · `team` 갈래 가운데 하나에 맞거나, 구단 `Internationals` (대표팀) 태그가 있다
- 그리고 제외 태그가 없고, 제외 제목에 맞지 않는다

| 제외 | 값 | 뜻 |
| --- | --- | --- |
| 태그 | `Compilation` · `Photos` · `Match gallery` · `Video` · `Full match` · `From the vault` · `Gamification` · `Behind the Scenes` · `3rd Party` · `Colney Carpool` | 사진 모음 · 영상 · 옛 경기 다시 보기 · 투표 · 다큐 예고 · 선수 차 안 인터뷰 영상 |
| 제목 | `Ask Me Anything` · 낱말 `AMA` | 선수의 팬 질의응답 · 태그로 구별되지 않는다 |

### 3.3. 이적 단계 규칙

`transfer_stage.rule_stage` 는 공식 소스 기사의 채택 경로가 `title` 이 아니면 단계를 「오피셜」 로 고정한다.
`scope` 를 그대로 두면 대표팀 활약 기사에도 「오피셜」 배지가 붙는다.
그래서 `scope` 경로는 `title` 과 같이 고정하지 않고 LLM 판정을 받게 한다 (대부분 「기타」 가 된다).
`promote_official` (완료 판정이면 「오피셜」 로 올림) 은 지금처럼 `title` 경로에만 적용한다.

### 3.4. 최근 7일에 대 본 결과 (2026-10-06 · 1군 뉴스 29건)

| 결과 | 기사 |
| --- | --- |
| 받음 (10건) | Lewis-Skelly 골든보이 후보 · Odegaard · Saka · Gyokeres (두 번) · Scanlon · Bruno 대표팀 활약 · Raya 이달의 선방 · Raya 와 Seaman 인터뷰 · 「Help Arteta win Manager of the Season」 |
| 거름 (19건) | 사진 모음 · 영상 · 옛 골 모음 · 장애인 티켓 안내 3 · Wenger 특집 · 투표 · 다큐 예고 · AMA 2 · Colney Carpool 등 |

「Help Arteta win Manager of the Season」 은 투표 독려 글이지만 감독 수상 후보 소식이기도 해 받는 쪽에 둔다.

### 3.5. 그대로 두는 것

- 「채택 누락 의심」 관측 알림 (`filter_miss_suspects`) 은 이적 제목인데 버려진 기사를 알린다. 버리는 기사가 줄 뿐 판정은 그대로 맞다.
- 공식 소스는 신선도 감시 제외 (`freshness_hours: 0`) 라 SLO-5 에 들어가지 않는다.
- 커버리지 감시 (`evaluate_coverage`) 의 계수 (`candidates` · `men_tagged` · `accepted`) 는 뜻이 그대로다. `accepted` 가 늘 뿐이다.

## 4. 화면 — 「이적 우선」

홈 맨 위 대표 기사 1장과 주요 소식 4건은 `serve.render.pick_top_stories` 가 고른다.
지금은 공신력 상위 3등급 · 최근 10일 기사를 순위 (`top_story_key`) 로 세우고, 이적 여부는 보지 않는다.

바꾸는 것은 정렬 기준 하나다.
이적 단계가 있는 기사 (`other` · 미분류 제외) 를 앞에 두고, 그 안에서 지금 순위를 따른다.
이적 기사가 다섯이 안 되면 남은 자리를 다른 소식이 지금 순위대로 채운다.

후보 조건 · 같은 사건 중복 제거 · 주요 소식을 최신순으로 다시 세우는 것은 그대로다.
최신 뉴스 목록 · 사이드바 필터 · 가십 절도 바꾸지 않는다.
새로 받는 기사는 이적 단계 분류에서 대부분 「기타」 가 되어 최신 뉴스에 배지 없이 섞여 나온다.

## 5. 기록 — 무엇을 받고 무엇을 버렸나

### 5.1. 수집 단계 기록에 더하는 키

`pipeline_runs.fetch_detail.funnels.<소스>` 에 두 키를 더한다.

| 키 | 값 |
| --- | --- |
| `passed_by` | 받은 기사의 갈래별 수 (`keyword` · `extra` · `name` · `team` · 공식 소스는 `tag` · `title` · `scope`) |
| `dropped` | 버린 제목 목록 · 소스당 최대 40개 · 제목당 120자 |

실행 기록은 2026-10-01 이후 평균 667바이트에서 5KB 안팎으로 늘 것으로 본다.
하루 8회면 연 15MB 안팎이다.

### 5.2. LLM 보조를 판단하는 법

배포 뒤 2주 동안 쌓인 `dropped` 를 손으로 훑어, 받아야 했는데 버린 제목이 주당 몇 건인지 센다.
놓침이 잦으면 A 를 통과하지 못한 새 제목만 묶어 Gemini 에 묻는 보조 판정 (§7.1 의 ②) 을 별도 설계로 얹는다.

```sql
SELECT started_at,
       JSON_EXTRACT(fetch_detail, '$.funnels.guardian.dropped') AS guardian_dropped
FROM pipeline_runs
WHERE started_at >= :since
ORDER BY started_at;
```

목록은 실행마다 같은 기사가 반복되므로 훑을 때는 제목을 중복 없이 모은다.

## 6. 영향

| 자리 | 영향 |
| --- | --- |
| SLO-5 (끊김) | 없다 · 응답 판정은 목록 링크와 제목 확인 수를 보고 키워드 통과 수는 보지 않는다 (`quality.responded`) |
| SLO-6 (수집량 이상) | 낮다 · 직전 12회 평균이 3건 미만인 소스는 판정하지 않는다 (`quality.volume_anomalies` 의 `min_baseline`) · 세 소스 모두 해당 |
| 번역 비용 | 하루 2 ~ 3건 늘 것으로 본다 · 지금 새 기사가 하루 15 ~ 17건이라 약 15 ~ 20% · 목록이 덮는 기간이 소스마다 달라 추정이며 배포 뒤 소스별 새 기사 수로 잰다 |
| 공식 소스 「오피셜」 배지 | `scope` 경로는 고정하지 않는다 (§3.3) |

## 7. 기각한 대안

### 7.1. 판정 방식

| 대안 | 기각 이유 |
| --- | --- |
| ② LLM 보조 (A 를 통과 못 한 새 제목만 Gemini 로 분류) | 지금 놓침 규모를 모른다 · 수집 단계에 외부 호출과 판정 주소 저장소가 생긴다 · §5.2 의 기록으로 필요를 잰 뒤 얹는다 |
| B LLM 제목 분류 (모든 새 제목) | 수집 판정이 Gemini 에 묶인다 · 2026-10-05 선불 잔액 소진 때 번역이 멈춘 일이 있었다 (안건 3α) |
| C 다 받고 나중에 거르기 | 번역이 분류보다 먼저라 버릴 기사까지 번역한다 · 처리 순서를 바꾸는 구조 변경이 필요하다 |
| ③ 다 받고 제외 낱말만 두기 | 범위 밖 기사 (격투기 · 특집 · 경기 결과) 가 표현만 바꿔 계속 들어온다 · 사실상 아스날 종합 뉴스가 된다 |
| 「제목이 `Arsenal` 로 시작」 규칙 | 팀 낱말과 같은 두 건을 잡지만 해설가 의견 (「Arsenal should have won Premier League sooner - Wilshere」) 을 잘못 잡는다 |

### 7.2. 화면과 시기

| 대안 | 기각 이유 |
| --- | --- |
| 대표 자리를 이적 기사만 | 비수기에 자리가 비거나 오래된 기사가 남는다 |
| 홈에 「선수 · 팀 소식」 별도 절 | 화면 설계 · 모바일 배치까지 새로 해야 한다 · 받아 본 뒤 판단한다 |
| 비수기에만 적용 | 시장이 열리는 순간 부상 · 평점 기사가 끊긴다 · 날짜 경계 규칙과 그 시험이 늘어난다 · 시장 기간의 대표 자리는 「이적 우선」 이 이적 기사로 채운다 |

## 8. 범위 밖

- 지금 키워드의 부분 일치 오탐 (`deal` → 「deal with」 · `sign` → 「design」)
- 분류 축을 새로 짜는 「아스날 종합 뉴스」 전환 (이적 · 부상 · 경기 · 계약 칸과 화면 재설계)
- 목록이 그대로일 때 조용함과 멈춤을 가르는 판정 (2ω ⓓ) · 상한의 계절성 (2ω ⓔ · 안건 ι)
- 「기타」 필터의 화면 개선 (안건 l-①)
- 명단의 별칭 칸 (지금은 설정 두 줄로 대신한다)

## 9. 시험 · 배포

### 9.1. 시험

| 대상 | 경우 |
| --- | --- |
| 판정 함수 | 갈래 넷 각각 · 처음 맞은 갈래 기록 · `rice` 는 거르고 「Declan Rice」 는 받음 · `Sakai` 는 `Saka` 로 안 잡힘 · 「White Hart Lane」 거름 · 명단이 비었을 때 이름 갈래만 빠짐 |
| 언론사 어댑터 | 2026-10-06 실측 제목 (BBC 24 · Sky 11 · Guardian 20) 을 픽스처로 두고 §2.3 의 결과를 고정 · `passed_by` · `dropped` 기록 · `dropped` 상한 40 · 120자 |
| 공식 소스 | §3.4 의 29건 픽스처 · 제외 태그 · AMA 제목 · `scope` 경로 기록 |
| 이적 단계 | `scope` 경로는 「오피셜」 로 고정되지 않음 · `promote_official` 은 `title` 에만 |
| 화면 | 이적 기사가 있으면 대표 자리를 차지 · 다섯이 안 되면 다른 소식이 채움 · 후보 조건 · 중복 제거 그대로 |

### 9.2. 배포 시점

구현 · 머지 · 배포는 2026-10-07 18:00 KST 실행 뒤에 한다.
그 시각의 수집 현황을 지금 수집 기준으로 남겨 두고, 바뀐 기준의 효과를 그 뒤 실행들과 비교하기 위해서다.

### 9.3. 배포 뒤 확인

| 시점 | 확인 |
| --- | --- |
| 첫 실행 | 네 소스의 `passed_by` · `dropped` 가 남는다 |
| 첫 주 | 소스별 새 기사 수 · 번역량 증가 · 공식 소스에 「오피셜」 이 잘못 붙지 않았다 |
| 2주 뒤 | `dropped` 를 훑어 LLM 보조가 필요한지 판단한다 (§5.2) |

### 9.4. 함께 고칠 문서

- README §3.4 의 「언론 5종은 공통 이적 키워드 필터를 공유합니다」 와 소스 표의 Arsenal.com 행
- `docs/superpowers/specs/2026-08-12-arsenal-official-collection-revision-design.md` 에 이 설계로 가는 개정 안내
