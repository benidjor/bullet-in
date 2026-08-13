# 머지 전 화면 검증 — 운영 사본을 로컬에 렌더해 직접 본다 (2026-08-11)

서빙 표시 규칙을 바꿀 때 머지 · 배포 전에 실제 화면을 확인하는 절차다.
단계 재정의를 적용한 작업에서 이 절차로 **고치려던 수정이 오히려 만든 회귀 3건을 배포 전에 잡았다.**
테스트가 통과해도 화면이 틀릴 수 있는 변경 (배지 · 정렬 · 묶음 · 라벨) 에 쓴다.

## 1. 왜 필요한가

- 표시 규칙은 데이터 분포에 따라 결과가 갈린다.
단위 테스트는 만든 사람이 떠올린 조합만 확인하므로 운영 데이터에만 있는 조합은 테스트를 통과한 채로 화면에서 틀린다.
- 이번 실측이 그 예다.
"종결 단계를 현재 상태로 쓴다" 는 규칙은 테스트를 전부 통과했지만 운영 데이터에 적용해 보니 개선 6명과 함께 **회귀 3명**을 만들었다 (영입을 마친 선수가 무산으로 · 아직 이적하지 않은 선수 둘이 무산으로).
원인은 앞 단계에서 잘못 분류된 기사 한 건이 배지를 계속 좌우한 것이었다.
화면을 대조하지 않았다면 배포한 뒤에야 드러났을 문제다.
- **로컬 `bulletin` 으로는 선수 페이지를 못 만든다** — 그 DB 에는 `article_players` 가 비어 있어 오류 없이 0명이 나온다.
그래서 운영 사본이 필요하고 `articles` 만 복제해서도 안 된다.

## 2. 절차

### 2.1. 운영 데이터를 세션 전용 사본으로 복제

세 테이블을 함께 덤프한다 — 하나라도 빠지면 선수 페이지가 비거나 이름 · 배지가 어긋난다.

```bash
ssh <vm> 'cd ~/bullet-in && set -a && source .env && set +a && \
  docker exec bullet-in-mariadb-1 mariadb-dump -uroot -p<pw> \
  bulletin articles article_players players' > prod_full.sql

docker exec bullet-in-mariadb-1 mariadb -uroot -p<pw> \
  -e "DROP DATABASE IF EXISTS bulletin_<세션이름>; CREATE DATABASE bulletin_<세션이름> CHARACTER SET utf8mb4;"
docker exec -i bullet-in-mariadb-1 mariadb -uroot -p<pw> bulletin_<세션이름> < prod_full.sql
```

- 사본 이름은 **세션 전용**으로 짓는다 (동시에 진행 중인 다른 작업의 사본을 지우지 않기 위해).
- 운영 DB 를 직접 읽어도 되지만 배치가 돌아가는 중이면 중간 상태를 보게 된다.

### 2.2. 숫자로 먼저 대조 — 렌더보다 이 단계가 중요하다

화면을 열기 전에 **옛 규칙과 새 규칙을 전 대상에 적용해 계산하고 차이 목록을 뽑는다.**
바뀐 것이 몇 건이고 무엇인지 모르면, 화면을 봐도 무엇을 봐야 할지 모른다.

```python
# 새 코드로 엔트리를 만들고, 같은 입력에 옛 규칙을 손으로 계산해 나란히 찍는다
entries = R.build_player_entries(rows, R.load_page_players(engine))
for e in entries:
    old = <옛 규칙 계산>
    if old != e["stage"]:
        print(e["name"], e["transfer_status"], old, "→", e["stage"])
```

- 이번에는 이 표에서 회귀 3건이 바로 눈에 띄었다 — 좋아진 사례와 섞여 있어도 사람이 확정한 명단 값과 나란히 출력하면 모순이 보인다.
- **모순 건수를 0으로 만드는 것을 판정 기준으로 삼는다** (사람이 확정한 값과 화면 표시가 어긋나는 건수).

### 2.3. 렌더해서 사람이 직접 본다

```bash
MARIADB_URL=".../bulletin_<세션이름>" uv run python - <<'EOF'
# run.py 서빙 경로와 1:1 인 스니펫 — enrich 전용 런북 §4 를 그대로 쓴다
# (fmkorea 무관 글 필터 포함 · SERVING_SELECT_SQL import)
write_site(rows, ..., "site_new", ...)
EOF

cd site_new && python3 -m http.server 8899 --bind 127.0.0.1
```

- 상대 경로 · CSS · JS 가 그대로 동작하므로 브라우저에서 라이브와 같은 화면을 본다.
- 라이브를 함께 열어 두면 전후 비교가 된다 — 로컬은 새 코드 · 라이브는 현재 코드다.
- 검토가 끝나면 서버를 내린다.

### 2.4 두 산출물을 파일 단위로 비교하면 전건이 바뀐 것으로 나온다

전후 두 벌을 렌더해 놓고 어느 페이지가 바뀌었는지 세면 **거의 모든 파일이 걸린다.**
사이드바의 단계 필터 계수가 모든 페이지에 박혀 있어서, 기사 한 건의 단계만 바뀌어도 그 숫자가 전 페이지에서 함께 달라지기 때문이다.

2026-08-13 실측이 그랬다 — 실제로 달라진 곳은 5개 파일인데 비교는 **678건 전부 변경**으로 나왔다.
필터 계수 블록을 지우고 비교하니 5건이 남았다.

```python
import pathlib, re
base, new = pathlib.Path("site_base"), pathlib.Path("site_new")
strip = lambda s: re.sub(r'<label class="opt">.*?</label>', '', s, flags=re.S)
diff = [str(f.relative_to(new)) for f in sorted(new.rglob("*.html"))
        if strip((base / f.relative_to(new)).read_text(encoding="utf-8"))
        != strip(f.read_text(encoding="utf-8"))]
print(len(diff), diff)
```

- **지운 계수는 따로 센다** — 그 숫자도 확인 대상이다 (2026-08-13 에는 오피셜 7 → 8 · 이적 완료 39 → 38 로 합이 보존되는 것이 판정 근거였다).
- 렌더 시각 같은 것을 지우려 들면 안 된다 — 이 산출물에는 매번 달라지는 값이 없다.
전건 변경의 원인은 노이즈가 아니라 **실제로 전 페이지에 들어 있는 값**이다.

## 3. 배포 후 확인의 함정 — CDN 캐시

배포 직후 라이브 주소로 페이지를 요청하면 **옛 페이지가 온다.**
2026-08-11 에 실제로 "반영이 안 됐다" 고 오진할 뻔했다 — VM 의 `site/` 산출물에는 이미 새 내용이 있었고 라이브 주소만 예전 캐시를 돌려주고 있었다.

```bash
curl -sL https://<배포id>.bullet-in.pages.dev/player/<slug>.html   # 배포별 주소는 즉시 새 것
ssh <vm> 'grep -c "<찾는 문자열>" ~/bullet-in/site/player/<slug>.html'   # 산출물 직접 확인
```

- 배포 스크립트가 마지막에 출력하는 `https://<배포id>.bullet-in.pages.dev` 주소를 쓰면 캐시를 우회한다.
- 라이브 도메인은 잠시 뒤 따라온다.

### 3.1 세는 함정 — 라벨 텍스트로 세면 다른 자리가 함께 걸린다

위 `grep -c` 의 「찾는 문자열」 에 **화면 라벨을 그대로 넣으면 안 된다.**
같은 라벨을 쓰는 자리가 한 페이지에 여럿이라 관계없는 것까지 세어진다.

실물이 2026-08-13 에 있었다.
사다리 종결 줄 가드 (#267) 가 걸렸는지 보려고 「무산」 으로 셌더니 **18개 페이지**가 나왔고, 실제 종결 줄은 6개였다.
사다리 종결 줄과 **기사 카드 배지**가 같은 라벨을 쓰기 때문이다.

```bash
ssh <vm> 'grep -l "tlend" ~/bullet-in/site/player/*.html | wc -l'   # 종결 줄만
ssh <vm> 'grep -l "무산" ~/bullet-in/site/player/*.html | wc -l'    # 카드 배지까지 (오진 유발)
```

- **카드 배지가 함께 안 가려지는 것은 회귀가 아니라 설계다.**
카드 배지는 「이 기사가 그 선수에 대해 무엇을 보도했나」 이고 머리 배지 · 종결 줄과 묻는 질문이 다르다 (근거는 `docs/superpowers/specs/2026-08-13-player-display-rules-design.md` §3.1 의 기각 사유).
- 그래서 명단이 `in_link` 인 선수 페이지에 「무산」 카드가 남아 있을 수 있다.
- **세려는 것이 어느 자리인지 먼저 정하고 그 자리의 클래스로 센다** — 사다리 줄은 `tlnode` · 종결 줄은 `tlend` 다.

### 3.2 한글을 찾을 때 문자 클래스를 섞으면 개수 자체가 틀린다

앞 절은 **세는 자리**를 잘못 고르는 함정이고, 이것은 같은 자리를 세는데도 **숫자가 틀리는** 함정이다.

2026-08-13 에 한 페이지의 「구단 공식」 표기를 세는데 값이 두 번 갈렸다.

```bash
grep -o '공신력 [^<]*\|구단 공식' player/norgaard.html | sort | uniq -c   # 10 으로 나옴
grep -c -F '구단 공식' player/norgaard.html                                # 2 — 이쪽이 맞다
```

`[^<]` 같은 문자 클래스가 바이트 단위로 동작해 한글 한 글자의 중간을 끊는다.
그래서 매치 구간이 엉뚱하게 잡히고 계수가 부풀거나 0 이 된다.

- **고정 문자열로 센다** (`grep -c -F` · `grep -o -F`) — 정규식 기능이 필요 없으면 항상 이쪽이다.
- 조건이 붙어 정규식이 꼭 필요하면 **파이썬으로 센다** (`str.count` · `re` 모듈은 유니코드 단위로 동작한다).
- 같은 명령을 두 번 다르게 써서 값이 갈리면 **둘 다 의심한다** — 이번에는 먼저 나온 값이 틀린 쪽이었다.

## 4. 곁들여 — 기존 배치를 새 코드 없이 부분 실행하기

전체를 대상으로 도는 배치 모듈을 일부 대상에만 돌리고 싶을 때, **state 파일에 제외 대상을 미리 넣으면 된다.**
`filter_targets(rows, load_state(state))` 가 state 에 있는 항목을 빼기 때문이다.

```bash
# 대상 63건만 남기고 나머지 516건을 state 로 제외
grep -vxFf targets.txt all_linked.txt > state_subset.txt
uv run python -m bullet_in.<배치 모듈> --state state_subset.txt --dry-run   # 대상 수 확인
uv run python -m bullet_in.<배치 모듈> --state state_subset.txt
```

- 배치 코드를 고치지 않으므로 이미 검증된 경로를 그대로 실행한다.
- `--dry-run` 으로 대상 수를 먼저 확인한다 — 여기서 숫자가 틀리면 state 파일을 잘못 만든 것이다.

## 5. 참조

- 로컬 DB 로는 선수 페이지가 안 나오는 이유: 세션 메모리 `local-mart-cannot-render-player-pages`
- 재생성 스니펫 정본: `docs/runbook/2026-07-19-enrich-only-pass.md` §4
- 1회성 배치 절차: `docs/runbook/2026-08-08-onetime-db-batch-via-tunnel.md`
- 이번 회차의 실측: `docs/superpowers/specs/2026-08-10-article-stage-redefinition-design.md` §6.5
