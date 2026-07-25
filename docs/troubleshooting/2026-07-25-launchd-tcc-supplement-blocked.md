# launchd 가 ~/Documents 안의 스크립트를 실행하지 못함 (macOS TCC · Operation not permitted)

fmkorea 맥 릴레이 (PR #130) 라이브 검증 중, launchd 보충 트리거가 저장소 안의 `supplement.sh` 를 실행하지 못한 사례다.
plist · 실행 권한 · 스크립트 문법이 전부 정상이어서 원인 소거에 시간이 걸릴 수 있는 유형이라 기록한다.
해결은 PR #131 로 반영됐다.

## 1. 증상

- 런북 §5 (보충 수집 1 회 검증) 에서 `com.bulletin.fmkorea-supplement` 를 load 했지만 수집이 실행되지 않음.
- `/tmp/fmkorea-supplement.err` 에 한 줄만 기록:
  `bash: /Users/aryijq/Documents/01_DE_project/bullet-in/infra/mac-fmkorea-relay/supplement.sh: Operation not permitted`
- `launchctl list` 의 해당 서비스 종료 코드가 126 (실행 불가).

## 2. 소거된 원인 (전부 정상이었던 것)

- plist 문법 — `plutil -lint` OK.
- 실행 비트 — 커밋된 100755 그대로 (`ls -la` 확인).
- 스크립트 문법 — `bash -n` 통과.
- 같은 스크립트를 터미널에서 직접 실행하면 정상 동작한다.
  터미널 (GUI 앱) 은 사용자가 부여한 Documents 접근 권한을 상속받기 때문이다.

## 3. 원인

- macOS TCC (Transparency, Consent, and Control) 가 `~/Documents` · `~/Desktop` · `~/Downloads` 를 보호 폴더로 관리한다.
- GUI 앱은 최초 접근 시 권한 팝업을 받지만, launchd 백그라운드 에이전트가 띄운 `bash` 는 팝업을 받을 수 없어 접근이 조용히 거부된다.
- 결과적으로 launchd 컨텍스트에서는 보호 폴더 안의 어떤 실행 파일도 열 수 없다.
  저장소가 `~/Documents` 아래에 있는 한, 저장소 경로의 스크립트를 plist 가 직접 가리키면 반드시 재현된다.

## 4. 해결 (PR #131)

- 실행 대상을 TCC 보호 밖 경로의 복사본으로 변경 — 설치 시 `supplement.sh` 를 `~/.bullet-in/` 로 복사하고, plist 의 `ProgramArguments` 가 그 복사본을 가리킨다.
- `bash` 에 Full Disk Access 를 부여하는 대안은 과도한 권한이라 기각했다.
- 같은 이유로 launchd 가 실행할 파일은 앞으로도 홈 루트 등 보호 밖 경로에 둔다.
  plist 자체는 `~/Library/LaunchAgents/` 에 있으므로 영향이 없다.

## 5. 재발 방지 · 운영 노트

- `supplement.sh` 를 수정하면 `~/.bullet-in/` 로 재복사해야 반영된다 (런북 §1 에 명시).
- 진단 순서 요령 — launchd 실행 실패에서 "Operation not permitted + 파일 자체는 정상" 조합이 보이면, 파일이 TCC 보호 폴더 안에 있는지부터 확인한다.

## 6. 참고

- 설치 · 검증 런북: `docs/runbook/2026-07-25-fmkorea-mac-relay-setup.md`
- 발단 트랙: PR #130 (fmkorea 맥 릴레이 복구) · 픽스: PR #131
