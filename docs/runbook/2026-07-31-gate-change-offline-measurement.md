# 게이트 규칙 변경의 영향을 접촉 없이 재는 절차 (2026-07-31)

번역 게이트는 전 소스가 공유하는 로직이라 규칙 하나를 바꾸면 영향 범위를 미리 알기 어렵다.
2026-07-30 재번역 큐 작업에서 쓴 측정 절차를 다시 돌릴 수 있게 여기 정리해 둔다.

**Gemini 호출 · 외부 사이트 접촉이 한 번도 없다.**
게이트는 결정적 후처리라 저장된 데이터만 있으면 규칙 변경의 결과를 그대로 재현할 수 있다.
재번역을 돌려 봐야 알 수 있는 것 (모델이 다음번에 뭐라고 쓸지) 만 이 절차 밖이다.

## 1. 언제 쓰나

- 게이트 축의 판정 규칙을 바꾸기 전 · 후 (조건 추가 · 임계값 변경 · 예외 소스 추가).
- 사전 (`name_map` · `club_map` · `glossary`) 을 늘리기 전에 발화가 얼마나 늘고 주는지 볼 때.
- "이 규칙을 넣으면 정당한 검출을 얼마나 잃는가" 를 수치로 답해야 할 때.

## 2. 1단계 — journal 에서 발화 이력을 재구성한다

게이트 발화는 WARNING 으로만 남고 DB 에 이력 테이블이 없다.
journal 이 사실상 유일한 시계열이다.

```bash
sudo journalctl -u bullet-in --output=short-iso \
  | grep -E "재번역 큐\(1차\)|제목 해소|제목 의심 잔존" \
  | sed -E "s/^([0-9-]+T[0-9:]+).*(재번역 큐\(1차\)|제목 해소|제목 의심 잔존).*content_hash=([0-9a-f]{8})[0-9a-f]*.*/\1 \2 \3/"
```

행마다 진입 · 종착 시각이 한 줄씩 나오므로 큐 체류 시간을 셀 수 있다.
2026-07-30 실측에서는 1차 진입 26건 중 해소 8건이 전부 1~2 회차 (3~6시간) 안에 풀렸고 한 건만 25시간 넘게 남아 있었다.

사유별 분포는 따로 센다.

```bash
sudo journalctl -u bullet-in | grep -oP "인명 누락:\K[A-Za-z]+" | sort | uniq -c | sort -rn
```

**주의 두 가지.**

- journal 보존 기간 밖은 안 나온다.
`sudo journalctl -u bullet-in --output=short-iso | head -2` 로 실제 시작 시각을 먼저 확인하고 그 범위를 근거 범위로 밝힌다.
- 로그 문구는 바뀐다.
2026-07-30 에 `재번역 재시도 잔존 → 재큐` 가 `제목 의심 잔존 — 수동 확인` 으로 바뀌었다.
과거 구간을 볼 때는 옛 문구도 함께 grep 한다.

## 3. 2단계 — 라이브 데이터를 한 벌 뜬다

VM 의 mart 에서 필요한 칼럼만 TSV 로 받는다.

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'docker exec bullet-in-mariadb-1 mariadb -uroot -pbulletin bulletin --batch -N -e "
   SELECT LEFT(content_hash,8),
          REPLACE(REPLACE(COALESCE(title_original,\"\"),\"\t\",\" \"),\"\n\",\" \"),
          REPLACE(REPLACE(CONCAT(COALESCE(body_source,\"\"),\" \",COALESCE(body_excerpt,\"\")),\"\t\",\" \"),\"\n\",\" \")
   FROM articles"' > full.tsv
```

`--batch` 는 탭으로 칼럼을 가르므로 값 안의 탭 · 개행을 반드시 지운다.
안 지우면 칼럼이 밀려 조용히 틀린 집계가 나온다.
받은 뒤 필드 수를 세어 확인한다.

```bash
awk -F'\t' '{c[NF]++} END {for (k in c) print "필드수", k, "→", c[k] "행"}' full.tsv
```

모든 행이 같은 필드 수여야 한다.

## 4. 3단계 — 검출기를 직접 돌려 규칙 두 개를 비교한다

파이프라인을 돌리지 않고 검출기 함수만 import 한다.
**같은 함수를 써야 한다** — 규칙을 스크립트에 옮겨 적으면 실물과 어긋난다.

```bash
uv run python - <<'PY'
import re, yaml
from bullet_in.enrich import _has_name_context     # 배포된 규칙 그대로
sur = sorted(set(yaml.safe_load(open('config/name_map.yaml'))['names'].values()))
rows = [l.rstrip('\n').split('\t') for l in open('full.tsv')]
tot, sup = 0, []
for s in sur:
    b = re.compile(rf"\b{s}\b")
    for h, to, bd in rows:
        if not b.search(to):
            continue
        tot += 1
        if not _has_name_context(f"{to} {bd}", s):
            sup.append((h, s, to[:66]))
print(f"제목 성 출현 {tot}건 · 검사 면제 {len(sup)}건 ({len(sup)/tot:.0%})")
for h, s, t in sup:
    print(f"   {h} {s:11s} {t}")
PY
```

`uv run` 을 쓴다 — 시스템 `python3` 는 3.9 라 이 코드가 임포트 단계에서 죽는다.

후보 규칙이 여럿이면 같은 모집단에 차례로 적용해 표로 만든다.
2026-07-30 측정 결과가 이 형태였다.

| 규칙 | 통과 | 검사 면제 | 면제율 |
| --- | --- | --- | --- |
| 본문 대조 | 76 | 56 | 42% |
| 풀네임 근거 | 129 | 3 | 2% |
| 풀네임 근거 + 기능어 제외 | 128 | 4 | 3% |

면제율만 보지 말고 **면제되는 행의 목록을 눈으로 확인한다.**
42% 와 3% 는 규칙의 우열이 아니라 성격의 차이였다.
어느 쪽이 정당한 검출을 자르는지는 목록을 봐야 안다.

## 5. 4단계 — 수치를 문서에 적을 때는 배포 목록으로 다시 잰다

설계 단계의 측정과 실제로 머지된 코드가 어긋날 수 있다.
2026-07-30 에는 브레인스토밍용 스크립트의 기능어 목록과 배포된 `_NAME_CONTEXT_STOPWORDS` 가 원소 두 개 달랐다.

그래서 문서에 수치를 확정하기 전에 **배포된 상수를 import 해서** 한 번 더 돌렸다.
결과가 같아 (면제 4건 · 3%) 스펙 수치를 그대로 뒀다.

목록 · 임계값을 나중에 바꾸면 이 수치를 다시 재야 한다.
그 사실을 상수 옆 주석에 적어 두면 다음 사람이 안다.

## 6. 함정

- **모집단을 밝히지 않은 비율은 쓸모가 없다.**
"제목에 등재 성이 나타난 132건 중 4건" 처럼 분모를 함께 적는다.
- **하루치 · 한 쌍만 보고 결론 내지 않는다.**
journal 전체 기간과 라이브 전건을 함께 본 뒤에야 원인을 말한다.
- **본문이 없는 행이 상당수다.**
본문을 근거로 쓰는 규칙은 이 집단에서 통째로 꺼진다.
`title_only_rows` 경로로 들어온 행이 여기 해당한다.
- **`title_ko` 가 이미 채워진 행은 재선별 대상이 아니다.**
규칙을 고쳐도 저장된 값은 그대로다.
과거 행까지 고치려면 `title_ko` 를 NULL 로 되돌려 큐에 다시 넣어야 한다.
그때는 Gemini 요금이 든다.

## 7. 참고

- 게이트 운영 · 전수 스윕 — `docs/runbook/2026-07-19-translation-quality-gates-ops.md`.
- 이 절차를 쓴 설계 — `docs/superpowers/specs/2026-07-30-retranslation-queue-terminal-state-design.md`.
- 같은 작업에서 나온 함정 — `docs/troubleshooting/2026-07-31-gate-verdict-and-signature-drift.md`.
- 프롬프트 판본 비교 측정 — `docs/runbook/2026-07-29-prompt-revision-measurement.md`.

