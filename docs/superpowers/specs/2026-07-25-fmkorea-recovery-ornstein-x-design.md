# fmkorea 수집 복구 · 온스테인 X 직접 수집 설계 (2026-07-25)

fmkorea 를 맥 경유 프록시로 복구하고, David Ornstein 의 X 계정을 새 직접 수집 소스로 추가하는 설계다.
두 소스는 "속보는 온스테인 X · 전문은 fmkorea" 로 역할을 나눠, fmkorea 의 맥 의존 지연이 이적 속보의 최신성을 해치지 않게 한다.

## 1. 배경

- fmkorea 가 VM 이관 (2026-07-20) 첫 회차부터 전 회차 HTTP 430 이다.
  발신 IP 가 Oracle 데이터센터 대역이라 fmkorea 보안 시스템이 차단하며, 코드 · 셀렉터는 무결하다
  (진단 SoT: `docs/troubleshooting/2026-07-24-fmkorea-vm-ip-persistent-430.md`).
- Tor 우회는 2026-07-25 실측에서 명시적으로 거부됐다
  — fmkorea 가 "Tor 및 일부 VPN IP 는 접속이 허용되지 않습니다" 를 반환 (차단 종류 6).
  이로써 데이터센터 · Tor · 알려진 VPN 대역이 모두 막히고, 통과 가능한 것은 실제 주거용 IP 뿐임이 확정됐다.
- fmkorea 는 행 수로는 전체의 8.4% (25 / 299) 지만, 신뢰도 최상위 tier 1 기사의 52% (14 / 27) 를 담당한다.
  25건 중 16건이 The Athletic 원문이고, The Athletic 은 페이월이라 fmkorea 가 유일한 확보 창구다.
- 온스테인 본인 X 계정은 현재 직접 수집하지 않는다.
  afcstuff 가 인용해 줄 때만 간접적으로 걸려, afcstuff 가 인용하지 않은 온스테인 속보는 놓친다.

## 2. 목표 · 비목표

목표.

- fmkorea 정기 수집을 실제 주거용 IP (맥) 경유로 복구한다.
- 맥이 켜지는 순간 밀린 fmkorea 를 자동으로 보충 수집한다 (사용자 개입 없음).
- 07-20 이후 누락된 fmkorea 글 (감사 실측 17건+) 을 검색 페이징으로 소급 복원한다.
- 온스테인 X 계정을 직접 수집 소스로 추가해 딜 속보의 최신성을 맥 가동과 무관하게 확보한다.

비목표.

- 유료 프록시 · 타 VPS 이전은 채택하지 않는다 (실측으로 열위 · 도박성 확정).
- 제목 번역 게이트 오탐 · arsenal 퍼널 로그 부재는 이 트랙 밖의 별도 후속이다.
- team 오저장 (fmkorea 25행 전부 arsenal 고정) 은 B3 트랙 몫이다.

## 3. 아키텍처 — 두 소스의 역할 분담

```
온스테인 X (신규)   ──> 딜 속보 · 요약      : VM 직접 접촉 · 맥 무관 · 고정 tier 1
fmkorea (1-B 복구)  ──> The Athletic 전문   : 맥 릴레이 프록시 · 지연 허용
```

- 최신성이 급한 정보 (딜 속보) 는 온스테인 X 가 VM 에서 직접 가져온다.
  맥이 꺼져 있어도 속보는 나가므로, fmkorea 는 더 이상 3시간 주기를 지켜야 하는 소스가 아니다.
- 두 소스가 같은 사건을 다루면 서빙 계층이 인명 기준으로 묶는다 (§7).

## 4. 파트 1 — fmkorea 1-B (맥 릴레이 프록시)

### 4.1 터널

- 맥에서 VM 으로 역방향 SSH 동적 포워딩 (`ssh -R`) 을 상주시킨다.
  VM 쪽 `localhost:<포트>` 가 맥을 출구로 쓰는 SOCKS 프록시가 된다 (맥에 별도 프록시 소프트웨어 불필요).
- 끊겨도 다시 붙도록 autossh 로 감싸고, 맥 launchd 로 상주시킨다 (최초 1회 설정).
  Tailscale 등 추가 서비스는 도입하지 않는다 (autossh 가 의존성 최소).

### 4.2 어댑터 proxy 주입 — 3곳 변경

- proxy 는 환경변수 `FMKOREA_PROXY` 로 준다 (예: `socks5://127.0.0.1:<포트>`)
  — 배포 환경 분리 · 시크릿 성격 · 로컬 무영향 (2026-07-25 plan 에서 sources.yaml 방식 대신 확정).
- `src/bullet_in/adapters/factory.py` 의 `FmkoreaAdapter(...)` 생성에 `proxy=os.environ.get("FMKOREA_PROXY")` 를 전달한다.
- `src/bullet_in/adapters/fmkorea.py` 의 `__init__` 에 `proxy` 파라미터를 받아 저장하고,
  `fetch` 안의 `httpx.AsyncClient(...)` 생성 지점에 `proxy=self.proxy` 를 넘긴다 (httpx 0.28 은 `proxy=`, `proxies=` 없음).
- httpx 의 socks5 프록시는 `socksio` 가 필요하다.
  현재는 twikit 의 transitive 의존으로만 설치돼 있어 pyproject 에 `httpx[socks]` 로 명시한다 (twikit 제거 시 조용히 깨지는 것 방지).
- `FMKOREA_PROXY` 미지정이면 현행 동작 (직접 접속) 을 유지해, 다른 소스 · 로컬 개발은 영향받지 않는다.

### 4.3 정기 회차 동작

- 맥이 켜져 있으면 VM 정기 회차가 터널을 타고 fmkorea 를 정상 수집한다.
- 맥이 꺼져 있으면 터널 연결 실패 → httpx 전송 오류 → 어댑터의 기존 키워드별 스킵 강등이 그대로 동작한다
  (크래시 없음 · 다른 소스 무영향).

### 4.4 보충 수집 — 맥 깨어남 트리거 (A 절충형)

- 맥 launchd 가 깨어날 때, VM 에 "fmkorea 만 수집" 을 원격 트리거한다 (터널 위 SSH 명령).
- **중복 가드는 이 보충 수집에만 적용한다** (정기 회차는 타이머 스케줄대로 가드와 무관하게 돈다).
  맥 깨어남 시 fmkorea 마지막 접촉이 3시간 이내면 스킵한다.
- 가드 기준은 "마지막 접촉" — VM 로컬 접촉 스탬프 파일과 DB `MAX(fetched_at)` 중 최신값 (2026-07-25 재검토 반영).
  DB 워터마크는 신규 행이 적재될 때만 전진하므로, 단독으로 쓰면 새 글 없는 시간대에 launchd 주기 (15분) 마다 재접촉하는 구멍 (fail-open) 이 생긴다.
- 보충 스크립트는 수집 전에 SOCKS 포트 TCP 연결성만 확인한다 (fmkorea 접촉 아님).
  터널이 없으면 스탬프 없이 종료하고 (다음 주기 재시도), 터널이 있으면 수집 후 신규 건수와 무관하게 접촉 시각을 스탬프한다.
- 잔여 리스크 (허용) — 정기 회차의 접촉은 스탬프에 잡히지 않아, 새 글 없는 시간대에 정기 접촉 후 2시간 안에 보충 접촉이 드물게 겹칠 수 있다 (빈도 3시간당 최대 1회).
- 3시간 근거는 fmkorea 2시간 규칙 준수 + 정기 주기 (3시간 · 2026-07-25 에 6h → 3h 변경) 와의 정렬이다.
  정기 회차가 방금 커버한 시간대를 보충이 또 건드리는 중복 · 잦은 접촉의 430 위험을 막는다.
- 정기 주기는 VM systemd 타이머 `OnCalendar=*-*-* 00/3:00:00 UTC` 로, KST 기준 하루 8회 (00 · 03 · 06 · 09 · 12 · 15 · 18 · 21) 다.
  타이머 변경은 이 트랙 · 코드와 독립이며, 가드 값은 이 주기에 맞춰 정렬한다.
- 보충 수집 진입점은 신규 스크립트다 (현 `run.py` 는 수집 · 번역 · 렌더 · 알림 전 과정을 돌려 격리 불가).
  스크립트는 `FmkoreaAdapter` 를 직접 인스턴스화해 `.fetch()` 만 하고, `to_articles` (`pipeline.py`) · `MartStore.upsert` 로 적재한다.
- 보충 수집은 적재까지만 하고 번역 · 렌더는 하지 않는다.
  번역 · 렌더는 다음 VM 정기 회차가 흡수하므로, 번역 전 상태 (영문 제목 · 빈 본문) 가 라이브에 노출되지 않는다
  (행 추가 백필의 수렴 패스 규칙: `docs/runbook/2026-07-24-vm-live-reprocess-deploy.md` §5.1).

## 5. 파트 2 — 온스테인 X 직접 수집

### 5.1 config 신규 소스

- `config/sources.yaml` 에 `x_ornstein` 소스를 추가한다.
  `adapter: x_playwright` · `handle: David_Ornstein` · `cookies_path: x_cookies.json` 재사용.
- tier 는 고정 tier 1 로 준다.
  afcstuff 의 `x_mentions` 모드 (트윗 속 @핸들로 tier 판정) 는 본인 트윗에 @David_Ornstein 이 없어 판정 불가이므로 쓰지 않는다.

### 5.2 어댑터 파싱 분기 — 본인 트윗 수집

- `x_playwright.py` 의 `parse_afcstuff_tweets` 는 인용 (`[ @handle ]`) 이 없는 트윗을 버린다.
  온스테인은 남을 인용하지 않고 본인이 정보를 트윗하므로, 이 필터로는 한 건도 안 들어온다.
- config 플래그 (예: `self_source: true`) 로 별도 파싱 경로를 탄다.
  본인 트윗은 인용이 없어도 RawItem 으로 만들고, `journalist` 는 config 의 handle 로 고정한다.
  단 아스날 관련성 필터 (§5.4) 를 통과한 트윗만 남긴다.
- afcstuff 의 "인용만" 경로는 건드리지 않는다 (수술적 변경 · 기존 소스 회귀 방지).

### 5.4 아스날 관련성 필터

- 온스테인은 축구 전반 기자라 트윗 다수가 아스날 무관 (첼시 · 맨유 · 대표팀 등) 이다.
  기존 소스는 소스 자체가 아스날 전용 (afcstuff · fmkorea 검색어 · guardian tag 등) 이라 관련성 필터가 없었고, 온스테인이 첫 범용 소스라 필터가 필수다.
- **온스테인의 클럽 해시태그 관행을 이용한다** — 아스날 트윗에는 `#AFC` 를 단다 (사용자 실측 2026-07-25).
  본인 트윗 파싱 경로에서 텍스트에 `#AFC` 가 있는 것만 수집하고 나머지는 드롭한다.
- 본문 키워드 (Arsenal · Gunners) 매칭보다 정밀하다 — 온스테인 본인이 클럽을 태깅하므로 오탐 · 누락이 적다.
- 라이브 표본으로 확정할 것 (PR 2 착수 시):
  · `#AFC` 중의성 (AFC Bournemouth · Ajax 등 타 클럽) — 온스테인이 타 AFC 를 어떻게 태깅하는지 (예: `#AFCB`) 표본으로 확인.
  · 태깅 일관성 — 아스날 트윗에 항상 `#AFC` 를 다는지. 누락이 크면 Arsenal 본문 키워드 OR 조건으로 보강.
- LLM 관련성 판별은 채택하지 않는다 (전 소스 공통 B3 트랙 몫 · 온스테인 하나로 앞당기지 않음 · Gemini 비용).

### 5.3 페이월 · backtrack

- 온스테인 트윗이 The Athletic 링크를 담아도, `is_paywalled` (`x_backtrack.py`) 가 원문 승격을 차단한다.
  결과적으로 트윗 텍스트 (요약) 만 저장되며, 이는 "속보 요약" 이라는 역할과 정확히 맞는다.

## 6. 파트 3 — fmkorea 소급 백필 (검색 페이징)

- 현 `search_url` 에는 페이지 번호 자리표시자가 없다 (`_discover` 가 1페이지만 읽음).
  소급하려면 URL 템플릿에 `page=` 를 추가하고, `_discover` 루프가 페이지를 넘기게 확장한다.
- `backfill_journalist.py` 골격을 재사용한다
  — `REQUEST_GAP_SEC = 1.5` 간격 · `--dry-run` / apply · `--limit` · 멱등 UPDATE.
  단 `backfill_journalist` 자체는 fmkorea 를 명시적으로 배제하므로 (adapter 조건), 별도 스크립트로 짓는다.
- 백필도 맥 릴레이 프록시를 탄다 (fmkorea 접촉이므로).
  페이지 간 간격 · 총 접촉량을 라이브 검증 계획에 명시한다 (§10).
- fmkorea 는 포럼 검색이라 리스트 롤오프가 없어 차단 기간 글도 페이징으로 복원 가능하다.

## 7. dedup · 서빙 묶음

- `content_hash` 는 정규화 제목 + `canonical_url` 로 계산한다 (`canonical.py`).
  `content_hash` · `url` 이 UNIQUE 라, 완전히 같은 URL · 제목만 DB 층에서 중복 제거된다.
- `pipeline.py` 는 같은 원문 URL 에서 fmkorea 를 후순위로 강등해, EN · X 가 first-seen 이 되게 한다.
- The Athletic 은 페이월이라 온스테인 X 는 트윗 URL · fmkorea 는 원문 기사 URL 을 쓴다.
  두 URL 이 달라 DB 행은 2개로 남지만, 서빙 계층 `cluster_events` (`serve/render.py`) 가 선수 인명 기준으로 묶어 화면엔 한 묶음으로 나온다.
  대표 선정은 공식 > tier > 최신 순이라, 권위 높은 소스가 대표가 된다.

## 8. 실패 · 강등

- 터널 끊김 · 맥 꺼짐 → fmkorea 만 키워드 스킵 (기존 강등) · 다른 소스 무영향.
- 온스테인 X 접촉 실패 → 그 소스만 스킵 (X 어댑터 기존 degrade).
- 보충 수집 · 백필 실패 → 로깅 후 다음 기회에 재시도 (fmkorea 는 소급 가능하므로 소실 없음).

## 9. 테스트 전략 (TDD)

- **proxy 주입** — `FmkoreaAdapter` 가 `proxy` 를 받아 `AsyncClient` 에 전달하는지 단위 테스트 (httpx 모킹).
  `proxy` 미지정 시 현행 동작 유지 회귀 테스트.
- **온스테인 파싱 분기** — `self_source` 경로가 인용 없는 트윗을 RawItem 으로 만들고 `journalist` 를 고정하는지.
  afcstuff "인용만" 경로가 불변인지 회귀 테스트.
- **고정 tier** — `x_ornstein` 이 tier 1 로 산출되는지 (`resolve_tier`).
- **검색 페이징** — `page=` 확장이 여러 페이지를 순회하고 `max_posts` cap · 간격을 지키는지 (fetch 모킹).
- 셀렉터 · 검색 구조 · 페이월 분기는 모킹이 못 잡으므로 머지 전 단독 `fetch()` 라이브 검증을 병행한다 (§10).

## 10. 접촉 예산 · 라이브 검증

- fmkorea 는 직전 접촉 후 2시간 대기 규칙을 지킨다 (주거 IP 기준 유효).
  라이브 검증은 프록시 경유 단독 `fetch()` 1회 · 백필 페이징은 `REQUEST_GAP_SEC` 준수 · 총 페이지 수를 사전 명시한다.
- 온스테인 X 는 쿠키 소모를 최소화한다 (afcstuff 와 쿠키 공유).
- proxy 경유 검증은 맥이 켜진 상태에서 VM 이 실제로 터널을 타는지 확인한다
  (로컬 직접 접속으로 갈음하지 않는다 · 발신 IP 가 다름).

## 11. 롤백

- fmkorea proxy — VM `.env` 에서 `FMKOREA_PROXY` 제거 (직접 접속 복귀 · 현행 강등으로 degrade).
  보충 수집까지 끄려면 `enabled: false` — 보충 스크립트도 이 플래그를 존중한다.
- 온스테인 X — `x_ornstein.enabled: false`.
- 터널 · launchd — 맥에서 launchd 언로드.
- DB 스키마 변경이 없어 마이그레이션 롤백은 불필요하다.

## 12. 구현 순서 (사용자 확정)

- 하나의 spec · 3 PR 분리.
- 순서 1 → 3 → 2.
  1. fmkorea 1-B 정기 복구 (터널 · proxy · 보충 수집) — 앞으로의 누락을 먼저 막음.
  2. 온스테인 X 직접 수집 — 속보 · 최신성 확보.
  3. fmkorea 소급 백필 — 과거 누락 복원 (마지막).

## 13. 미해결 · 리스크

- **터널 안정성** — 홈 네트워크 유동 IP · 공유기 재부팅은 autossh 재접속이 흡수하나 드물게 손이 갈 수 있다.
- **온스테인 트윗 형태 다양성** — 스레드 · 리트윗 · 인용 혼재 시 본인 트윗 판별 규칙을 라이브 표본으로 확정해야 한다.
- **`#AFC` 관련성 필터 정확도** — 해시태그 중의성 (타 AFC 클럽) · 태깅 일관성 (누락) 을 라이브 표본으로 검증하고, 누락이 크면 본문 키워드로 보강한다 (§5.4).
- **페이징 소급 깊이** — 몇 페이지까지 거슬러 복원할지는 백필 착수 시 누락 실측으로 정한다.
- **cluster 대표 역전** — 온스테인 X (요약) 가 fmkorea (전문) 보다 대표로 뽑히면 상세가 요약만 보일 수 있다.
  대표 선정 로직 (공식 > tier > 최신) 실측으로 확인 후 필요 시 조정.

## 14. 참고

- 진단 SoT: `docs/troubleshooting/2026-07-24-fmkorea-vm-ip-persistent-430.md`
- fmkorea 어댑터 운영: `docs/runbook/2026-07-13-fmkorea-search-adapter-ops.md`
- 백필성 변경 VM 반영 · 수렴 패스: `docs/runbook/2026-07-24-vm-live-reprocess-deploy.md`
- 커버리지 감사: `docs/runbook/2026-07-24-source-coverage-audit.md`
