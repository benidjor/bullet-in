# Gemini 파싱 실패 진단 — 확률적 비정형과 구조적 원인의 판별 (2026-07-19)

v1 마감 트랙 ③ 의 SLO 실측용 회차 (신규 52건) 에서 "Gemini 응답 파싱 실패, 스킵" 이 8건 나왔고, enrich 재시도에서도 2건이 반복 실패했다.
반복 실패는 구조적 원인 (본문 잘림 등) 처럼 보이지만, 실제로는 확률적 JSON 비정형이었고 재시도만으로 0 수렴했다.
이 문서는 그 판별 과정에서 밟은 오진 함정 2개와 판별 절차를 남긴다.

## 1. 증상

- 종단 회차 로그에 `WARNING … Gemini 응답 파싱 실패, 스킵 content_hash=…` 8건 (신규 52건 중).
- enrich 재시도 패스에서 6건 수렴 · 2건 반복 실패
→ 같은 행이 두 번 실패하니 "이 행 자체에 문제가 있다" 는 가설이 생김.

## 2. 오진 함정 ① — 기지 함정 패턴매칭

긴 본문 번역 잘림 (daily-ops §7 — `max_output_tokens` 초과로 JSON 꼬리 절단) 이 기지 함정이라 먼저 의심했다.
검증 자체는 옳은 순서지만, **반복 실패 = 구조적이라는 확신은 성급하다.**

- 실패 표본이 2건뿐이면 확률적 실패의 우연 반복과 구조적 실패를 로그만으로 구분할 수 없다.
- 판별은 §4 의 동일 입력 프로브가 한다 — 로그 재해석으로는 결론이 안 난다.

## 3. 오진 함정 ② — 진단 컬럼이 실제 입력과 다름

길이 가설을 재려고 실패 행의 `body_excerpt` 길이를 쟀다 (3,205 · 2,734자 — 정상 범위).
그런데 `enrich_rows` 의 실제 입력은 다르다.

```python
# src/bullet_in/enrich.py — 입력은 body_source 우선
contents=prompt.format(title=r["title_original"],
                       body=r.get("body_source") or r.get("body_excerpt") or "")
```

- `body_excerpt` 로 잰 "정상 범위" 는 무의미한 비교였다
— 다행히 `body_source` 재측정도 정상 범위 (3,205 · 2,734자 « 성공 행 최대 10,027자) 라 결론은 같았지만, 컬럼이 달랐다면 오판으로 직행했다.
- **교훈: 길이 · 내용 가설을 재기 전에 "코드가 실제로 모델에 넣는 컬럼" 을 먼저 확인한다.**

## 4. 판별 절차 — 동일 입력 1건 프로브

실패 행 1건을 골라 `enrich_rows` 와 동일한 프롬프트 · 입력 · config 로 단발 호출하고 세 가지를 본다.

```python
resp = client.models.generate_content(
    model=GEMINI_MODEL,
    contents=TRANSLATE_PROMPT.format(title=r["title_original"], body=r["body_source"] or ""),
    config={"max_output_tokens": 8192, "response_mime_type": "application/json"})
print(len(resp.text), resp.candidates[0].finish_reason)   # 길이 · 종료 사유
print(resp.text[-150:])                                    # 꼬리가 완결된 JSON 인가
print(_extract_full(resp.text) is None)                    # 파서 통과 여부
```

판독:

- `finish_reason=MAX_TOKENS` + 꼬리 절단
→ 구조적 (잘림) — daily-ops §7 경로.
- `finish_reason=STOP` + 완결 JSON + 파서 통과
→ **확률적 비정형** — 같은 입력이 회차마다 성공 · 실패를 오간다. 재시도가 해법.
- `STOP` 인데 파서 실패가 재현되면 응답 원문을 보고 파서 (`_extract_full`) 의 허용 범위를 판단.

이번 사례는 두 반복 실패 행 모두 프로브 1회에 성공 (STOP · 완결 JSON) → 확률적 판정 → 재시도 패스로 0 수렴.

## 5. 해결 · 예방

- 잔존 수렴은 enrich 전용 패스로 (fetch 없음 — `docs/runbook/2026-07-19-enrich-only-pass.md`).
- per-row 자동 재시도 루프는 추가하지 않는다 (YAGNI)
— 하루 4회 스케줄이 자연 재시도이고, 429 설계 (즉시 중단 · 다음 회차 누적) 와 같은 철학.
  즉시 수렴이 필요한 경우 (측정 · 캡처 전) 만 위 런북으로 수동 수렴.
- 파싱 실패율이 회차마다 유의하게 높아지면 (예: 신규 대비 15%+) 그때 프롬프트 · 파서 보강을 검토한다.

## 6. 참고

- 런북: `docs/runbook/2026-07-19-enrich-only-pass.md` (수렴 절차) · `docs/runbook/2026-05-27-daily-operations.md` §7 (긴 본문 잘림 — 구조적 경로)
- 트랙: v1 마감 트랙 ③ (PR #58), spec `docs/superpowers/specs/2026-07-19-v1-docs-capture-closeout-design.md`
