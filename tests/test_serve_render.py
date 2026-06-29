from pathlib import Path

STATIC = Path("src/bullet_in/serve/static")

def test_static_assets_exist_and_nonempty():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "data-theme" in css and "--bg" in css      # 테마 변수
    assert ".card" in css and ".side" in css
    assert "data-outlet" in js and "data-tier" in js   # 카드 필터 계약
    assert "localStorage" in js                        # 테마 영속
