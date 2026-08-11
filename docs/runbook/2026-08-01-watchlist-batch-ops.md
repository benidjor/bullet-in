# 링크 선수 워치리스트 배치 운영 절차 (2026-08-01)

정기 회차와 분리된 전용 배치 (`watchlist_fmkorea.py`) 의 VM 반영 · 관측 · 커서 리셋 · 증량 절차를 다룬다.
배치는 fmkorea 를 검색해 적재까지만 하고 번역 · 분류 · 렌더는 다음 정기 회차가 이어받는다.
설계 스펙: `docs/superpowers/specs/2026-08-01-linked-player-watchlist-design.md` (§8 배포 · 검증 · 관찰).

## 1. 개요

- **역할** — `status='confirmed' AND transfer_status IN (in_link, out_link)` 인 활성 이적축 선수의 한글 표기를 fmkorea 제목에서 로테이션 검색한다.
  슬라이스당 10명, 검색 실패가 없으면 커서가 다음 슬라이스로 전진한다.
- **적재만** — Gemini 를 호출하지 않는다.
  신규 글은 raw (Mongo) · mart (MariaDB) 에만 쌓이고 한글 요약 · 이적 단계 분류 · 화면 노출은 다음 정기 회차 enrich 가 채운다.
- **정기 회차와의 관계** — 같은 fmkorea 어댑터 부품 (`build_fmkorea_adapter` · `persist` · `tunnel_alive`) 을 재사용하되 진입점은 별도다.
  실행 주기도 분리돼 있어서 (정기 +90분 오프셋) 배치가 fmkorea 에서 430 을 맞아도 정기 회차의 접촉 예산은 그대로 남는다.

## 2. VM 최초 반영 절차

```bash
cd ~/bullet-in && git log --oneline -1     # VM 이 어느 커밋인지 먼저 확인
git pull --ff-only
sudo cp infra/systemd/bullet-in-watchlist.* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now bullet-in-watchlist.timer
systemctl list-timers bullet-in-watchlist.timer --no-pager
```

`list-timers` 출력의 `NEXT` 줄이 다음 실행 예정 시각이다.
직후 한 회차를 기다렸다가 §3 으로 완료 로그를 확인한다.

## 3. 배치 관측

```bash
journalctl -u bullet-in-watchlist -n 50
```

정상적으로 끝나면 아래 형태의 로그가 한 줄 찍힌다 (`watchlist_fmkorea.main`, 값은 예시).

```
워치리스트 배치 완료 — 검색 10명 · 적재 3 · 동일 내용 생략 1 · 기존 기사 유지 0 · 필터 탈락 2 · 검색 실패 0 · 커서 187
```

필드별 의미는 다음과 같다.

- **검색 N명** — 이번 슬라이스에서 제목 검색을 시도한 선수 수 (기본 10, 명단이 10명 이하면 전원).
- **적재** — mart 에 새로 쌓인 기사 수.
- **동일 내용 생략** — content_hash 가 이미 있어 건너뛴 수 (중복).
- **기존 기사 유지** — URL 정합 보호로 기존 완전체 기사를 스텁이 덮어쓰지 않고 유지한 수.
- **필터 탈락** — 무관 글 필터 (구단 키워드 · 링크 선수 사전) 를 통과하지 못해 버려진 수.
- **검색 실패** — 키워드 검색 자체가 실패한 수 (rate limit · 기타 HTTP 오류 · 네트워크 오류).
- **커서** — 다음 배치가 이어받을 마지막 검색 선수 id, 검색 실패가 있으면 커서를 전진시키지 않고 `유지` 로 찍힌다.

배치는 세 경로에서 스킵되고 경로마다 로그 문구가 다르다 (실행하지 않으므로 완료 로그는 안 찍힌다).

- **fmkorea 터널 미접속** — `fmkorea 터널 미접속 — 워치리스트 배치 스킵 (커서 무전진 · 스탬프 무기록)`
- **60분 가드** (마지막 fmkorea 접촉이 60분 이내) — `워치리스트 배치 스킵 — 마지막 fmkorea 접촉 <시각> (60분 이내)`
- **활성 링크 0명** (시장 폐장으로 명단 전원 archived) — `활성 링크 선수 0명 — 검색 없이 정상 종료 (시장 폐장 휴면)`

## 4. 관찰 3종 (스펙 §8)

증량할지는 아래 세 관찰이 며칠 쌓인 뒤에 판단한다.

### 4.1. 배치 429 · 430 비율

fmkorea 의 실제 rate limit 응답이 표준 429 가 아니라 자체 430 이었던 사례는 이미 기록돼 있다 (`docs/runbook/2026-07-13-fmkorea-search-adapter-ops.md` §rate-limit).
어댑터는 429 만 전용 문구로 남기고 그 외 상태 코드는 일반 HTTP 경고로 남긴다.
그러니 코드값을 특정하지 말고 검색 실패 계열 로그를 통째로 센다.

```bash
journalctl -u bullet-in-watchlist | grep "fmkorea 검색"
```

완료 로그의 `검색 실패` 필드를 회차별로 누적해도 수는 같다.
비율이 크면 (특히 커서가 여러 회차 연속으로 `유지` 로 찍히면) §5 의 슬라이스 반복 이상이다.

### 4.2. 무관 글 비중

```bash
journalctl -u bullet-in-watchlist | grep "무관 글 필터 탈락"
```

건수가 크면 (§4.1 검색 대비 탈락 비율이 높으면) 스펙 §9 범위 밖으로 미뤄둔 이적 키워드 수집 필터를 후속으로 검토한다.

탈락뿐 아니라 통과 쪽의 동명이인 글도 이 관찰의 대상이다.
필터의 선수명 조항은 제목에 선수명이 있으면 통과시키므로, 같은 이름의 다른 인물 글도 들어온다
(첫 dry-run 실측 2026-08-02: "비에이라" 검색이 세네갈 감독 후보 파트릭 비에이라 글을 통과).
단계 분류가 other 로 처리해 화면 노출 부담은 적지만, 비중이 크면 이적 키워드 필터 검토 근거에 함께 넣는다.

### 4.3. 일순 주기

커서가 명단 끝을 돌아 최소 id 로 복귀하는 간격을 잰다.

```bash
journalctl -u bullet-in-watchlist | grep "워치리스트 배치 완료"
```

각 줄의 `커서 <id>` 값을 시간순으로 나열한 뒤 값이 이전보다 작은 id 로 떨어지는 시점 (한 바퀴 완주) 사이의 간격을 잰다.
슬립 (신규 후보 확정으로 명단이 늘거나 archived 로 줄어드는 변동) 이 섞이면 주기가 흔들린다.
그 구간의 명단 크기 변화도 함께 기록해 둔다.

## 5. 커서 리셋

경로는 `~/.bullet-in/watchlist_cursor` 이며 마지막으로 검색한 선수 id 하나만 담는다.

- **전체 재시작** (처음부터 다시 로테이션) — `rm ~/.bullet-in/watchlist_cursor`
- **특정 지점부터 재개** — `echo <player_id> > ~/.bullet-in/watchlist_cursor`

리셋이 필요한 경우는 둘이다.

- 명단 대개편 직후 (다수 확정 · archived 전이로 로테이션 순서가 크게 바뀐 뒤).
- §4.3 에서 슬라이스가 같은 구간을 반복하는 이상이 보일 때.

## 6. 증량 절차 (4회 → 8회)

§4 관찰 3종이 문제없이 통과하고 사용자가 증량을 결정한 뒤에만 진행한다.

1. `infra/systemd/bullet-in-watchlist.timer` 의 `OnCalendar` 를 아래로 바꾼다.

   ```
   OnCalendar=*-*-* 01/3:30:00 UTC
   ```

   정기 회차와 동일한 3시간 간격으로 하루 8회 실행되며 정기 회차 대비 +90분 오프셋은 그대로다.
2. repo 에 커밋한다.
3. VM 에 반영한다 (§2 와 동일한 세 단계).

   ```bash
   cd ~/bullet-in && git pull --ff-only
   sudo cp infra/systemd/bullet-in-watchlist.timer /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl restart bullet-in-watchlist.timer
   ```

## 6.1 실행 시각 이동 (낮 배치를 밤으로)

증량과는 별개로, 낮에 도는 두 배치를 밤으로 옮기는 안이다.
2026-08-11 관찰 33회 실측이 근거다.

### 6.1.1 실측

검색 실패로 한 건도 못 건진 회차 (이하 전멸) 가 33회 중 14회 (42%) 였고 시각대에 쏠려 있었다.

| 시각 (KST) | 전멸 빈도 |
| --- | --- |
| 07:30 · 13:30 (낮) | 8회 중 5회꼴 |
| 01:30 · 19:30 (밤) | 1~2회 |

같은 코드 · 같은 명단 · 같은 60분 가드로 도는데 결과가 갈리므로 시각대 요인으로 본다.
다만 fmkorea 쪽 부하인지 다른 이유인지는 확인하지 못했다 — 상대 서버 사정이라 우리 로그로는 가릴 수 없다.
그래서 이 이동은 원인 규명이 아니라 실측에 맞춘 경험적 대응이다.

### 6.1.2 바꿀 값

```
OnCalendar=*-*-* 10,13,16,19:30:00 UTC
```

KST 로는 19:30 · 22:30 · 01:30 · 04:30 이다.

- 하루 4회는 그대로라 일순 주기 (§4.3) 는 바뀌지 않는다.
- 정기 회차 (`00/3` UTC) 대비 +90분 오프셋도 그대로다 — 네 시각 모두 정기 정시 + 90분 지점이다.
- 정기 회차와 60분 이상 떨어져 있어 접촉 예산 규율 (§7) 도 유지된다.

### 6.1.3 절차

VM systemd 반영이 필요하므로 배포 주체가 있는 회차에 함께 넣는다.

1. `infra/systemd/bullet-in-watchlist.timer` 의 `OnCalendar` 를 위 값으로 바꾸고 `Description` 의 시각 표기도 함께 고친다.
2. repo 에 커밋한다.
3. VM 에 반영한다.

   ```bash
   cd ~/bullet-in && git pull --ff-only
   sudo cp infra/systemd/bullet-in-watchlist.timer /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl restart bullet-in-watchlist.timer
   systemctl list-timers bullet-in-watchlist.timer --no-pager
   ```

4. `list-timers` 의 `NEXT` 가 새 시각인지 확인한다.

### 6.1.4 검증

이동 후 30회 남짓 (약 일주일) 쌓인 뒤 전멸 비율을 다시 센다.

```bash
journalctl -u bullet-in-watchlist | grep "워치리스트 배치 완료"
```

각 줄의 `검색 실패` 값이 검색 인원과 같으면 그 회차가 전멸이다.
비율이 42% 에서 눈에 띄게 내려가지 않으면 시각대 요인이 아니었다는 뜻이므로 원래 시각으로 되돌린다.

되돌릴 때는 `OnCalendar=*-*-* 04/6:30:00 UTC` 로 바꾸고 같은 절차를 반복한다.

## 7. 수동 실행 · dry-run

```bash
cd ~/bullet-in && set -a; source .env; set +a
uv run python -m bullet_in.watchlist_fmkorea --dry-run --force 2>&1 | tee /tmp/watchlist-dryrun.log
```

`--dry-run` 은 적재 없이 검색 · 필터 결과만 출력하고 커서를 전진시키지 않는다.
`--force` 는 60분 가드를 무시하고 즉시 실행한다.
dry-run 도 실제로 검색을 거는 만큼 아래 접촉 규율을 지킨다.

- 실행 전 직전 회차가 200 으로 끝났는지 `journalctl -u bullet-in-watchlist -n 20` 으로 먼저 확인한다.
- 출력은 항상 `tee` 로 파일에 남긴다.
- 출력을 다시 보고 싶다는 이유만으로 재실행하지 않는다 — 재실행은 재접촉이고 단시간 재접촉은 430 을 부른다.
- 검증을 두 번 이상 나눠 실행할 때의 이격은 60분까지 필요 없다.
버스트 상한 실측이 약 18요청 · 16분 창이므로 (`docs/troubleshooting/2026-07-30-fmkorea-contact-budget-and-search-reach.md`),
요청 합이 상한 아래면 20~30분 이격으로 충분하다 (2026-08-02 머지 전 검증 실측: discover 1건 + 26분 뒤 dry-run 13건 · 430 없음).
단 정기 회차 정시와는 60분을 띄운다.

## 8. 참고

- 설계 스펙: `docs/superpowers/specs/2026-08-01-linked-player-watchlist-design.md`
- fmkorea rate limit (HTTP 430) 배경: `docs/runbook/2026-07-13-fmkorea-search-adapter-ops.md`
- 선수 명단 운영 (확정 · 백필 · 생애주기 전이): `docs/runbook/2026-07-31-player-roster-ops.md`
- VM 반영 절차 일반: `docs/runbook/2026-07-20-vm-cohost-bootstrap.md` §6.1
