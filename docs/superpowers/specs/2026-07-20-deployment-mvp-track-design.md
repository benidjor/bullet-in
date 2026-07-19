# 배포 서비스화 MVP 트랙 설계 — 결정 축 확정 · sub-project 분해 (2026-07-20)

이 프로젝트의 최종 목표를 "본인만 보는 수동 운영" 에서 "외부에 공개된 배포 서비스" 로 끌어올리는 트랙 (백로그 §5) 의 결정 스펙.
결정 축 5개를 옵션 비교로 확정하고, 구현을 sub-project 3개 (SP-B · SP-C · SP-D) 로 나눈다.
인프라 · 배포 방식은 선행 프로젝트 seoulnow (Oracle Free VM · Cloudflare Pages 운영 전례) 에서 검증된 것을 가져다 쓴다.

## 1. 목표 · 비목표

### 1.1. 목표 — MVP 정의

- MVP = "방문자가 URL 을 열면 사람 손 없이 최신 유지되는 아스날 이적 뉴스 한국어 사이트".
- 범위 = 결정 축 ①~④.
  - ① 스케줄 상시 가동 — 수동 회차 실행 대체.
  - ② 인프라 — site 호스팅 + 파이프라인 · MongoDB · MariaDB 상시 환경 · 비용.
  - ③ 배포 전 게이트 — 잔여 페이지 정리 (필수) · X 버너 리스크 (결정) · Gemini 비용 재확인.
  - ④ 본문 전문 서빙 저작권 — 서빙 범위 결정 + 조정 구현.
- 완료 정의: 외부 네트워크에서 URL 접속 시 최신 회차가 반영돼 있고, 갱신에 사람 개입이 없다.

### 1.2. 비목표

- 이벤트 로그 (결정 축 ⑤) — 목적이 "방문자 분석 대비" 로 유력해진 상태로 MVP 이후 1순위 이월.
- 워치리스트 · SP2 고도화 (재측정 사전 점검 제외) · 전담 부재 소스 +0.5 · corroboration · 관찰 대기 항목.
- 무인 운영 안전망 신규 구축 — 번역 게이트 4축 · SLO-5/6/7 알림 · 모니터링 뷰는 이미 완료돼 있어 MVP 에서 새로 만들 것이 없음.
- 완전 무인의 명시적 예외: X 쿠키 수동 재추출 (수 주 ~ 수 개월 주기) 는 유일하게 남는 수동 유지보수 항목.

## 2. 확정 결정

### 2.1. 축 ② 인프라 — seoulnow VM 동거 + Cloudflare Pages (월 0원)

- 채택: 기존 seoulnow Oracle Cloud Free VM (ARM 24GB) 한 대에 bullet-in 을 함께 올려 운영 (이하 "동거").
  - bullet-in 자체 docker compose (mongo + mariadb, 상시 약 1GB) 를 seoulnow compose 와 별개로 기동.
  - 회차 (하루 4회) 순간에만 파이프라인 프로세스 (chromium 포함 피크 약 1.5GB) 가 존재.
  - Tunnel · API 노출 계층은 두지 않음 — bullet-in 은 완전 정적 서빙이라 불필요.
- site 호스팅: Cloudflare Pages.
  - 회차 끝에 `site/` 를 wrangler + API 토큰으로 자동 배포 — seoulnow 에서 수동 영역으로 남긴 지점을 자동화로 개선.
- 선행 조건: 동거 착수 전 VM 메모리 실측 (free -h · docker stats).
→ 여유가 없으면 3-a (신규 유료 소형 VM 2GB, 월 약 1.1만원) 로 전환 — 구성은 그대로고 어느 호스트에 올릴지만 바뀜.
- seoulnow 차용 요소: `deploy-vm.yml` (main push 시 Actions 가 SSH 배포) · `deploy.sh` (git pull --ff-only + compose 기동 + 재시작, 멱등) · systemd 유닛 + `install-units.sh` 패턴 · Cloudflare Pages 계정 · wrangler 경험.
- 검토 후 제외한 옵션.
  - 로컬 맥 + 무료 정적 호스팅: 재작업 최소 · X 리스크 최저 (가정 IP) 지만 맥 상시 가동 의존이 남아 "완전 무인" 미달.
  - GitHub Actions cron + 무료 관리형 DB: 0원 완전 무인이지만 X 버너 차단 리스크 최대 (매회 변동 DC IP) + MariaDB 이전 재작업 + 무료 티어 정책 변동 의존.
- 잔여 리스크: 두 프로젝트가 장애 반경 공유 (한쪽 메모리 폭주가 다른 쪽을 OOM-kill 가능) · Oracle 무료 정책 변동.
→ 후자는 3-a 와 동일 경로로 이주 가능.

### 2.2. 축 ① 스케줄 — systemd timer + `run.py` 직접 실행

- 채택: oneshot service (`uv run python -m bullet_in.run`) + timer 하루 4회 · `Persistent=true` (재부팅 놓침 보정).
  - 실패 알림은 systemd `OnFailure=` 훅에서 기존 `notify.send_alert` (Discord webhook) 재사용.
  - 재시도 정책은 기존 철학 유지 — per-row 백오프 없이 다음 회차의 멱등 누적이 재시도를 대신함.
- 검토 후 제외한 옵션.
  - seoulnow Airflow 에 DAG 등재: seoulnow `deploy.sh` 가 Airflow 를 상시 서비스에서 제외하고 Spark 회차 때 scheduler 를 내리는 운영 이력 — 상시 보장이 없는 스케줄러라 전제 불성립.
    현 DAG 가 PythonOperator (bullet_in 직접 import) 라 의존성 충돌 위험도 겹침.
  - 자체 Airflow standalone: 하루 4회 회차를 위해 상시 약 1GB 지불 — 동거 채택 사유 (메모리 절약) 와 역행.
- `airflow/dags/bullet_in_daily.py` 는 로컬 · 향후 확장용 자산으로 보존 (운영 경로에서만 제외).

### 2.3. 축 ④ 저작권 — 소스별 차등 서빙

번역 전문은 2차적저작물이라 출처 표기 · 링크 · 비영리로도 공개 게시가 면책되지 않는 반면, 사실 자체와 자기 표현의 요약은 리스크가 낮다는 일반론에 근거한다.
소스 성질에 비례해 서빙 범위를 차등한다.

| 소스군 | 서빙 범위 | 근거 |
|---|---|---|
| 언론사 기사 (bbc_sport · bbc_gossip · skysports · guardian · goal · football_london) | 3줄 요약 + 짧은 발췌 (첫 1~2문단, 약 300자) + 원문 링크 | 전문 번역은 침해 소지 · 발췌는 인용 논리 |
| X 트윗 (x_afcstuff) | 전문 유지 | 원문 자체가 수십 단어 = 인용 수준 |
| fmkorea | 기존 정책 유지 (퍼가기 금지 = 헤드라인-온리, PR #85) | 정책 연장 |
| arsenal_official | 전문 유지 | 구단 공식 발표문 — 자사 홍보 목적의 보도자료 성격으로 리스크 최저 |

- README "메타데이터 · 요약 · 원문 링크 중심" 원칙과 실서비스가 일치하게 됨 — 과잉 적용 지점 (트윗) 만 합리적 예외.
- 검토 후 제외: 전문 유지 (리스크가 명백하고 README 원칙과 모순) · 전 소스 요약 축소 (리스크가 낮은 트윗까지 줄이는 과잉 축소 + Tier 2-a 에서 만든 본문 UX 의 전면 후퇴).
- 발췌도 "정당한 범위" 해석에 기대므로 리스크 제로는 아님을 기록해 둔다.

### 2.4. 축 ③ X 버너 — 유지 + 차단 시 비활성 폴백

- 채택: x_afcstuff 를 VM 회차에 포함해 계속 수집.
  - 동거로 접촉 IP 가 가정 IP → 고정 DC IP 로 바뀌어 차단 확률은 상승 — 감지는 SLO-5 신선도 워터마크 (X 24h) 가 담당.
  - 차단 · 쿠키 만료가 감지되면 `config/sources.yaml` 에서 x_afcstuff 를 끔 — 최악의 경우에도 MVP 는 성립한다는 기존 합의를 문서로 못박음.
- 검토 후 제외: 공개 시점 선제 비활성 (문제가 실제로 생기기도 전에 콘텐츠 11% 와 ITK 차별점을 포기) · X 회차만 로컬 맥에서 분리 실행 (맥 의존을 다시 들여오고 원격 DB 연결이 새로 필요해 MVP 의 단순함과 어긋남).

### 2.5. 축 ③ Gemini 비용 — 무료 티어 유지 (결제 불필요)

- 실측 (2026-07-20): mart 205건 · 일평균 신규 19건 · 평균 원문 2.8천자.
- 건당 호출 2~3회 (번역 + 3줄 요약 + 게이트) 로도 일 40~60 요청 — 무료 티어 일 총량 한도 내.
- 분당 속도 (15 RPM) 제약은 기존 설계 (429 식별 시 회차 중단 · 하루 4회 멱등 누적) 가 그대로 흡수.
- VM 이전으로 달라지는 조건 없음.

### 2.6. 축 ③ 잔여 페이지 — `write_site` 에 자동 정리 내장

- 실측: `site/article/` 페이지 파일 379개 vs DB 205행 — 재수집 (revision) · 행 삭제로 DB 에서 빠졌는데 파일만 남은 페이지가 174건 (구표기 힌카피에 16건 포함).
- 채택: 사이트를 다시 만들 때마다 `write_site` 가 `site/article/*.html` 을 DB 의 content_hash 목록과 대조해, DB 에 없는 기사의 파일을 자동 삭제.
  - 오삭제 방어: DB 조회 결과가 비정상적으로 적으면 (예: 0건) 삭제를 건너뛰고 WARNING 만 남김 — 조회 실패 시 전체 페이지를 지워버리는 사고 방지.
  - 이미 쌓여 있는 174건도 첫 실행에서 함께 삭제됨 — 별도 수동 작업 없음.
- 검토 후 제외: 일회성 수동 삭제 (재수집이 일어날 때마다 다시 쌓여 수동 운영이 남음) · 방치 (정정 전 오류 페이지가 검색엔진에 노출될 수 있음).
- 404 대가: 현재 공유된 링크가 없고, DB 에서 빠진 페이지는 정정 전 오류가 남은 경로라 404 가 올바른 상태.

## 3. Sub-project 분해

```
SP-A 결정 스펙 (본 문서) ──┬──> SP-C 스케줄 상시 가동 (VM 동거 셋업) ──> SP-D 공개 전환
                           └──> SP-B 배포 게이트 (병렬 — 본 spec 승인 즉시 착수 가능)
```

- SP-B 는 인프라 · 스케줄과 의존이 없어 main 기준 로컬에서 병렬 구현 가능.
- SP-C · SP-D 는 순차 — 각각 별도 plan (필요시 spec 보강) 으로 진행.

### 3.1. SP-B 배포 게이트 (병렬)

- 범위 ⑴ `write_site` 잔여 페이지 자동 정리 — §2.6 설계.
- 범위 ⑵ 차등 서빙 구현 — §2.3 매핑.
  - 소스군 → 서빙 모드 매핑은 코드가 아닌 config 에 둠 (신규 소스 추가 시 모드 지정을 빠뜨려도 기본값으로 방어).
  - detail 템플릿 분기: 발췌 모드는 첫 1~2문단 약 300자 + "전문은 원문 기사에서" 안내 + 원문 링크 강조.
  - 기존 페이지는 재렌더로 일괄 반영.

### 3.2. SP-C 스케줄 상시 가동

- 순서: VM 메모리 실측 (선행 조건) → bullet-in compose 동거 셋업 (포트 · 디스크 확인 포함) → systemd 유닛 (service + timer + OnFailure 알림) 등록 → 하루 4회 가동 + 회차 끝 site 산출 확인.
- 셋업 절차는 seoulnow 런북 · `deploy.sh` 패턴을 참조해 bullet-in 용 부트스트랩 런북으로 작성.

### 3.3. SP-D 공개 전환

- Cloudflare Pages 프로젝트 생성 + 회차 끝 wrangler 자동 배포 연결.
- README 정비 — 서빙 원칙과 실서비스 일치 확인 · 공개 저장소 규칙 (Claude 서명 · 포트폴리오 프레이밍 · 회사 실명 금지) 준수 점검.
- 배포 전 게이트 체크리스트 실행: 잔여 페이지 정리 완료 (파일 수 = DB 행 수) · 차등 서빙 검증 · SLO 알림 동작 · X 폴백 절차 문서화.
- 공개 (URL 확정).

## 4. 검증 · 성공 기준

- SP-B: 정리 후 `site/article/` 파일 수 = DB 행 수 (379 → 205) · 구표기 (힌카피에) 페이지 16건이 사라짐 · 오삭제 방어 테스트 (DB 0건 시나리오에서 삭제 0건).
  차등 서빙은 소스군별 상세 페이지 스냅샷으로 검증 (언론사 페이지에 body 블록 부재 · 트윗 페이지에 존재).
- SP-C: 맥을 꺼둔 상태에서 VM 이 4회차 연속 자동 완주 + 실패 알림 경로 (OnFailure → Discord) 동작 확인.
  seoulnow 프로세스 무영향 (메모리 실측 전후 비교) 확인.
- SP-D: 외부 네트워크에서 URL 접속 → 최신 회차 반영 확인 — 이것이 곧 MVP 완료 정의 (§1.1).

## 5. 리스크 · 폴백

- VM 메모리 여유가 없음 → 3-a (유료 VM) 로 전환 — 호스트 선택만 바뀌고 작업 내용은 같음.
- X 버너 차단 → SLO-5 감지 + x_afcstuff 비활성 — MVP 성립 유지.
- Oracle 무료 정책 변동 · 계정 회수 → 3-a 와 동일 경로로 이주.
- 자동 정리 오동작 → 오삭제 방어 로직으로 차단 + 정적 산출물이라 재렌더 · git 히스토리로 복구 가능.
- 동거로 인한 상호 영향 → bullet-in 쪽은 실패해도 사이트가 마지막 상태로 남을 뿐이라 심각도 낮음 · seoulnow 쪽 영향은 착수 전 메모리 실측으로 미리 줄임.

## 6. 참고

- 백로그 SoT: `docs/superpowers/2026-07-19-post-v1-followup-tracks.md` §5 — 배포 서비스화 트랙 항목.
- seoulnow 전례: https://github.com/benidjor/seoulnow — `infra/vm/deploy.sh` · `.github/workflows/deploy-vm.yml` · `infra/systemd/` · `infra/cloudflare/README.md`.
- X 어댑터 운영: `docs/runbook/2026-07-03-afcstuff-playwright-adapter-ops.md`.
- fmkorea 퍼가기 정책: PR #85 · 잔여 페이지 실측: 백로그 "DB 에서 빠진 기사의 잔여 페이지 정리" 항목.
- SP2 재측정 사전 점검 (본 세션 4회차 기록): `docs/troubleshooting/2026-07-19-sp2-promotion-diagnosis.md` §4.1.
