import asyncio

import httpx
import respx

from bullet_in import backfill_fmkorea_body as bf


def test_match_targets_pairs_exact_titles_only():
    targets = {"h1": "[텔레그래프] 아스날 수비 보강", "h2": "[더 타임스] 미드필더 관심"}
    found = [("[텔레그래프] 아스날 수비 보강", "https://www.fmkorea.com/111"),
             ("[더 타임스] 미드필더 관심 (수정)", "https://www.fmkorea.com/222")]
    assert bf.match_targets(targets, found) == {"h1": "https://www.fmkorea.com/111"}


def test_match_targets_ignores_surrounding_whitespace():
    targets = {"h1": "[BBC] 아스날 소식"}
    found = [("  [BBC] 아스날 소식 ", "https://www.fmkorea.com/1")]
    assert bf.match_targets(targets, found) == {"h1": "https://www.fmkorea.com/1"}


def test_row_update_extracts_body_and_journalist():
    html = ('<div class="rd_body"><div class="xe_content">'
            '<p>By David Ornstein June 19, 2026 3:19 am 리버풀이 협상 중이다.</p>'
            '</div></div>')
    upd = bf.row_update(html, ".xe_content")
    assert upd["body_level"] == 1
    assert "June 19, 2026" not in upd["body"]
    assert "By David Ornstein" in upd["body"]
    assert upd["journalist"] == "David Ornstein"


def test_row_update_returns_none_when_repost_blocked():
    html = ('<div class="rd_body"><div class="xe_content"><p>본문.</p></div>'
            '<strong>[퍼가기가 금지된 글입니다]</strong></div>')
    assert bf.row_update(html, ".xe_content") is None


def test_row_update_returns_none_when_body_empty():
    assert bf.row_update('<div class="rd_body"></div>', ".xe_content") is None


# --- 제목 기반 검색 (대상별 검색어 도출) ---

def test_search_candidates_puts_debracketed_title_first():
    """제목 전체가 가장 특정적이라 먼저 시도한다 (스펙에 없는 판단 · 실측 미완)."""
    cands = bf.search_candidates("[텔레그래프]아스날, 에미레이츠와 계약 연장")
    assert cands[0] == ("title", "아스날, 에미레이츠와 계약 연장")


def test_search_candidates_includes_outlet_plus_longest_token():
    # 사용자가 실제로 찾아낸 질의 형태 ('타임즈 기마랑이스' · '비사커 첼시')
    cands = bf.search_candidates("[타임즈] 기마랑이스를 두고 협상 중인아스날")
    assert ("title_content", "타임즈 기마랑이스") in cands


def test_search_candidates_trims_trailing_particle():
    # '에미레이츠와' → '에미레이츠' (조사를 떼야 사용자가 성공한 질의와 같아진다)
    cands = bf.search_candidates("[텔레그래프]아스날, 에미레이츠와 계약 연장")
    assert any(kw.endswith("에미레이츠") for _, kw in cands)


def test_search_candidates_handles_outlet_with_journalist():
    # 말머리에 기자명이 붙으면 매체명만 쓴다
    cands = bf.search_candidates("[텔레그래프-루크 에드워즈]아스날, 기마랑이스 재검토")
    assert any(kw.startswith("텔레그래프 ") for _, kw in cands)


def test_search_candidates_survives_title_without_bracket():
    cands = bf.search_candidates("아스날 소식")
    assert cands and all(kw for _, kw in cands)


def test_search_candidates_are_unique_and_nonempty():
    cands = bf.search_candidates("[BeSoccer] PSG,디오망데영입 위해 협상 중")
    assert len(cands) == len(set(cands))
    assert all(kw.strip() for _, kw in cands)


# --- find_post_url: 후보를 순서대로 시도하고 제목 정확 일치에서 멈춘다 ---

SEARCH_TMPL = ("https://fm.test/s?target={target}&kw={keyword}&page={page}")


def _hit(title: str, srl: str = "999") -> httpx.Response:
    return httpx.Response(200, text=(
        f'<a class="hx" href="/index.php?document_srl={srl}">{title}</a>'))


_MISS = httpx.Response(200, text='<a class="hx" href="/index.php?document_srl=1">다른 글</a>')


@respx.mock
def test_find_post_url_stops_at_first_candidate_that_matches():
    title = "[텔레그래프]아스날, 에미레이츠와 계약 연장"
    first = respx.get(url__startswith="https://fm.test/s?target=title&kw=").mock(
        return_value=_hit(title, "1234"))
    url, tried = asyncio.run(_find(title))
    assert url == "https://www.fmkorea.com/1234"
    assert tried == 1                      # 첫 후보에서 멈춘다 (접촉 최소화)
    assert first.called


@respx.mock
def test_find_post_url_falls_through_to_later_candidate():
    title = "[타임즈] 기마랑이스를 두고 협상 중인아스날"
    respx.get(url__startswith="https://fm.test/s?target=title&kw=").mock(return_value=_MISS)
    respx.get(url__startswith="https://fm.test/s?target=title_content&kw=").mock(
        return_value=_hit(title, "555"))
    url, tried = asyncio.run(_find(title))
    assert url == "https://www.fmkorea.com/555"
    assert tried >= 2


@respx.mock
def test_find_post_url_returns_none_when_no_candidate_matches():
    title = "[BeSoccer] 없는 글"
    respx.get(url__startswith="https://fm.test/s").mock(return_value=_MISS)
    url, tried = asyncio.run(_find(title))
    assert url is None
    assert tried == len(bf.search_candidates(title))


@respx.mock
def test_find_post_url_gives_up_on_block_without_trying_rest():
    # 430 은 차단 신호 — 남은 후보를 더 두드리면 차단을 깊게 만든다
    title = "[텔레그래프]아스날, 에미레이츠와 계약 연장"
    respx.get(url__startswith="https://fm.test/s").mock(return_value=httpx.Response(430))
    url, tried = asyncio.run(_find(title))
    assert url is None
    assert tried == 1


async def _find(title: str):
    async with httpx.AsyncClient() as c:
        return await bf.find_post_url(c, title, SEARCH_TMPL, "a.hx",
                                      "https://www.fmkorea.com", gap_sec=0.0)


# 사용자가 브라우저로 직접 글을 찾아낸 (제목, 성공한 검색어) — 실측 계약
BROWSER_VERIFIED = [
    ("[텔레그래프]아스날, 에미레이츠와 계약 연장/연 £45M에서 대폭 인상", "에미레이츠"),
    ("[텔레그래프] 노팅엄 포레스트, 우스만디오망데영입 위해 £32m 공식 오퍼", "노팅엄"),
    ("[타임즈] 기마랑이스를 두고 협상 중인아스날", "타임즈 기마랑이스"),
    ("[비사커] 첼시가 어떻게아스날을 제치고 £117m에 모건 로저스를 영입했나", "비사커 첼시"),
]


def test_search_candidates_reproduce_browser_verified_keywords():
    """사람이 실제로 성공시킨 검색어를 도출 규칙이 만들어내야 한다.

    최장 토큰만 쓰면 2/4 다 — 게시자가 띄어쓰기를 붙여 써서 ('어떻게아스날을' ·
    '우스만디오망데영입') 최장 토큰이 쓰레기를 고른다. 첫 토큰 계열이 필요하다."""
    for title, proven in BROWSER_VERIFIED:
        kws = [kw for _, kw in bf.search_candidates(title)]
        assert proven in kws, f"{proven!r} 없음 · 도출={kws}"


def test_search_candidates_stay_bounded():
    # 후보가 늘면 대상당 접촉이 그만큼 늘어난다 — 상한을 계약으로 고정
    for title, _ in BROWSER_VERIFIED:
        assert len(bf.search_candidates(title)) <= 5
