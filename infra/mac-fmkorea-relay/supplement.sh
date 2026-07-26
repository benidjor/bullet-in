#!/usr/bin/env bash
set -euo pipefail

# launchd 가 남기는 로그를 회차마다 점검해 커지면 최근 분량만 남긴다.
# 맥을 재부팅하지 않고 슬립으로만 쓰면 /tmp 가 비워지지 않아 연결 실패 기록이 계속 쌓인다.
# 파일을 지우거나 옮기면 launchd · autossh 가 이미 열어 둔 fd 로 계속 써서 새 파일이 비므로,
# 제자리에서 잘라내는 방식만 쓴다.
trim_log() {
  local f=$1 max_bytes=$2 keep_lines=200
  [ -f "$f" ] || return 0
  if [ "$(stat -f%z "$f")" -gt "$max_bytes" ]; then
    tail -n "$keep_lines" "$f" > "$f.trim" && cat "$f.trim" > "$f" && rm -f "$f.trim"
  fi
}
for log in /tmp/fmkorea-supplement.err /tmp/fmkorea-supplement.out /tmp/fmkorea-tunnel.err; do
  trim_log "$log" 262144   # 256KB — 실측 하루 약 20KB 이므로 2주에 한 번꼴로 절단
done

ssh -o BatchMode=yes -o ConnectTimeout=10 -i /Users/aryijq/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'bash -lc "cd /home/ubuntu/bullet-in && set -a && source .env && set +a && export FMKOREA_PROXY=socks5://127.0.0.1:1080 && uv run python -m bullet_in.collect_fmkorea"'
