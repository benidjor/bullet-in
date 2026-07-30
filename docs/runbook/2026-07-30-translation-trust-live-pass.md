# 런북 — 번역 신뢰성 라이브 반영 (2026-07-30)

계획서 `2026-07-29-translation-trust.md` 의 Task 1 과 Task 10 을 실행한 기록이다.
원문 없이 지어낸 한국어 본문을 없애고 복제 게이트 임계값을 확정하는 것이 목표였다.

명령과 실제 출력을 그대로 남긴다.
같은 절차를 다시 돌릴 때 순서와 확인 지점이 어디인지가 요지다.

## 1. 실행 순서 — 왜 이 순서인가

```
① 설정 반영 (football.london enabled: false) → 머지 → VM pull
② 덤프 → DELETE → 재렌더 → 배포
③ 지어낸 본문 필드 비우기
④ 게시글 본문 채우기
⑤ 정기 회차가 재작성 (게이트 첫 실행)
⑥ 잔존율 분포로 임계값 확정
```

①이 ②보다 먼저다.
순서가 바뀌면 다음 회차가 지운 행을 다시 수집한다.

③이 ④보다 먼저인 이유는 ④가 실패해도 지어낸 본문은 이미 사라져 화면이 정직해지기 때문이다.
④는 라이브 접촉이라 실패할 수 있다.

## 2. VM 준비

정기 회차는 자동으로 `git pull` 하지 않는다.
머지 후 반드시 수동 반영한다.

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'export PATH="$HOME/.local/bin:$PATH"; cd ~/bullet-in && git pull --ff-only && git log --oneline -1'
```

새 컬럼이 있으면 스키마를 먼저 적용한다.
`ops_snapshot` 이 `rewrite_retention` 을 참조하므로, 컬럼 없이 렌더하면 ops 생성이 실패한다.

```python
MartStore(create_engine(os.environ["MARIADB_URL"])).ensure_schema()
```

- **비대화형 SSH 는 `uv` 를 못 찾는다** — 원격 스크립트 서두에 `export PATH="$HOME/.local/bin:$PATH"` 를 고정한다.
- **긴 스크립트는 stdin 으로 넘긴다** — `ssh ... 'uv run python -' < script.py`.
따옴표 중첩으로 f-string 이 깨지는 것을 피할 수 있다.

## 3. football.london 제거

### 3.1. 덤프 — `mysqldump` 가 아니라 컨테이너의 `mariadb-dump`

```bash
U=$(grep "^MARIADB_URL=" .env | sed -E "s#.*://([^:]+):([^@]+)@[^/]+/([^?]+).*#\1|\2|\3#")
USER="${U%%|*}"; REST="${U#*|}"; PASS="${REST%%|*}"; DB="${REST##*|}"
docker exec bullet-in-mariadb-1 mariadb-dump -u"$USER" -p"$PASS" --no-tablespaces \
  --single-transaction --no-create-info \
  --where="source_id='football_london'" "$DB" articles > ~/football-london-100rows-$(date +%Y%m%d).sql
```

실측 — 811K · `football_london` 101회 등장 (100행 + 헤더 주석).
비밀번호를 옮겨 적지 않고 `.env` 에서 뽑는다.

### 3.2. 삭제

```
삭제 100행 · 전체 505 → 405
football_london 잔여 0 · Tom Canton 잔여 0
재료 없이 body_ko 있는 행 71 → 29
```

계획서의 95행은 2026-07-27 사본 값이고 실측은 100행이었다.
소스를 내리기 전까지 3시간마다 계속 수집되고 있었다.

### 3.3. 재렌더 · 배포

```
load_sources 에 football_london 있나: False
site 재생성: 405 행 · site/article/*.html 405개 (고아 100개 제거)
Uploaded 408 files (5 already uploaded)
```

- **삭제와 재렌더 사이에 정기 회차가 끼면** football.london 행이 `serving` 조회에 실패해 `full` 대신 `excerpt` 로 렌더된다.
`serving_mode` 가 안전 기본값을 쓰므로 깨지지는 않는다.
- **남는 것 1건** — `all.html` 의 `i2-prod.football.london` 이미지 URL 이다.
fmkorea 가 퍼온 football.london 기사 (outlet 표기 `풋볼런던`) 로, 직수집만 멈춘 것이라 정책과 부합한다.
계획서는 애그리게이터 경로로 `x_backtrack` 만 적었는데 fmkorea 도 같은 경로다.

### 3.4. 라이브 검증 — 캐시를 우회해야 한다

`curl` 로 확장자 경로를 치면 308 이고 본문이 비어 나온다.
`-L` 없이 grep 하면 "없음" 이 나와 잘못된 판정을 만든다.
실제로 ⑥ 절이 배포됐는데 없다고 오판했다.

```bash
curl -sL "https://bullet-in.pages.dev/all?cb=$(date +%s)" | grep -c -i "Tom Canton"
curl -sL "https://<배포해시>.bullet-in.pages.dev/ops" | grep -o "<h2>[^<]*"
```

쿼리스트링 캐시버스터나 배포 고유 URL 로 재확인한다 (`2026-07-27-pages-deletion-verification-traps.md`).

## 4. 지어낸 본문 필드 비우기

지우기 전에 값을 파일로 보존한다.

```
대상 29 행
보존: ~/fabricated-bodies-20260730.json (48KB · title_ko · summary · body_ko 전문)
정리 29 행 (title_ko 는 유지)
재료 없이 body_ko 남은 행: 0
```

`title_ko` 를 남기는 이유는 NULL 로 만들면 매 회차 재선별 대상이 되고 '번역 대기' 배지가 영구히 붙기 때문이다.

상세 페이지가 사유 문구로 바뀐 것을 배포 고유 URL 로 확인했다.

```
원문 본문을 확보하지 못해 : 1
자동 번역한 것입니다      : 0
아르테타 · 방출 조항 · 재정적 페어플레이 : 각 0   ← 지어낸 3건 전부 제거
제목                    : 유지
```

## 5. 게시글 본문 채우기

```bash
uv run python -m bullet_in.backfill_fmkorea_body --pages 1 --force 2>&1 | tee ~/bf-fill.log
```

```
본문 빈 fmkorea 행 29건
검색 3회 200 · 검색 후보 60건 · 제목 일치 7/29건
글 fetch 7회 전부 200
대상 29 · 일치 7 · 채움 7 · 금지·본문없음 0 · 실패 0
```

채운 7건의 본문은 873~4899자이고 기자명 2건이 본문에서 추출됐다.

- **`--pages 3` 은 쓰지 않았다** — 검색 요청이 3회에서 9회로 늘어 누적 예산을 빨리 쓴다.
- **접촉 예산 · 430 의 성격** — `docs/troubleshooting/2026-07-30-fmkorea-contact-budget-and-search-reach.md`.
같은 명령이 16분 간격으로 성공하고 실패했다.
- **못 채운 22건** — 수집용 고정 키워드로는 주소를 찾을 수 없었다.
`--by-title` 경로 (PR #162) 로 회수하고 라이브 확인은 접촉 예산 회복 후에 한다.

## 6. 재작성 — 정기 회차에 맡긴다

`enrich` 만 따로 돌리지 않았다.
채우기가 번역 4필드를 NULL 로 되돌리므로 다음 정기 회차가 `rows_missing_translation` 으로 자동 선별한다.
렌더 · 배포까지 `ExecStartPost` 가 한다.

21:03 KST 회차 결과다.

```
new_or_changed 7 · errors {} · success_rate 1.0 · elapsed 170s
전체 405 → 412행
x_afcstuff 2 → 7건 · fmkorea 1 · goal 1
잔존율 기록 8건
번역 대기 8 → 2
```

Gemini 호출은 재작성 8건 (행당 1~3회) + 번역 1건이었다.

## 7. 임계값 확정 — 0.75 유지

게이트가 처음 돈 회차의 잔존율 분포다.

| 잔존율 | 매체 | 본문 | 시도 |
| --- | --- | --- | --- |
| 0.76 | The Telegraph | 4459자 | 1 |
| 0.62 | (아르테타 인터뷰) | 3241자 | — |
| 0.59 | ESPN | 2236자 | — |
| 0.51 | BeSoccer | 3593자 | — |
| 0.48 | The Telegraph | 1864자 | 3 |
| 0.30 | 메일 | 3340자 | — |
| 0.27 | Sky | 795자 | — |
| 0.13 | ESPN | 1800자 | — |

```
중앙값 ≈ 0.495 · 0.75 초과 1/8 (12.5%) · 재시도 3회 도달 1/8
```

중앙값이 임계값을 크게 밑돌고 초과가 1건뿐이라 **0.75 를 유지**한다.
표본이 The Telegraph · ESPN · BeSoccer · Sky · 메일 계열이므로 스펙 §8 의 "The Athletic 44건 표본" 우려도 함께 해소됐다.

`ops.html` ⑥ 절에 초과 1건 (`97e82280` · The Telegraph · 0.76) 이 노출된다.

## 8. 검증 기준 대조 (스펙 §7)

| 기준 | 결과 |
| --- | --- |
| ① 본문 빈 fmkorea 0건 또는 사유 확인 | **부분** — 22건 잔존 · 사유는 검색 도달 범위 (퍼가기 금지 아님) |
| ② 재생성 행의 숫자 누락 0개 | **부분** — 8건 중 1건에 누락 `40` 이 3회 시도 후 잔존 |
| ③ ops ⑥ 절에 초과 목록 · 건수 | **충족** — 1건 노출 |
| ④ football.london 0건 · Tom Canton 없음 | **충족** |
| ⑤ 본문 없는 행의 상세 페이지 정상 | **충족** — 사유 문구로 렌더 |

①과 ②가 부분 충족이다.
①은 `--by-title` 회수로 이어지고, ②는 게이트가 폐기 조건이 아니므로 설계대로 채택한 결과다 (스펙 §4.4).

## 9. 남은 것

- **재번역 큐 무한 루프** — `White flag` 를 인명 누락으로 오판해 같은 행이 하루 8회 재큐된다.
상한이 없어 매 회차 Gemini 를 헛되게 부른다 (`2026-07-30-silent-drops-and-blind-alerts.md` §3).
- **`--by-title` 라이브 확인** — 직전 회차 검색이 200 이면 `--limit 1` 로 시도한다.
- **신선도 알림 오진** — 별도 트랙 (세션 메모리 `slo5-freshness-alert-track`).

## 10. 참고

- 계획서 — `docs/superpowers/plans/2026-07-29-translation-trust.md`
- 스펙 — `docs/superpowers/specs/2026-07-29-translation-trust-design.md`
- 접촉 예산 · 검색 도달 — `docs/troubleshooting/2026-07-30-fmkorea-contact-budget-and-search-reach.md`
- 조용한 드롭 · 알림 오진 — `docs/troubleshooting/2026-07-30-silent-drops-and-blind-alerts.md`
- enrich 전용 패스 — `docs/runbook/2026-07-19-enrich-only-pass.md`
