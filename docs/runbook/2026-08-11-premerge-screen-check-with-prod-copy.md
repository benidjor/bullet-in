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
def strip(s):
    s = re.sub(r'<label class="opt">.*?</label>', '', s, flags=re.S)
    return re.sub(r"\s+", " ", s)      # 지운 자리에 남는 공백까지 눌러야 한다 (아래)
diff = [str(f.relative_to(new)) for f in sorted(new.rglob("*.html"))
        if strip((base / f.relative_to(new)).read_text(encoding="utf-8"))
        != strip(f.read_text(encoding="utf-8"))]
print(len(diff), diff)
```

- **지우고 나서 공백을 눌러야 한다** (2026-08-14 추가).
블록만 들어내면 항목 개수가 다른 만큼 **빈 줄 개수가 달라져** 그 차이로 파일이 걸린다.
지우는 대상이 이번처럼 개수가 바뀌는 목록 (기자 항목) 이면 특히 그렇다.
공저자 귀속 회차에서 실제 변경 61건이 이 공백만으로 **684건**으로 나왔고, 눌러 주니 61 이 됐다.
차이 목록을 열어 보면 남은 것이 빈 줄뿐이라 바로 갈린다.
- **지운 계수는 따로 센다** — 그 숫자도 확인 대상이다 (2026-08-13 에는 오피셜 7 → 8 · 이적 완료 39 → 38 로 합이 보존되는 것이 판정 근거였다).
- 렌더 시각 같은 것을 지우려 들면 안 된다 — 이 산출물에는 매번 달라지는 값이 없다.
전건 변경의 원인은 노이즈가 아니라 **실제로 전 페이지에 들어 있는 값**이다.
- **새 컬럼을 넣는 변경이면 두 벌이 아니라 세 벌을 렌더한다** — 배포 구간과 소급 구간을 갈라야 한다.
절차와 실패 사례는 `docs/troubleshooting/2026-08-14-transition-rule-does-not-cover-the-template.md` §4 에 있다.

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

### 3.3 페이지를 이름으로 집으면 남의 페이지가 걸린다

앞 두 절은 **무엇을 세는가**의 함정이고, 이것은 **어디를 세는가**의 함정이다.
2026-08-14 소급 확인에서 이렇게 세어 「소급이 화면에 안 실렸다」 는 결론을 냈는데, 도구를 고치자 **결과가 전부 뒤집혔다.**

**선수 페이지는 이름이 아니라 슬러그 파일명으로 집는다.**

```bash
grep -l -F '마르티넬리' site/player/*.html | head -1   # 부아디 페이지가 잡힌다
ls site/player/martinelli.html                          # 이쪽이 그 선수의 페이지다
```

선수 이름은 **남의 페이지에도 정상적으로 나온다** — 기사 제목 · 카드 · 사이드바에 함께 실리기 때문이다.
그래서 이름으로 거르면 언급된 페이지가 먼저 걸리고, `head -1` 을 붙이면 엉뚱한 페이지 하나를 골라 그 값을 답으로 쓴다.
같은 확인에서 뇌르고르 페이지를 보려다 기마랑이스 페이지를 봤다.

**본문에 무엇이 남았는지는 렌더된 HTML 이 아니라 저장된 `body_ko` 로 본다.**

기사 상세 페이지에는 그 기사의 본문 말고도 다른 기사 카드와 사이드바 필터가 함께 실린다.
소급으로 본문에서 걷어낸 문자열을 상세 페이지에서 세면 **다른 기사의 제목과 필터 UI 라벨이 걸려** 「안 지워졌다」 로 읽힌다.

- 실물 — 관련기사 소제목 「은와네리」 를 상세 페이지에서 세니 아래쪽 **다른 기사 카드 제목**이 걸렸고, 「더보기」 는 **아웃렛 필터의 UI 라벨** (「스카이스포츠 1 더보기」) 이 걸렸다.
- DB 에서 보면 한 줄로 끝난다 — `SELECT body_ko FROM articles WHERE content_hash LIKE '<해시>%'`.
- **화면에 실렸는지**를 볼 때만 HTML 을 보고, 그때도 기사 해시로 그 상세 파일 하나를 집는다.

**선수 페이지 수를 예측할 때 `role` 승격을 페이지 생성으로 읽지 않는다.**

`role` 이 `mention` 에서 `subject` 로 바뀌면 그 기사가 목록에 뜰 자격을 얻지만, **페이지가 생기는 것은 별개 조건**이다.
2026-08-14 에 마갈량이스가 `subject` 로 승격됐는데 귀속이 전부 선수축 `other` 라 페이지 자체가 없었고, 「그 페이지에 한 건이 붙는다」 는 예고가 빗나갔다.

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

## 5. 사본이 필요 없는 경우 — 배포 산출물 한 장으로 재기 (2026-08-20 추가)

**화면에 이미 나가 있는 것의 규모를 재는 일이라면 운영 사본도 터널도 필요 없다.**
VM 이 만든 `site/all.html` 한 장에 사이드바 계수와 카드 전량이 함께 들어 있다.

### 5.1. 언제 이 방법으로 충분한가

- **재려는 것이 배포된 화면의 현재 상태일 때** — 어긋난 건수 · 항목 종수 · 숨겨진 카드 수 등.
- **코드를 안 바꿨을 때** — 새 규칙의 결과를 보려면 사본에 렌더해야 하므로 §2 절차를 쓴다.

**사본이 필요한 경우와 갈리는 지점은 「지금 화면」 이냐 「바꾼 뒤 화면」 이냐다.**

### 5.2. 절차

```bash
# ① 산출물 한 장만 받는다 (회차 시각도 함께 확인)
ssh <vm> 'cd ~/bullet-in && git log --oneline -1 && ls -la site/all.html'
scp <vm>:'~/bullet-in/site/all.html' /tmp/<세션전용>/all.html
```

카드와 사이드바를 같은 파일에서 뽑아 대조한다.

```bash
# ② 카드 — data-* 속성이 필터 판정의 입력이다
grep -o 'data-outlet="[^"]*"' all.html | sort | uniq -c | sort -rn | head

# ③ 사이드바 계수
grep -o 'data-group="outlet" data-value="[^"]*"[^>]*>[^<]*<span class="ct">[0-9]*' all.html

# ④ 서버가 숨긴 카드 수 — 화면 규칙으로 센 값과 맞아야 측정을 믿을 수 있다
grep -c 'style="display:none"' all.html
```

### 5.3. 이 방법의 함정

- **`index.html` 로 재면 안 된다** — 사이드바 계수는 전체 기사인데 index 는 카드를 사건 블록 안에 접어 둔다.
접힌 카드도 필터 대상이라, 안 세면 그만큼이 「도달 불가」 로 잘못 잡힌다.
- **관련 기사 (`relitem`) 는 태그가 여러 줄에 걸쳐 있다** — 한 줄 `grep` 으로 세면 통째로 놓친다.
- **HTML 속성은 원자료가 아니다** — 대표 선정 · 별칭 접기 · 소스 폴백을 이미 거친 값이다.
저장값 기준 수치가 필요하면 DB 를 조회한다 (`2026-08-20-rendered-values-are-not-raw-data.md`).
- **VM 은 KST 로 돈다** — 산출물 파일 시각도 KST 다.
UTC 로 적힌 시각과 회차를 견줄 때는 +9 를 한다.

### 5.4. 저장값만 고쳤을 때의 반영 시점

`articles` 의 표시용 컬럼 (`outlet` 등) 만 고쳤다면 **배포가 필요 없다.**
다음 정기 회차가 렌더하면서 화면에 반영된다.

**확인은 절대값이 아니라 증감으로 한다** — 정정은 저장값에 하고 확인은 화면에서 하므로 층이 다르고, 저장값이 빈 행의 소스 폴백이 화면 계수에 함께 잡힌다.

## 6. 화면 규칙 자체를 브라우저에서 재기 (2026-08-20 추가)

§2 · §5 는 **산출물의 값**을 세는 절차다.
`app.js` 의 판정 규칙을 바꿨다면 그것만으로는 부족하다 — **그 규칙이 실제 브라우저에서 무엇을 보여 주는지**를 따로 봐야 한다.
표기 통일 회차에서 사이드바 항목 251개를 하나씩 눌러 확인했고, 그 과정에서 함정 둘을 밟았다.

### 6.1. 절차

렌더한 산출물을 로컬에 띄우고 항목을 하나씩 켜서 화면에 남는 카드를 센다.

```js
// 사이드바 항목을 하나씩 켜고 「적용」 을 눌러 화면에 남는 카드를 센다
const apply = document.getElementById('applyBtn');
const vis = () => [...document.querySelectorAll('a.item')]
  .filter(e => getComputedStyle(e).display !== 'none').length;
for (const b of document.querySelectorAll('input[data-group="outlet"]')) {
  const want = +b.closest('label').querySelector('.ct').textContent;
  b.checked = true; b.dispatchEvent(new Event('change', {bubbles: true}));
  apply.click();
  const got = vis();                       // 적힌 건수와 이 값을 대조한다
  b.checked = false; b.dispatchEvent(new Event('change', {bubbles: true}));
  apply.click();
}
```

### 6.2. 함정 ① — 체크만으로는 필터가 안 걸린다

**필터는 「적용」 버튼에서 걸린다.**
`change` 이벤트 처리기는 버튼에 `dirty` 표시만 하고, `applyFilters` 는 `applyBtn.onclick` 에 걸려 있다.

- 이것을 모르고 재면 **항목 전부가 같은 값 (필터 없는 화면의 카드 수) 으로 나온다.**
실물 — 251개 항목이 전부 701 로 나왔다.
- **값이 한 종류로 뭉치면 필터가 안 걸린 것을 의심한다.**
「어긋남 251종」 처럼 보이지 않고 「전부 같은 값」 으로 나타나므로 오독하기 쉽다.

### 6.3. 함정 ② — 항목에서 출발하는 검사는 반대 방향을 못 본다

「사이드바가 적은 건수 = 그 항목을 골랐을 때 나오는 건수」 는 **항목에서 출발하는 검사**다.
그래서 **「카드에는 있는데 사이드바에 항목이 없다」 를 구조적으로 못 본다** — 그 항목이 없으니 검사 목록에도 없다.

**양방향으로 센다.**

```bash
# ① 측정 도구부터 의심한다 — 원자료 태그 수와 내 계수가 같은가
grep -o 'data-group="outlet"' all.html | wc -l

# ② 두 방향을 모두 센다
#    카드의 고유 data-outlet 값  vs  사이드바 항목
#    → 카드에만 있는 것 0 · 항목에만 있는 것 0 이어야 한다
```

- 이 대조가 있어야 **「화면에 빈 자리가 없다」 를 단정**할 수 있다.
- 실물 — 다른 세션이 잰 49종과 우리 48종이 갈렸을 때, 이 대조로 우리 층이 깨끗한 것을 보이고 원인을 상대 도구 (`outlet_display` 의 `directory` 인자 누락) 로 좁혔다.
- 없어진 것을 세려면 없어지기 전 목록이 필요하다는 것과 같은 뿌리다 (`2026-08-14-a-tradeoff-weighed-one-loss-but-there-were-five.md`).

### 6.4. 함수를 손으로 불러 화면을 예측할 때

렌더를 돌리지 않고 저장값에 서빙 함수를 직접 적용해 델타를 예고할 수 있다.
그때는 **인자 목록을 호출부와 1:1 로 맞춘다** — 정본은 `run.py` 의 `write_site(...)` 다.

- `outlet_display` 는 `directory` (인용 기자 소속 접기) 와 `outlet_dir` (표기 · 조직 계정 접기) 를 **둘 다** 받는다.
하나만 빠져도 화면에 없는 표시명이 생긴다.
- **그 오차는 델타에서 상쇄돼 안 드러난다** — 전후를 같은 틀린 도구로 재기 때문이다.
그래서 **절대값을 한 번은 배포 산출물과 맞춰 본다.**
- 경위와 처방: `docs/troubleshooting/2026-08-14-suspect-the-yardstick-not-the-data.md` §2.3.

## 7. 참조

- 로컬 DB 로는 선수 페이지가 안 나오는 이유: 세션 메모리 `local-mart-cannot-render-player-pages`
- 재생성 스니펫 정본: `docs/runbook/2026-07-19-enrich-only-pass.md` §4
- 1회성 배치 절차: `docs/runbook/2026-08-08-onetime-db-batch-via-tunnel.md`
- 이번 회차의 실측: `docs/superpowers/specs/2026-08-10-article-stage-redefinition-design.md` §6.5
- 층마다 값이 달라지는 문제: `docs/troubleshooting/2026-08-20-rendered-values-are-not-raw-data.md`
