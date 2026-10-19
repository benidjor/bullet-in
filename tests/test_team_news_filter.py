"""홈 두 구역 · 「뉴스 종류」 필터 · 첫 화면 상한을 실제 브라우저로 본다 (설계 2026-10-20 §4 · §9.1).

렌더한 홈 · app.js · style.css 를 그대로 띄운다 — 구역 감춤과 상한은 CSS 와 JS 가 함께
만드는 결과라 문자열 검사로는 못 잰다. 크로미움이 없는 기계에서는 건너뛴다.
"""
from datetime import datetime
from pathlib import Path

import pytest

from bullet_in.serve.render import render_index

STATIC = Path(__file__).resolve().parents[1] / "src" / "bullet_in" / "serve" / "static"
NOW = datetime(2026, 6, 29, 12, 0, 0)
SOURCES = {"bbc_sport": {"display_name": "BBC Sport", "serving": "full"}}


def _row(h, stage, hour, direction="in"):
    return dict(content_hash=h, url=f"https://x/{h}", source_id="bbc_sport",
                title_original=h, title_ko=f"기사 {h}", summary_ko="요약", tier=2,
                confidence_score=0.5, image_url=None, outlet=None, team="arsenal",
                transfer_stage=stage, transfer_direction=direction,
                published_at=datetime(2026, 6, 29, hour, 0, 0))


# 모두 공신력 2등급이라 위쪽 띠 (상위 세 등급만 · render._TOP_TIERS) 는 비고,
# 이적 13건 · 팀 3건이 그대로 두 구역에 놓인다 (같은 날 · 날짜 묶음 하나).
ROWS = ([_row(f"t{i:02d}", "rumour", 11 - i % 10) for i in range(13)]
        + [_row(f"o{i}", "other", 1 + i) for i in range(3)])

JS = """async () => {
  const wait = ms => new Promise(r => setTimeout(r, ms));
  const vis = el => !!el && getComputedStyle(el).display !== 'none' && el.offsetParent !== null;
  const sect = k => document.querySelector(`.sect[data-kind="${k}"]`);
  const cards = k => [...sect(k).querySelectorAll('a.item:not(.dupcard)')].filter(vis).length;
  const snap = () => ({ transfer: vis(sect('transfer')) ? cards('transfer') : 0,
                        team: vis(sect('team')) ? cards('team') : 0 });
  const out = {};
  out.initial = snap();
  const cap = sect('transfer').querySelector('.capmore');
  out.capText = vis(cap) ? cap.textContent : null;
  cap.click(); await wait(30);
  out.afterCap = snap();
  document.querySelector('input[data-group="kind"][data-value="transfer"]').click();
  document.getElementById('applyBtn').click(); await wait(30);
  out.kindTransfer = snap();
  document.getElementById('resetBtn').click(); await wait(30);
  document.querySelector('input[data-group="stage"][data-value="rumour"]').click();
  document.getElementById('applyBtn').click(); await wait(30);
  out.stageRumour = snap();
  return out;
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


def _page(browser, tmp_path, query=""):
    (tmp_path / "index.html").write_text(render_index(ROWS, SOURCES, NOW), encoding="utf-8")
    for f in ("app.js", "style.css"):
        (tmp_path / f).write_text((STATIC / f).read_text(encoding="utf-8"), encoding="utf-8")
    page = browser.new_page()
    page.goto((tmp_path / "index.html").as_uri() + query)
    return page


def test_두_구역과_상한과_뉴스_종류_필터(browser, tmp_path):
    page = _page(browser, tmp_path)
    r = page.evaluate(JS)
    page.close()
    assert r["initial"] == {"transfer": 6, "team": 3}             # 이적 구역은 6장에서 멈춘다
    assert r["capText"] == "이적 뉴스 더보기 · 7건"
    assert r["afterCap"] == {"transfer": 13, "team": 3}
    assert r["kindTransfer"]["team"] == 0                         # 선수 · 팀 뉴스 구역째 감춤
    assert r["kindTransfer"]["transfer"] > 0
    assert r["stageRumour"]["team"] == 0                          # 단계를 고르면 단계 없는 기사는 빠진다


def test_옛_기타_주소는_선수_팀_뉴스만_보인다(browser, tmp_path):
    page = _page(browser, tmp_path, "?bucket=other")
    r = page.evaluate("""() => ({
      checked: document.querySelector('input[data-group="kind"][data-value="team"]').checked,
      transfer: getComputedStyle(document.querySelector('.sect[data-kind="transfer"]')).display,
      team: getComputedStyle(document.querySelector('.sect[data-kind="team"]')).display })""")
    page.close()
    assert r == {"checked": True, "transfer": "none", "team": "block"}


# 닷새에 이적 카드 셋씩 — 첫 화면은 앞 세 날짜 · 상한 6장 (1 · 2일째) · 3일째는 상한 뒤
DAYS = [_row(f"d{d}{i}", "rumour", 10 - i) | {"published_at": datetime(2026, 6, 29 - d, 10 - i)}
        for d in range(5) for i in range(3)]

RESET_JS = """async () => {
  const wait = ms => new Promise(r => setTimeout(r, ms));
  const vis = el => !!el && el.offsetParent !== null;
  const sect = document.querySelector('.sect[data-kind="transfer"]');
  const snap = () => ({
    cards: [...sect.querySelectorAll('a.item:not(.dupcard)')].filter(vis).length,
    days: [...sect.querySelectorAll('.daygroup')].filter(vis).map(g => g.dataset.date),
    cap: vis(sect.querySelector('.capmore')) ? sect.querySelector('.capmore').textContent : null,
    more: vis(sect.querySelector('.latestmore')) });
  const first = snap();
  document.querySelector('input[data-group="kind"][data-value="transfer"]').click();
  document.getElementById('applyBtn').click(); await wait(30);
  const filtered = snap();
  document.getElementById('resetBtn').click(); await wait(30);
  return { first, filtered, reset: snap() };
}"""


def test_필터를_풀면_첫_화면으로_돌아간다(browser, tmp_path):
    (tmp_path / "index.html").write_text(render_index(DAYS, SOURCES, NOW), encoding="utf-8")
    for f in ("app.js", "style.css"):
        (tmp_path / f).write_text((STATIC / f).read_text(encoding="utf-8"), encoding="utf-8")
    page = browser.new_page()
    page.goto((tmp_path / "index.html").as_uri())
    r = page.evaluate(RESET_JS)
    page.close()
    assert r["first"] == {"cards": 6, "days": ["2026-06-29", "2026-06-28"],
                          "cap": "이적 뉴스 더보기 · 3건", "more": False}
    assert r["filtered"]["cards"] == 15 and r["filtered"]["cap"] is None
    assert r["reset"] == r["first"]                              # 날짜 펼침 · 상한이 첫 화면 그대로
