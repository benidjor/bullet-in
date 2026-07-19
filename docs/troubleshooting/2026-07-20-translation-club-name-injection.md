# 번역 외부 지식 주입 환각 — 무근거 구단명 삽입 · 스윕의 언어별 대조 함정 (2026-07-20)

번역 품질 게이트 3축이 모두 놓친 새 환각 유형의 진단 기록.
사용자 신고 ("제목에 미들즈브러가 있는데 본문에 언급이 없다") 로 발견됐고, 코퍼스 스윕 과정에서 스윕 자체의 오탐 함정도 실측했다.

## 1. 증상

- BBC 라운드업 `9956234a…` 의 원문 제목은 `Arsenal forward Trossard joins Besiktas for £15.3m` 뿐.
- 번역 산출물 3곳에 원문에 없는 "미들즈브러" 가 등장:
  - title_ko: "… 3000만 파운드 **미들즈브러** FW 영입 임박" (실제 £30m 대상 = 클럽 브뤼헤의 촐리스).
  - body_ko · summary3_ko: "**미들즈브러의** 모건 로저스" — 원문은 `Aston Villa, who reportedly value Rogers at £130m` 로 소속을 명시.

## 2. 원인 판정 — 학습 지식 주입 (기사와 모순)

- 모건 로저스의 실제 전 소속이 미들즈브러다 (2024년 미들즈브러 → 아스톤 빌라).
→ 모델이 기사에 없는 **학습 지식을 주입**해, 기사 본문 (빌라 소속) 과 모순되는 서술을 만들었다.
- 기존에 관찰 · 대응한 환각 유형 (인명 누락 · 무근거 임대 · 제목 전면 환각) 과 성격이 다르다
— 세상 지식으로는 "참" 에 가까운 정보라 표면상 그럴듯해, 표기 스윕 · 역방향 검출로도 안 걸리고 독자 신고까지 잠복했다.
- 부수 관찰: 제목 번역이 원문 제목에 없는 본문 내용 (촐리스 £30m) 을 덧붙이는 라운드업 제목 증강도 같은 회차에 발생 — 증강 자체보다 증강 중 사실 결합이 어긋나는 것이 위험.

## 3. 게이트 3축이 못 잡은 이유

| 게이트 | 커버 | 이 유형 |
|---|---|---|
| 정방향 환각 검출 | 번역 누락 · 왜곡 (귀속 문구 기준) | 삽입은 대상 아님 |
| 역방향 제목 검출기 (#80) | 인명 누락 · 무근거 임대 | 무근거 **구단명** 은 범위 밖 |
| glossary 스윕 | 표기 변형 교정 | 미들즈브러는 표기 문제가 아님 |

## 4. 진단 · 스윕 방법 (재사용)

키워드 존재 매트릭스 — 의심 고유명사 × (원문 body_source vs 번역 body_ko) 존재 여부를 대조한다.

```sql
-- 번역엔 있는데 원문엔 없는 구단명 후보 (en 경로)
SELECT content_hash, title_ko FROM articles
WHERE (title_ko LIKE '%미들즈브러%' OR body_ko LIKE '%미들즈브러%' OR summary3_ko LIKE '%미들즈브러%')
  AND COALESCE(body_source,'') NOT LIKE '%Middlesbrough%'
  AND COALESCE(title_original,'') NOT LIKE '%Middlesbrough%';
```

### ⚠️ 함정 — 언어별 대조 없이는 ko 경로가 오탐

- 위 스윕이 fmkorea 행 `cc2c7b58` 을 잡았으나 **오탐** — fmkorea 는 body_source 자체가 한국어라
  근거가 "미들즈브러" (한글) 로 실존하는데 영문 `Middlesbrough` 대조는 항상 불성립.
- 규칙: **en 경로 (HTML 스크랩 등) 는 영문 표기, ko 경로 (fmkorea) 는 한글 표기로 원문을 대조**한다.
  lang 컬럼이 따로 없으므로 실무상 `source_id` 로 경로를 가른다 (fmkorea = ko).
- 이번 실측: 전 코퍼스 205건에서 실환각은 1건뿐, 오탐 1건은 위 규칙으로 해소.

## 5. 정정 · 지속성 한계

- 정정: title_ko (미들즈브러 FW → 클럽 브뤼헤 FW) · body_ko · summary3_ko (→ 아스톤 빌라의) 3곳 `REPLACE` UPDATE + site 재렌더. DB 작업이라 커밋 · PR 없음.
- **지속성 한계**: 수동 정정은 upsert 밖의 UPDATE 다.
  같은 기사가 revision 재수집 (본문 변경 → content_hash 변경) 되면 번역 필드가 리셋 · 재번역되므로 같은 환각이 재발할 수 있다
— 근본 방어는 검출기 (아래) 몫이고, 정정은 현 스냅샷의 교정이다.

## 6. 예방 — 검출기 트랙 (백로그 등재)

- "무근거 구단명 검출기 보강" 을 백로그 SoT (`docs/superpowers/2026-07-19-post-v1-followup-tracks.md` §5) 에 등재 (PR #89).
- 설계 요점 (본 문서 실측 반영): 번역 3필드에 등장하는 구단명 중 원문에 없는 것을 플래그,
  §4 의 언어별 대조 규칙 필수, 구단명 사전은 glossary (표기 교정) 와 분리한 한↔영 매핑.

## 7. 참고

- 게이트 3축 운영: `docs/runbook/2026-07-19-translation-quality-gates-ops.md`.
- 역방향 제목 검출기: PR #80 · glossary 스윕: PR #81.
- 선행 환각 유형 기록: bullet-in 트랙 ③ 데이터 정정 (id 420 제목 전면 환각 등).
- 확률적 파싱 실패 (같은 enrich 계열 · 별개 유형): `docs/troubleshooting/2026-07-19-gemini-stochastic-json-parse-failure.md`.
