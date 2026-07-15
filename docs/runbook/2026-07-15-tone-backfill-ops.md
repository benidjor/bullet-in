# 요약 말투 백필 운영 런북

PR #48 (요약 말투 정리)로 들어간 존댓말 검출 · 선별 백필의 운영 절차.
백필은 매 run 사이클 (하루 4회 스케줄)에서 자동으로 돌며, 이 문서는 실측 · 조정 · 실패 대응만 다룬다.

## 1. 잔존 실측 (읽기 전용)

```bash
set -a; source .env; set +a
uv run python - <<'EOF'
import os
from sqlalchemy import create_engine
from bullet_in.storage.mariadb import MartStore
from bullet_in.tone import has_polite_ending
mart = MartStore(create_engine(os.environ["MARIADB_URL"]))
rows = mart.rows_enriched_summaries()
bad = [r for r in rows
       if has_polite_ending(r.get("summary_ko")) or has_polite_ending(r.get("summary3_ko"))]
print(f"잔존 {len(bad)} / 전체 {len(rows)}")
for r in bad[:5]:
    print("-", r["content_hash"][:8], (r.get("summary_ko") or "")[:60])
EOF
```

판독:
- 샘플 5건을 눈으로 확인해 **오검출 (인용문 · 명사 어미)이 없는지** 먼저 본다.
- 오검출이 있으면 §5 (검출기 조정)로 — 백필은 검출을 그대로 믿으므로 오검출 방치 = 정상 요약 재생성 낭비.
- 기준 실측 (2026-07-15, 트랙 종결 시점): 잔존 0 / 296.

## 2. 회차 상한 (`tone_backfill_limit`) 조정

- 기본 20 (`config/sources.yaml`). 조정 기준: 잔존 N ≤ 80이면 유지 (20 × 하루 4회 = 하루 내 수렴).
- N > 80이면 상향 (예: 40) — 429는 분당 *속도* 한도라 회차 내 직렬 호출 수십 건은 안전 (CLAUDE.md 함정 절).
- run.py는 `cfg.get("tone_backfill_limit", 20)` 폴백이라 키를 지워도 무해하다.

## 3. 수렴 확인은 로그가 아니라 §1 스크립트로

- 백필 결과 INFO (`말투 백필: 대상 %d건 중 %d건 재생성`)는 **기본 로깅 레벨에서 출력되지 않는다** (run.py는 루트 로거를 구성하지 않음).
- 따라서 로그 침묵은 "패스 미실행"의 증거가 아니다 — 실행 여부 · 수렴 여부 판단은 §1 스크립트가 유일한 근거.
- 수렴 후 정상 상태도 침묵이다 (검출 0건이면 백필 패스가 조용히 지나감).

## 4. 실패 모드

| 증상 | 원인 | 대응 |
|---|---|---|
| 특정 행이 여러 사이클 연속 잔존 | 모델이 해당 기사에서 존댓말을 고집 → 재생성 결과가 다시 검출됨 (회차 슬롯 1개 점유) | §1 샘플로 해당 요약 확인 → 오검출이면 §5, 진짜면 해당 건만 수동 재생성 또는 방치 (비용은 상한으로 유계) |
| 잔존 수가 줄지 않고 요약도 안 바뀜 | Gemini가 빈/`null` summary_ko 반환 → `_extract_resummary` 가드가 행 단위 스킵 (기존 요약 보존) | 정상 방어 동작 — 다음 회차 재선별로 자연 재시도, 지속되면 프롬프트 점검 |
| WARNING `rate limit(429), 말투 백필 중단` | 429 — 그 회차 즉시 중단 (남은 건 다음 사이클) | 대응 불필요 (스케줄이 재시도) — 매 회차 반복되면 상한 하향 검토 |
| 있던 요약이 사라짐 (NULL) | 백필 경로에선 발생 불가 (가드) — upsert의 revision 리셋이 원인일 가능성 | `pipeline_runs` · revision 확인, 다음 사이클 번역 패스가 복원 |

## 5. 검출기 조정 (어미 · 인용부호 목록)

- SoT는 `src/bullet_in/tone.py`의 `_POLITE_END` (어미) · `_QUOTED` (인용부호), 동작 고정은 `tests/test_tone.py`.
- 조정 절차: 오검출/미검출 실례를 **테스트 케이스로 먼저 추가** (실패 확인) → 목록 수정 → 통과 확인.
- 알려진 미커버 (의도적 이월): 의문형 존댓말 (~습니까 · ~나요) — 뉴스 요약에 드물어 수렴 0 확인 시점 기준 불요, 잔존이 다시 생기면 재검토.
- 유니코드 주의: 인용부호 목록은 실제 코드포인트 (U+201C 등)여야 한다 — 유사 ASCII 강등 사고는 `docs/troubleshooting/2026-07-15-subagent-unicode-transcription-loss.md`.

## 6. 전건 재요약이 필요할 때 (프롬프트 대개편 등)

- 백필 트리거는 "검출된 행"뿐이라, 말투 외 이유의 전건 재생성은 이 경로로 못 한다.
- 전건 재생성은 기존 절차 (transfer-stage 런북의 컬럼 NULL 복원 패턴)를 요약 필드에 준용: `summary_ko`를 NULL로 복원하면 번역 패스 (`title_ko IS NULL` 아님 주의 — 요약만 NULL이면 번역 패스 대상이 아님)가 아니라 **별도 백필이 필요**하므로, 실제로는 title_ko까지 NULL 복원해 전체 enrich를 다시 태우는 것이 안전하다.

## 7. 롤백

- `git revert` (PR #48 squash 커밋) + `tone_backfill_limit` 키 제거 (잔존해도 무해).
- 백필이 만든 데이터 변경은 요약 2필드뿐이고 원문 (`body_ko` · raw)이 보존되므로 가역 — 필요 시 재생성으로 복원.

## 참조

- spec · plan: `docs/superpowers/{specs,plans}/2026-07-15-summary-tone-cleanup*.md` (PR #47)
- 429 · 하루 4회 스케줄: CLAUDE.md "자주 밟는 함정"
- 최종 리뷰 Minor 이월 (기록): 0건 회차 무로그 (§3) · 풀 SELECT body_ko 전량 (규모 커지면 2단 조회) · 재생성 재검증 없음 (§4 첫 행)
