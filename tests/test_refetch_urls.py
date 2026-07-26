import asyncio
from datetime import datetime, timezone
import httpx
from bullet_in import refetch_urls
from bullet_in.refetch_urls import build_item, format_result

NOW = datetime(2026, 7, 26, tzinfo=timezone.utc)

HTML = """<html><head>
<meta property="og:title" content="Arsenal complete Tzolis signing">
<meta property="og:image" content="https://img.test/t.jpg">
</head><body><article>Full body text here.</article></body></html>"""

def test_build_item_shapes_payload_like_html_adapter():
    # 정기 수집 (html 어댑터 상세 경로) 과 동형 payload — 가드의 same-source 갱신 경로로 통과
    it = build_item("bbc_sport", "https://www.bbc.com/sport/x", HTML, "article", NOW)
    assert it.source_type == "html"
    assert it.raw_payload["title"] == "Arsenal complete Tzolis signing"
    assert it.raw_payload["body"] == "Full body text here."
    assert it.raw_payload["image_url"] == "https://img.test/t.jpg"
    assert it.raw_payload["authors"] == []

def test_build_item_returns_none_without_title():
    # 제목 추출 실패 시 덮어쓰지 않는다 — 불완전 복원 방지
    assert build_item("bbc_sport", "https://x.test/a", "<html></html>", "article", NOW) is None

def test_build_item_without_body_selector_keeps_empty_body():
    it = build_item("bbc_sport", "https://x.test/a", HTML, None, NOW)
    assert it.raw_payload["body"] == ""


def test_format_result_dry_run_marks_not_persisted():
    assert format_result(3, 0, 0, True) == "[dry-run] 검증 3건 (미적재)"


def test_format_result_live_run_uses_confirmed_vocabulary():
    assert (format_result(5, 12, 15, False)
            == "적재 5 · 동일 내용 생략 12 · 기존 기사 유지 15")


class _FakeResponse:
    def __init__(self, text):
        self.text = text
    def raise_for_status(self):
        pass


def _fake_client_factory(plan):
    """httpx.AsyncClient 대역 — url 별로 정해진 결과 (성공 html · fail) 를 재현한다."""
    class _FakeAsyncClient:
        def __init__(self, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def get(self, url):
            action = plan[url]
            if action == "fail":
                raise httpx.HTTPError("boom")
            return _FakeResponse(action)
    return _FakeAsyncClient


NO_TITLE_HTML = "<html><body>제목 없음</body></html>"


def test_refetch_keeps_gap_after_fetch_and_title_failures(monkeypatch):
    # fetch 실패 · 제목 추출 실패 모두 continue 였던 기존 루프는 그 뒤 sleep 을 건너뛴다 —
    # finally 로 옮긴 뒤에는 마지막 항목을 뺀 모든 항목 뒤에 간격이 유지돼야 한다.
    urls = ["https://x.test/fail", "https://x.test/no-title", "https://x.test/ok"]
    plan = {urls[0]: "fail", urls[1]: NO_TITLE_HTML, urls[2]: HTML}
    monkeypatch.setattr(refetch_urls.httpx, "AsyncClient", _fake_client_factory(plan))
    sleep_calls = []

    async def _fake_sleep(sec):
        sleep_calls.append(sec)
    monkeypatch.setattr(refetch_urls.asyncio, "sleep", _fake_sleep)

    n, dup, blocked = asyncio.run(refetch_urls.refetch("bbc_sport", urls, dry_run=True))
    assert (n, dup, blocked) == (1, 0, 0)   # 성공 (제목 추출 성공) 1건만 dry-run 집계
    assert len(sleep_calls) == 2            # 실패 2건 뒤에도 대기 · 마지막 (성공) 뒤는 대기 없음
