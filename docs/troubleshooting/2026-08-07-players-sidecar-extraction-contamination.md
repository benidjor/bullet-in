# 선수 귀속 오염의 통로는 곁다리 추출과 제목-only 재료였다 (2026-08-07)

`article_players` 오염이 무엇인지는 `2026-08-03-player-stage-not-grounded-in-article.md` 가 다뤘다.
이 문서는 재추출 트랙의 dry-run (스펙 `2026-08-07-player-stage-reextraction-design.md`) 이 특정한 **왜 그런 값이 만들어졌는지** — 통로 두 개를 기록한다.
프롬프트 결함이라고만 알고 있던 문제의 절반 이상이 실은 호출 구조와 재료의 문제였다.

## 통로 ① — 완역 호출의 곁다리 필드는 주 과제에 묻힌다

players 쌍은 대부분 수집 시점의 번역 · 재작성 호출 (`TRANSLATE_PROMPT` · `PARAPHRASE_PROMPT`) 이 완역의 부산물로 뽑는다.
완역이라는 큰 과제 옆에 붙은 곁다리 필드는 모델이 본문을 훑으며 이름을 긁는 대로 담고, 출력 검증도 주 과제 (번역 품질) 에 몰려 있어 아무도 그 필드를 따져 보지 않았다.

실측이 이것을 갈랐다.

- 비니시우스 기사 (`41db55d1`) 의 DB 귀속은 14명 — 과거 대형 이적 나열 대목의 10명이 후보로 등재될 정도로 긁혀 있었다.
- 같은 기사를 **전용 추출 호출** (`EXTRACT_PLAYERS_PROMPT` + 본문) 로 다시 물으면, **프롬프트를 고치지 않아도** 2명 (비니시우스 · 아르테타) 만 나온다 (dry-run 4회 전부 동일).
- 즉 이 기사의 과잉 귀속은 프롬프트 문구가 아니라 **호출 맥락**의 산물이다.

교훈 — 구조화 추출을 큰 생성 과제의 곁다리로 붙이면 품질이 따로 떨어진다.
곁다리 필드의 값이 이상할 때는 프롬프트 문구를 의심하기 전에, 같은 입력을 전용 호출로 다시 물어 두 결과를 갈라 봐야 한다.

## 통로 ② — 재료가 제목 한 줄이면 모델은 세계지식으로 채운다

- 연결 기사 502건 중 **130건 (26%)** 은 `body_source` · `body_excerpt` 가 모두 빈 문자열이다 (x_afcstuff 125 · x_ornstein 5 — 트윗 계열).
- 추출 재료가 `body_source or body_excerpt or ""` 라, 이 130건은 **제목 한 줄이 재료의 전부**였다.
빈 문자열 폴백은 오류 없이 조용히 진행되므로 로그에도 남지 않는다.
- 근거가 한 줄뿐이면 모델은 빈 곳을 아는 대로 채운다.
기마랑이스 트윗 (`e5ad5c1a`) 이 실증이다 — 제목만 주면 `rumour` (세계지식), 트윗 전문 번역 (`body_ko` · "며칠 내 합의 · 최대 8천만 파운드") 을 주면 `negotiating` (근거 기반).
- 130건 전부 `body_ko` 는 있다.
→ 재추출 재료를 `body_source or body_excerpt or body_ko` 로 넓히는 폴백이 스펙 §3.2 로 확정됐다.

교훈 — LLM 출력이 "그럴듯한데 근거가 없다" 면 프롬프트보다 먼저 **그 호출이 실제로 받은 재료**를 확인한다.
빈 문자열 폴백은 조용해서, 재료 부족은 출력 품질 문제로 위장된다.

## 왜 지금까지 못 봤나

- 곁다리 필드 (통로 ①) 는 주 과제의 검증 (번역 게이트) 이 커버하지 않았고, `article_players` 를 읽는 화면이 생기기 전까지 소비자도 없었다.
- 재료 부족 (통로 ②) 은 폴백이 조용해 실패로 기록되지 않았고, 백필 (`backfill_article_players.py`) 도 같은 재료 규칙을 물려받아 같은 방식으로 돌았다.

## 진단 쿼리

```sql
-- 연결 기사 중 원문 본문이 빈 행 (소스별)
SELECT source_id, COUNT(*) n,
       SUM(COALESCE(body_source,'')='' AND COALESCE(body_excerpt,'')='') no_orig_body,
       SUM(COALESCE(body_ko,'')='') no_body_ko
  FROM articles a
 WHERE EXISTS (SELECT 1 FROM article_players ap WHERE ap.content_hash = a.content_hash)
 GROUP BY source_id ORDER BY n DESC;
```

## 참조

- 증상 정의: `docs/troubleshooting/2026-08-03-player-stage-not-grounded-in-article.md`
- 원인 특정 · 수정 설계: `docs/superpowers/specs/2026-08-07-player-stage-reextraction-design.md` (§1.2 · §4.2)
- 측정 절차: `docs/runbook/2026-08-07-extraction-prompt-dryrun-measurement.md`
