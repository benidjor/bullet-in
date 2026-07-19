# 공신력 레지스트리 · tier 운영 런북 (2026-07-15)

PR #45 에서 소스 tier 재조정 · 기자 5건 정비 · README 공신력 표 신설을 처리하며 정리한 절차.
공신력은 세 곳에 나눠 살아서 (config 2파일 + README 표) 한 곳만 바꾸면 조용히 어긋난다 — 이 런북이 그 정합 절차의 SoT.

## 1. 구성 — 공신력이 사는 세 곳

| 위치 | 역할 | 소비자 |
|---|---|---|
| `config/sources.yaml` | 직접 수집 소스의 고정 tier | `score.confidence` (적재 시 스냅샷) |
| `config/credibility.yaml` | journalists · outlets 레지스트리 (동적 라우팅) | `resolve_tier` (x_afcstuff · fmkorea) |
| README §3 표 2개 | 공개 뷰 (수집 소스 · 기자 ITK) | 사람 |

- 동적 소스 판정 순서: 기자 먼저 → 아웃렛 → 기본 4 (x_afcstuff 는 config `fallback_tier` · fmkorea 는 코드 상수).
- README 표는 config 의 파생 뷰: config 를 바꾸면 README 표도 **같은 PR 에서** 갱신한다.

## 2. 신규 기자 · ITK 등재 체크리스트

1. **동일인 확인** — 등재하려는 핸들 · 채널명이 기존 항목의 인물인지 먼저 확인 (gunnerblog = McNicholas 전례).
   개인 채널명 계정은 독립 항목이 아니라 본명 항목의 alias 로 흡수한다.
2. **tier 선정** — 소속 매체의 outlets tier 를 기준점으로 개인 신뢰도를 가감 (Sheth 1.5 = Sky Sports 동급 · Sam Dean 3 = Telegraph 동급).
   독립 · ITK 는 개별 판단.
3. **alias 3종 세트** — ① `@핸들`: X 인용 매칭에 필수 (없으면 그 경로에서 매칭 자체가 불가) ② 한글 표기: fmkorea 본문 매칭 ③ 영문 이름.
   단 성씨가 일반 영단어면 ("law" · "dean") 성씨 단독 대신 풀네임 — 트러블슈팅 함정 ③.
4. **검증** — 레지스트리 키 확인 (키는 소문자 정규화됨) + 전체 테스트.

```bash
uv run python -c "
from bullet_in.credibility import load_registry
reg = load_registry('config/credibility.yaml')
print(reg.journalists.get('@새핸들'.lower()))"   # 기대 tier 가 나와야 함
uv run pytest -q
```

## 2.5 전담 · 비전담 기준선 (2026-07-19 확정)

같은 언론사 안에서 아스날 전담 기자와 비전담 기자를 tier 로 구분한다.
- **소스 tier = 비전담 기준선** — 전담 기자를 등재한 직접 수집 소스는 sources.yaml tier 를 전담 기자보다 0.5 높게 (= 공신력 낮게) 둔다 (bbc_sport 1.5 · skysports 2).
- 전담 (등재) 기자 기사만 기존 min 승격 가드로 등재 tier 를 받는다 (Mokbel 1 · Sheth 1.5).
  미등재 바이라인 (비전담 개인 · 조직명 · 저자 미상) 은 자동으로 비전담 기준선을 받으므로 별도 등재가 필요 없다.
- 언급 라우팅용 outlets 레지스트리도 같은 값으로 동기화한다 (§3 두 파일 동시 수정 원칙 — BBC 1.5 · Sky Sports 2).
- 전담 기자가 없는 소스 (guardian · goal) 는 현행 tier 유지 — 전담 등재 PR 에서 +0.5 조정을 함께 처리한다.
- 서빙 facet 은 비전담도 "이름 (소속)" 라벨 + 기사 tier 그룹으로 분류하고, 조직 바이라인 (BBC Sport 등) 은 outlet 정식명으로 접는다.

## 2.7 매핑 · alias 제거 (해지) 체크리스트 (2026-07-19 신설)

등재의 역방향 — 표기 매핑을 없앨 때는 **생산 경로와 소비 경로를 쌍으로** 제거한다.

1. **생산 경로** — 그 표기를 outlet 값으로 만들어 내는 곳 (fmkorea `OUTLET_MAP` · 어댑터 payload).
2. **소비 경로** — `credibility.yaml` 의 해당 alias.
   생산처를 없애도 alias 를 남기면 향후 다른 매핑 경로가 같은 표기로 tier 를 재부여할 수 있는
   잠재 경로가 남는다 (2026-07-19 `[공홈]` 사례 — tier 0 이라 비용 최대,
   `docs/troubleshooting/2026-07-19-fmkorea-official-prefix-misattribution.md`).
3. **README 표** — §1 관례대로 같은 PR 에서 갱신.
4. **기존 적재분** — 잘못 부여된 행의 정리 (DELETE vs 강등 UPDATE) 는 별도 판단 · PR 에 기록
   (공홈 사례 = 5건 DELETE, PR #70).

## 3. tier 재조정 절차

- **두 파일 동시 수정** — 직접 수집 소스는 `sources.yaml`, 같은 매체의 언급 라우팅은 `credibility.yaml` outlets.
  한쪽만 바꾸면 "직접 수집 = 3 vs 트윗 인용 = 1.5" 처럼 같은 매체가 두 공신력으로 갈라진다 (PR #45 에서 The Guardian · Goal.com 동시 정합).
- **dbt 게이트 확인** — `stg_articles.tier` accepted_values 는 [0, 1, 1.5, 2, 3, 4].
  이 집합 밖 값을 도입하면 `dbt/models/sources.yml` 도 함께 수정.
- **기적재 혼재 인지** — `articles.tier` · `confidence_score` 는 적재 시점 스냅샷: 변경 후 신규 수집분만 새 값을 받고, 같은 소스에 신구 tier 가 혼재한다 (서빙 정렬만 영향 · dedup 무영향).
  과거분까지 맞추려면 backfill (실행 여부는 사용자 판단 — "당시 판단 보존" 관점도 유효):

```sql
-- confidence_score = 1 - tier/4 (score.confidence_from_tier 와 동일 산식)
UPDATE articles SET tier = 3, confidence_score = 0.25 WHERE source_id = 'guardian';
```

## 4. transfer_keywords 앵커 수정

- 최상위 `transfer_keywords: &transfer_kw` 1곳 수정이 참조 5개 소스 (bbc_sport · goal · football_london · guardian · skysports) 에 동시 반영된다.
- **참조는 병합이 아니다** — `*transfer_kw` 는 리스트 전체 치환이라 "공통 20개 + 소스별 추가 1개" 구성은 불가.
  개별화가 필요해지는 소스는 앵커 참조를 버리고 리스트를 복사해 독립시킨다.
- 수정 후 build 스모크로 어댑터별 최종 키워드를 눈으로 확인:

```bash
uv run python -c "
import os, yaml
os.environ.setdefault('GUARDIAN_API_KEY', 'dummy')   # factory 의 guardian skip 방지용
from bullet_in.adapters.factory import build_adapters
cfg = yaml.safe_load(open('config/sources.yaml'))
for a in build_adapters(cfg):
    print(a.source_id, getattr(a, 'title_keywords', None))"
uv run pytest -q
```

- 키워드 변경은 수집량에 직결 — 변경 후 첫 회차 `source_counts` 를 확인한다 (`2026-07-15-source-expansion-ops.md` §3 과 같은 축).

## 5. 관련

- 트러블슈팅: `2026-07-15-credibility-registry-curation-traps.md` (alias 경로 비대칭 · 동일인 중복 · 오탐 성씨).
- 런북: `2026-07-15-source-expansion-ops.md` (신규 소스 배포 체크 · 드리프트 진단).
