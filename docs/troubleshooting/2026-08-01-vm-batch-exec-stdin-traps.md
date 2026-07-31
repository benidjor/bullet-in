# VM 원격 일괄 실행이 중간에 끊기는 함정 2건 (2026-08-01)

후보 확정 운영 (2026-07-31 ~ 08-01) 에서 확정 CLI 48건을 `ssh 'bash -s' < 스크립트` 형태로 일괄 실행하다, 두 번 연속으로 스크립트가 전부 또는 중간부터 실행되지 않았다.
둘 다 원격 비대화형 셸의 표준입력 · 환경이 로컬 터미널과 다르다는 데서 왔다.
증상만 보면 확정 CLI 버그로 오인하기 쉬워 판별법과 재사용 템플릿을 함께 남긴다.

## 1. `docker exec -i` 가 남은 스크립트를 삼킨다

### 1.1. 증상

스크립트 앞쪽의 `docker exec -i ... mariadb -e "..."` 한 줄만 실행되고, 그 뒤의 확정 CLI 9건은 `echo` 한 줄 없이 한 건도 실행되지 않았다.
에러 메시지도 없어서 겉보기에는 빨리 끝난 성공으로 보인다.

### 1.2. 원인

`bash -s` 는 스크립트 본문을 표준입력으로 읽으면서 실행한다.
스크립트 중간의 `docker exec -i` 는 그 표준입력을 컨테이너에 이어 붙이므로, 아직 실행 안 된 나머지 줄이 통째로 mariadb 클라이언트의 입력으로 넘어간다.
bash 는 읽을 입력이 사라져 스크립트가 거기서 끝난다.

### 1.3. 부작용 점검 — 삼켜진 줄이 SQL 로 해석됐는가

mariadb 가 삼킨 나머지 줄을 SQL 문장으로 해석할 수도 있다.
이번 건은 남은 줄이 전부 셸 문법 (`run() {` · `uv run ...`) 이라 유효한 SQL 이 없었고 부작용 0 을 확인했다.
같은 사고가 나면 삼켜진 구간에 `UPDATE` · `DELETE` 로 시작하는 줄이 있었는지부터 확인하고, 있었다면 대상 테이블을 검증한다.

### 1.4. 대응

- 스크립트 안의 `docker exec` 에서 `-i` 를 뺀다.
  일회성 `-e` 실행에는 stdin 을 붙일 이유가 없다.
- 표준입력을 읽을 수 있는 모든 외부 명령 (docker · python · CLI) 에 `< /dev/null` 가드를 붙인다.

## 2. 비대화형 셸에는 uv 가 PATH 에 없다

### 2.1. 증상

배치 전 건이 `uv: command not found` 로 실패했다.
같은 명령을 SSH 대화형 접속에서 치면 정상 동작하므로, 대화형 검증만 거친 스크립트에서 처음 드러난다.

### 2.2. 원인 · 대응

`ssh host 'bash -s'` 는 프로필 (`~/.bashrc` 등) 을 소싱하지 않는 비대화형 셸이다.
uv 가 있는 `~/.local/bin` 이 PATH 에 없으므로, 스크립트 첫 줄에서 직접 넣는다.

## 3. 재사용 템플릿

두 함정의 가드를 모두 넣은 배치 스크립트 골격이다.
로컬에서 파일로 만들어 `ssh -i <키> <호스트> 'bash -s' < 스크립트 | tee 로그` 로 실행한다.

```bash
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
cd ~/bullet-in
set -a; source .env; set +a
run() {
  echo "=== CONFIRM $1 -> $2 ==="
  uv run python -m bullet_in.confirm_player --name "$1" --ko "$2" "${@:3}" < /dev/null || echo "FAILED: $1"
}
docker exec bullet-in-mariadb-1 mariadb -uroot -pbulletin bulletin -e "..." < /dev/null
run "Full Name" "표기" --category squad --transfer-status none
```

## 4. 참고

- 같은 계열 함정 (여러 줄 heredoc 붙여넣기가 EOF 를 못 만나 멈춤): `docs/runbook/2026-07-31-player-roster-ops.md` §2.3
- 일괄 확정의 전체 실행 형태: 같은 런북 §3.5
