# 배포 전에 홈 화면을 운영 데이터로 재현해 재는 절차 (2026-08-28)

서빙 변경은 **머지 전에** 실물로 확인할 수 있다.
운영 DB 에 ssh 터널을 뚫고 로컬에서 새 코드로 렌더한 뒤 브라우저로 재면 된다.

2026-08-28 회차 (홈 카드 접기 · PR #352 ~ #359) 에서 여덟 번 썼고, 이 절차로만 잡힌 결함이 셋이다.

- 카드 아래끝이 55px 어긋나던 것
- 꺼낸 기사가 카드로는 감춰져 아무 데서도 안 보이던 것
- 확정 도구의 재렌더가 서빙 필터를 건너뛰던 것

## 1. 언제 쓰나

| 상황 | 이 절차 | 더 가벼운 대안 |
| --- | --- | --- |
| 템플릿 · 렌더 코드가 바뀜 | **이것** | 없음 |
| CSS · JS 만 바뀜 | 써도 되지만 과함 | `2026-08-27-checking-a-screen-change-without-the-database.md` |
| 배포 뒤 확인 | 아님 | `2026-07-20-vm-cohost-bootstrap.md` §8 (배포본 · 프리뷰 · 라이브 셋) |

**로컬 DB 로는 못 한다** — `article_players` 가 비어 있어 선수 페이지가 오류 없이 0개로 나온다
(`local-mart-cannot-render-player-pages` 메모리).

## 2. 터널

```bash
ssh -i ~/.ssh/<키> -f -N -L 13307:127.0.0.1:3306 <운영 사용자>@<운영 호스트>
nc -z 127.0.0.1 13307 && echo "터널 열림"
```

**포트는 세션마다 다르게 잡는다** — 병렬 세션이 같은 포트를 쓰면 서로의 터널을 죽인다.

끝나면 닫는다.

```bash
pkill -f "13307:127.0.0.1:3306"
```

## 3. 렌더 — 인자를 `run.py` 와 1:1 로

**`serving_rows` 를 빼면 fmkorea 무관 글과 옛 글이 화면으로 돌아온다.**
런북 스니펫과 확정 도구가 실제로 그 한 줄을 빠뜨리고 있었다
(`docs/troubleshooting/2026-08-28-the-comment-said-1-to-1-but-only-half-was-copied.md`).

```python
"""새 템플릿 · 자산으로 운영 데이터를 스크래치패드에 렌더한다 (실 site/ 는 안 건드린다)."""
import os, yaml
from pathlib import Path
from sqlalchemy import create_engine, text

from bullet_in.run import SERVING_SELECT_SQL, LINKED_HASHES_SQL, serving_rows
from bullet_in.score import load_sources
from bullet_in.credibility import load_registry, journalist_directory, outlet_directory
from bullet_in.adapters.factory import build_adapters
from bullet_in.storage.players import PlayerStore
from bullet_in.serve.render import write_site

OUT = "<스크래치패드>/new_dir"
engine = create_engine(os.environ["MARIADB_URL"])
cfg = yaml.safe_load(Path("config/sources.yaml").read_text())

with engine.connect() as c:
    rows = [dict(r) for r in c.execute(text(SERVING_SELECT_SQL)).mappings().all()]
    linked = set(c.execute(text(LINKED_HASHES_SQL)).scalars().all())

adapters = build_adapters(cfg, fmkorea_player_names=PlayerStore(engine).confirmed_ko_names())
fm = next(a for a in adapters if a.source_id == "fmkorea")
rows, hidden, stale = serving_rows(rows, relevance_terms=fm.relevance_terms,
                                   player_names=fm.player_names, linked=linked)
blank = sum(1 for r in rows if not r["transfer_stage"])
assert blank == 0, f"stage 빈 행 {blank} — 렌더 중단"

write_site(rows, load_sources("config/sources.yaml"), OUT,
           directory=journalist_directory("config/credibility.yaml"),
           registry=load_registry("config/credibility.yaml"),
           outlet_dir=outlet_directory("config/credibility.yaml"))
print(f"렌더 완료 {len(rows)}행 (무관 {hidden} · 옛 글 {stale} 제외)")
```

돌릴 때는 운영 주소로 바꾼 env 를 준다.

```bash
set -a; . ./.env; set +a
export MARIADB_URL="${MARIADB_URL/@localhost:3306/@127.0.0.1:13307}"
uv run --project . python <스크립트> 
```

**행 수를 먼저 본다** — 서빙 행 수와 `ls new_dir/article/*.html | wc -l` 이 같아야 한다.

## 4. 브라우저로 열기

`file://` 은 확장이 막는다.
로컬 http 서버를 띄운다.

```bash
cd <스크래치패드> && nohup python3 -m http.server 8777 >/dev/null 2>&1 &
# 끝나면 pkill -f "http.server 8777"
```

주소는 `http://localhost:8777/new_dir/index.html` 이다.

## 5. 재는 법 — 눈이 아니라 좌표와 개수로

**보는 것으로는 몇 px 어긋났는지 못 잰다.**
`javascript_tool` 로 값을 뽑는다.

**행마다 카드 아래끝이 맞는지**

```javascript
[...document.querySelectorAll('.daygroup')].slice(0,3).flatMap(g => {
  const bl = [...g.querySelectorAll('.block')].filter(b => b.style.display !== 'none');
  const out = [];
  for (let i = 0; i < bl.length; i += 2) {
    const a = bl[i], c = bl[i+1]; if (!c) continue;
    out.push(Math.abs(Math.round(a.getBoundingClientRect().bottom
                               - c.getBoundingClientRect().bottom)));
  }
  return out;
})
```

**화면에 실제로 서 있는 카드 수와 그 공신력**

```javascript
[...document.querySelectorAll('.daygroup .block')]
  .filter(b => b.style.display !== 'none')
  .map(b => b.querySelector('.item')?.dataset.tier)
```

**감춰진 카드와 그 이유** — 마크업 계수와 화면 계수가 갈리는 자리다.

```javascript
[...document.querySelectorAll('.daygroup .block')]
  .filter(b => b.style.display === 'none')
  .map(b => { const it = b.querySelector('.item');
              return [it?.dataset.stage, it?.classList.contains('dupcard')]; })
```

## 6. 말할 때 조건을 붙인다

이 절차의 결과는 **아직 배포되지 않은 코드의 화면**이다.

- 「PR #357 을 적용하면 0장이 됩니다」 — 맞다
- 「지금 최신 소식에 최하 카드는 없습니다」 — **틀리다** (라이브는 그 앞 배포본이다)

2026-08-28 에 이 구분을 안 해서 사용자에게 두 번 틀린 답을 했다
(`docs/troubleshooting/2026-08-28-we-measured-one-screen-and-talked-about-another.md`).

## 7. 배포 뒤에는 세 곳을 다시 본다

머지 · VM 반영 · 재렌더 · 배포까지 하고 나면 라이브에서 같은 값을 다시 잰다.

```bash
curl -sL https://<배포해시>.bullet-in.pages.dev -o preview.html
curl -sL -H 'Cache-Control: no-cache' "https://bullet-in.pages.dev/?cb=$RANDOM" -o live.html
```

**Cloudflare Pages 는 없는 경로도 200 을 돌려준다** (소프트 404).
링크가 살아 있는지는 상태 코드가 아니라 **본문 제목**으로 판정한다.

```javascript
const t = await (await fetch('player/meslier.html')).text();
t.match(/<title>([^<]*)<\/title>/)[1]     // 「일란 멜리에 · Bullet-in」 이어야 한다
```

## 함께 볼 것

- `docs/runbook/2026-08-27-checking-a-screen-change-without-the-database.md` — 자산만 바꿨을 때의 가벼운 확인
- `docs/runbook/2026-08-11-premerge-screen-check-with-prod-copy.md` — 운영 사본을 뜨는 다른 방식
- `docs/troubleshooting/2026-08-02-rerender-during-reclassification.md` — 단계가 빈 행이 있을 때 렌더를 멈추는 이유
