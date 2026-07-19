# 번역 품질 게이트 운영 (2026-07-19)

트랙 ③ · 상세 점검에서 도입한 번역 품질 자동 게이트 4축 + 사전 3종의 운영 절차.
모두 결정적 (LLM 재호출 없음) 후처리 · 검증이라 비용이 없고, 실패 시 재번역 큐 → 폴백으로 수렴한다.
도입 PR: #76 (정방향 환각) · #78 (라운드업 완전성) · #80 (역방향 오역) · glossary 확장 #72 · #81 · 구단명 주입 (2026-07-20).

## 1. 구성 — 게이트 4축과 사전 3종

| 축 | 함수 (enrich.py) | 잡는 것 | 실사례 |
|---|---|---|---|
| 정방향 환각 | `detect_title_hallucination` | 번역 제목에 생겼는데 원문에 없는 인명 | id 365 '펠레그리니' 창작 |
| 역방향 오역 | `detect_title_mistranslation` | 원문 제목 인명이 번역에서 전부 소실 · 무근거 '임대' | id 385 '조르제' · id 392 임대 반전 · id 420 무관 제목 |
| 라운드업 완전성 | `detect_roundup_omission` | 가십 단신 누락 (괄호 출처 병기 대조) | id 381 말미 3건 누락 |
| 무근거 구단명 | `detect_club_injection` | 번역 4필드 (제목 · 요약 · 3줄 · 본문) 에 생긴 원문 근거 없는 구단명 (학습 지식 주입) | `9956234a` 미들즈브러 (로저스 전 소속 주입) |

- **사전 3종**: `config/glossary.yaml` (오표기 → 통용 치환, 저장 직전 적용)
  · `config/name_map.yaml` (한글 통용 표기 → 영문 성, 검출 전용 — 치환 안 함)
  · `config/club_map.yaml` (한글 통용 표기 → 영문 별칭 목록, 검출 전용 — 치환 안 함).
- 적용 지점: `run.py` 번역 저장 루프 — glossary 치환 → 검출 → `paragraphize` → 저장.

## 2. 재번역 큐 · 폴백 동작 (스키마 무변경)

- **1차 검출** — WARNING + `title_ko` NULL 저장 (요약 · 본문은 저장)
→ 다음 사이클 `rows_missing_translation` 이 자동 재선별 (기존 멱등 경로 재사용).
- **재시도 판별 표지** — `title_ko IS NULL AND summary_ko IS NOT NULL` = 직전 사이클에 부분 저장된 재시도 행.
- **재검출 (재시도 행)** — 제목 축: 원문 제목 폴백 확정 + WARNING (사실 보존 우선)
  · 라운드업 축: 잔존 WARNING (수동 확인) — 사이클당 1회 재시도로 무한루프 차단.
  · 구단명 축: 잔존 WARNING (수동 확인) — 라운드업 축과 동일 (사이클당 1회 재시도).
- 실측: id 385 는 1차 재번역도 실패했으나 2차에서 "크리스토스 촐리스" 로 자가 복구 — 큐 설계가 실전 검증됨.

## 3. 로그 해석 (WARNING, `bullet_in.run`)

- **`재번역 큐 content_hash=… 환각의심=… 단신누락=… 구단주입=…`** — 1차 검출. 다음 사이클에 자동 재시도되므로 즉시 조치 불필요.
- **`제목 환각 재발 — 원문 제목 폴백`** — 재시도까지 실패. 서빙은 영문 원문 제목.
  한글 제목이 필요하면 수동 정정 (아래 §5) 후 원인 표기를 사전에 추가.
- **`라운드업 단신 누락 잔존 — 수동 확인`** — 본문 재번역 2회 모두 누락. 누락 출처 목록이 로그에 있으니 해당 단신만 대조.
- **`무근거 구단명 잔존 — 수동 확인`** — 재번역까지 같은 구단명 주입. 학습 지식 주입형은
  재롤로 안 고쳐질 수 있음 (원문 대조 수동 정정 → 선례: 미들즈브러 REPLACE 정정).

## 4. 사전 확장 절차

### 4.1. glossary (표기 변형 — 치환)

1. 변형 발견 시 `replacements` 에 `오표기: 통용` 추가.
2. **부분 포함 검사 필수** — 짧은 표기가 다른 단어 안에 들어가는지, 긴 표기를 먼저 두는지
   (선례: `메리에르` 를 `메리에` 보다 앞에 — 순서가 곧 치환 순서).
3. 기존 저장분은 SQL REPLACE 백필 별도 수행 (한국어 4필드만 — `body_source` 영어 원문 보존, PR 본문 기록).

### 4.2. name_map (검출 사전 — 치환 아님)

1. `names` 에 `한글 통용 표기: 영문 성` 추가. 값은 성 단독 (풀네임 · 성 표기 변형을 포함 매치).
2. 같은 인물의 복수 한글 표기는 각각 등재 (검출기가 영문 값 기준으로 동일 인물 처리)
— 단, glossary 가 한 표기로 정규화하면 (라시포드 → 래시포드) 통용 표기 한쪽만 등재해도 된다 (검출 전에 치환 적용).
3. **시드 표기가 곧 판정 기준** — 통용 표기가 틀리면 오탐이 난다 (선례: 은완네리 → 은와네리 교정).
4. 영문 값은 단어 경계로 매치되므로 'price' 안의 'Rice' 류 오탐은 구조적으로 차단됨 — 별도 고려 불필요.

### 4.3. club_map (구단명 검출 사전 — 치환 아님)

1. `clubs` 에 `한글 통용 표기: [영문 별칭 목록]` 추가. 통칭 (Boro · Spurs) 까지 등재해야 오탐이 없다.
2. 짧은 한글 표기의 후행 결합 오매치 (인터뷰 ⊃ 인터 · 로마노 ⊃ 로마 · 포르투갈 ⊃ 포르투) 는 코드 가드 밖 — 셋 중 하나로 대응:
   구별 가능한 긴 표기 등재 (인터 밀란 · AS 로마) / 혼동 상위어의 영문 표기를 별칭에 넣어 접지 (포르투 ← Portugal) /
   영문 앵커가 없으면 미등재 (릴).
3. 선행 결합 (시리즈 ⊃ 리즈) 은 `_ko_present` 가드가 방어 — 별도 고려 불필요.
4. 아스날은 미등재 (전 기사가 아스날 문맥이라 신호 없음) · 복수 한글 표기는 각각 등재.
5. 복수 한글 표기 등재 시 별칭 목록을 완전히 동일하게 맞출 것
— 동일 별칭 목록 = 동의 키 그룹으로 원문 근거를 상호 인정한다 (맨유 ↔ 맨체스터 유나이티드).

## 5. 코퍼스 스윕 · 수동 정정

정기 점검 또는 오역 제보 시 전수 스윕:

```bash
set -a; source .env; set +a
uv run python - <<'PY'
import os, yaml
from sqlalchemy import create_engine, text
from bullet_in.enrich import (detect_title_mistranslation, detect_roundup_omission,
                              detect_club_injection)
name_map = yaml.safe_load(open("config/name_map.yaml"))["names"]
club_map = yaml.safe_load(open("config/club_map.yaml"))["clubs"]
e = create_engine(os.environ["MARIADB_URL"])
with e.connect() as c:
    rows = [dict(r) for r in c.execute(text(
        "SELECT id, source_id, title_original, title_ko, body_source, body_ko, "
        "summary_ko, summary3_ko, body_excerpt FROM articles WHERE title_ko IS NOT NULL")).mappings().all()]
for r in rows:
    if r["source_id"] != "bbc_gossip":   # 라운드업 제목 재초점은 정상 (run.py 와 동일 제외)
        m = detect_title_mistranslation(r["title_ko"], r["title_original"], name_map)
        if m: print("제목:", r["id"], r["source_id"], m)
    o = detect_roundup_omission(r["body_source"], r["body_ko"])
    if o: print("단신:", r["id"], o)
    src = " ".join(filter(None, [r["title_original"], r["body_source"], r["body_excerpt"]]))
    c2 = detect_club_injection(r, src, club_map)
    if c2: print("구단:", r["id"], c2)
PY
```

- 플래그 행 처리: `UPDATE articles SET title_ko=NULL WHERE id=…` 로 큐 투입 후 다음 사이클 (또는 대상 한정 스크립트) 재번역.
- 재번역이 반복 실패하는 행 (JSON 파싱 실패 등) 은 원문 대조 수동 정정으로 마감하고 PR 에 기록 (선례: id 392 · 420).

## 6. 함정 · 한계

- **사전 밖 토큰 환각은 못 잡는다** — '펠레스타인' (Atletico 왜곡) 실증. 인명 사전을 늘려도 미지 토큰 창작은 구조적으로 미검출
→ 실사례 관찰 시 사전 1행 확장으로 흡수, 누적되면 하이브리드 (플래그 건 LLM 재확인) 재검토.
- **정당한 제목 축약과의 구분** — 역방향 인명 검사는 원문 제목의 매핑 인명이 **전부** 소실일 때만 플래그
  (일부 유지 = 다절 트윗 · 리스트클의 정상 축약). bbc_gossip 은 제외 (재초점이 정상).
- **폐기 소스 잔존 플래그** — football_london 리스트클 6건은 스윕에 계속 잡히지만
  재번역 경로 (title_ko NULL 트리거) 를 타지 않는 기존 행이라 무해 — 오탐으로 오인하지 말 것.
- **백필 · 스윕은 통합 상태에서** — 브랜치 갈린 상태의 데이터 작업 사고는
  `docs/troubleshooting/2026-07-19-parallel-pr-session-integrity-traps.md` 부록 참조.
- **일반어 별칭의 미검출 방향 열림** — `Forest` · `Palace` · `Villa` 류 통칭 별칭은 casefold 매치라
  원문의 일반 명사 용례도 근거로 인정된다. 오탐 안전 우선 설계상 의도된 방향 (미검출로만 열림) — 결함 아님.

## 7. 롤백

- 게이트 비활성: `git revert` (코드) — 검출이 전부 no-op 이 되고 저장 경로는 기존과 동일.
- 사전만 무력화: `name_map.yaml` 의 `names` 를 비우면 인명 축 전체 no-op (임대 축은 코드 revert 필요).
- 구단명 축만 무력화: `club_map.yaml` 의 `clubs` 를 비우면 no-op (코드 revert 불필요).
- 데이터: 큐 투입 (title NULL) 은 다음 사이클 번역으로 자연 복원 — 별도 롤백 불필요.
