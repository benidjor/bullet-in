"""공신력을 고르면 자동 체크되는 소스 · 기자는 조건이 아니다 (UI 스펙 2026-07-21 §7.2).

app.js 를 실제 브라우저에서 돌려 사이드바 건수와 적용 결과가 같은지 본다 — 문자열 검사로는
「자동 체크가 결과를 바꾸는가」 를 못 잰다. 크로미움이 없는 기계에서는 건너뛴다.
"""
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "src" / "bullet_in" / "serve" / "static"


def _card(hash_, tier, journalist, stage="rumour", direction="in"):
    return (f'<div class="block"><a class="item" href="#" data-hash="{hash_}" data-stage="{stage}" '
            f'data-dir="{direction}" data-tier="{tier}" data-outlet="X" data-journalist="{journalist}" '
            f'data-published="2026-09-18T10:00:00" data-confidence="0" data-text="t">{hash_}</a></div>')


# 최상 세 장 (Ornstein · Mokbel · 기자 미상) 과 최하 한 장 — 사이드바의 최상 건수는 3 이다.
PAGE = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"></head><body>
<aside class="side">
  <label class="opt"><input type="checkbox" data-group="team" data-value="arsenal" checked> Arsenal</label>
  <div class="grp" data-grp="tier"><button class="grphead" type="button">공신력</button><div class="grpbody">
    <label class="opt"><input type="checkbox" data-group="tier" data-value="all" checked> 전체 <span class="ct">4</span></label>
    <label class="opt"><input type="checkbox" data-group="tier" data-value="1"> 공신력 최상 <span class="ct">3</span></label>
    <label class="opt"><input type="checkbox" data-group="tier" data-value="4"> 공신력 최하 <span class="ct">1</span></label>
  </div></div>
  <div class="grp collapsed" data-grp="journalist"><button class="grphead" type="button">기자</button><div class="grpbody">
    <label class="opt"><input type="checkbox" data-group="journalist" data-value="David Ornstein" data-tier="1"> David Ornstein</label>
    <label class="opt"><input type="checkbox" data-group="journalist" data-value="Sami Mokbel" data-tier="1"> Sami Mokbel</label>
  </div></div>
  <div class="fstatus" id="fstatus">조건 없음 · 전체 4건</div>
  <button class="btn reset" id="resetBtn">초기화</button><button class="btn apply" id="applyBtn">필터 적용</button>
</aside>
<main><div class="latest"><div class="daygroup" data-date="2026-09-18"><div class="daydiv">d</div><div class="daylist flatlist">
{_card("a1", "1", "David Ornstein")}{_card("b2", "1", "Sami Mokbel")}{_card("c3", "1", "")}{_card("d4", "4", "Someone")}
</div></div></div></main>
<script src="app.js"></script></body></html>"""

JS = """async () => {
  const wait = ms => new Promise(r => setTimeout(r, ms));
  const status = () => document.getElementById('fstatus').textContent.trim();
  const shown = () => [...document.querySelectorAll('a.item')].filter(e => e.style.display !== 'none').map(e => e.dataset.hash);
  document.querySelector('input[data-group="tier"][data-value="1"]').click(); await wait(50);
  const auto = [...document.querySelectorAll('input[data-group="journalist"]')].filter(c => c.checked).length;
  document.getElementById('applyBtn').click(); await wait(50);
  const first = { status: status(), shown: shown() };
  document.querySelector('input[data-group="journalist"][data-value="David Ornstein"]').click(); await wait(50);
  document.getElementById('applyBtn').click(); await wait(50);
  return { auto, first, second: { status: status(), shown: shown() } };
}"""


@pytest.fixture(scope="module")
def browser():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        p = pw.sync_playwright().start()
        b = p.chromium.launch()
    except Exception as e:                                   # 크로미움 미설치 기계
        pytest.skip(f"chromium 없음: {e}")
    yield b
    b.close()
    p.stop()


def test_자동_체크된_기자는_조건이_아니고_손댄_뒤에야_조건이_된다(browser, tmp_path):
    (tmp_path / "all.html").write_text(PAGE, encoding="utf-8")
    (tmp_path / "app.js").write_text((STATIC / "app.js").read_text(encoding="utf-8"), encoding="utf-8")
    page = browser.new_page()
    page.goto((tmp_path / "all.html").as_uri())
    r = page.evaluate(JS)
    page.close()

    assert r["auto"] == 2                                     # 최상을 고르면 최상 기자 둘이 자동 체크
    assert r["first"] == {"status": "조건 1개 · 3건", "shown": ["a1", "b2", "c3"]}   # 사이드바 건수 3 과 같다
    assert r["second"] == {"status": "조건 2개 · 1건 · 직접 고름", "shown": ["b2"]}  # 손댄 뒤에는 기자가 조건
