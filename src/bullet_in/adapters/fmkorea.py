from __future__ import annotations
import asyncio
from collections import Counter
from datetime import datetime, timezone, timedelta
from urllib.parse import quote
import re
import logging
import httpx
from bs4 import BeautifulSoup
from bullet_in.models import RawItem

log = logging.getLogger(__name__)

_BODY_MAX_CHARS = 2000

ORIGIN_BODY_MIN_CHARS = 200


def origin_body_usable(body: str) -> bool:
    """원문 URL 이 돌려준 본문을 등급 2 재료로 채택해도 되는지 판정한다.

    상태 코드만으로는 부족하다 — 만료된 라이브 블로그가 200 과 함께 안내 문구를
    돌려주고, 그 문장이 언론사 본문으로 저장된 실사례가 있다
    (docs/troubleshooting/2026-08-02-origin-error-page-stored-as-body.md).
    길이 기준은 배포판 실측이다 (2026-08-03 · 등급 2 본문 273건 중 200자 미만은
    오류 안내 2건뿐 · 그다음으로 짧은 정상 본문이 251자).
    거부는 손실이 아니라 등급 하락이다 — 게시글 본문 (등급 1) 으로 물러선다."""
    return len((body or "").strip()) >= ORIGIN_BODY_MIN_CHARS

def _body_text(html: str, selector: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    el = soup.select_one(selector)
    return el.get_text(" ", strip=True)[:_BODY_MAX_CHARS] if el else ""

_URL_RE = re.compile(r"https?://[^\s\"'<>)]+")

_SRL_RE = re.compile(r"document_srl=(\d+)")

def _post_url_from_href(href: str, base_url: str) -> str | None:
    """검색결과 앵커 href → 정규 글 URL. document_srl 우선 · /NNNNN 폴백 · 없으면 None."""
    m = _SRL_RE.search(href or "") or re.match(r"/(\d{6,})", href or "")
    return f"{base_url.rstrip('/')}/{m.group(1)}" if m else None

def _squash(s: str) -> str:
    """공백 무시 비교용 — 게시자가 같은 말을 붙여 쓰기도 하고 띄어 쓰기도 한다."""
    return re.sub(r"\s+", "", s or "").lower()


def is_arsenal_relevant(title: str, body: str, relevance_terms, player_names) -> bool:
    """무관 글 판정 (워치리스트 스펙 §3.2) — 구단 키워드 (제목 · 본문) 또는 선수명 (제목) 포함 시 통과.

    인정 집합이 둘 다 비면 필터 없음 — 백필 등 기존 호출부 무영향.
    수집 (어댑터) 과 서빙 (run.py) 이 같은 규칙을 쓰도록 모듈 함수로 둔다.
    두 곳이 갈리면 화면에 남은 글과 새로 들어오는 글의 기준이 어긋난다."""
    if not relevance_terms and not player_names:
        return True
    t, b = _squash(title), _squash(body)
    if any(_squash(k) in t or _squash(k) in b for k in relevance_terms):
        return True
    return any(_squash(n) in t for n in player_names)


def _round_robin(per_kw: list[list[tuple[str, str]]], limit: int) -> list[tuple[str, str]]:
    """키워드별 결과 리스트를 라운드로빈으로 최대 limit개 뽑는다 (앞 키워드 독식 방지)."""
    out, i = [], 0
    while len(out) < limit and any(i < len(r) for r in per_kw):
        for r in per_kw:
            if i < len(r):
                out.append(r[i])
                if len(out) >= limit:
                    break
        i += 1
    return out

PAYWALLED_OUTLETS = {"The Athletic"}

OUTLET_MAP = {
    "디 애슬레틱": "The Athletic", "디애슬레틱": "The Athletic",
    "디 애슬래틱": "The Athletic", "디애슬래틱": "The Athletic",  # '래' 변종
    "The Athletic": "The Athletic",                              # 리터럴 명시
    # 등재 정식명 · 소스 설정과 같은 표기를 쓴다 — 다르면 같은 매체가 사이드바에서
    # 두 항목으로 갈린다 (직수집분 'Goal.com' 176건 ↔ 전재글 'Goal' 1건 실측).
    "골닷컴": "Goal.com", "르퀴프": "L'Équipe", "레퀴프": "L'Équipe",  # '레' 변종
    "인디펜던트": "The Independent", "디 인디펜던트": "The Independent",
    "텔레그래프": "The Telegraph",
    "DM": "Daily Mail", "비사커": "BeSoccer",
    "타임스": "The Times", "타임즈": "The Times",
}

# 클럽 공홈 말머리는 수집하지 않는다 (2026-07-19) — 이용자가 타 구단 공홈 발표에도
# [공홈] 을 써서 Arsenal.com tier 0 오귀속이 발생했고, 아스날 공홈은 직수집
# (arsenal_api) 이 구 URL 중복 없이 official 태깅까지 커버한다.
_OFFICIAL_PREFIX = "공홈"
_BRACKET_RE = re.compile(r"^\s*\[([^\]]+)\]")

def parse_bracket(title: str) -> tuple[str | None, str | None, bool]:
    """fmkorea 말머리 [언론사] / [언론사 - 기자] / [언론사-독점·단독] 파싱."""
    m = _BRACKET_RE.match(title)
    if not m:
        return None, None, False
    inner = m.group(1).strip()
    # 단독 보도 표식은 어휘가 흔들린다 ("독점" · "단독" 실측) — 기자명 자리로 새지 않게 전부 제거
    is_excl = ("독점" in inner) or ("단독" in inner)
    inner = inner.replace("독점", "").replace("단독", "")
    parts = re.split(r"\s*-\s*", inner, maxsplit=1)
    outlet = parts[0].strip(" -")
    journalist = parts[1].strip(" -") if len(parts) > 1 and parts[1].strip(" -") else None
    outlet = OUTLET_MAP.get(outlet, outlet)
    return (outlet or None), journalist, is_excl

_BYLINE_HEAD_CHARS = 200
_MONTHS = ("January|February|March|April|May|June|July|August|September|"
           "October|November|December")
# 축약형까지 넣어야 'Aug. 2, 2026' 같은 표기가 걸린다 (운영 6건이 'David Ornstein Aug'
# 로 저장돼 있었다). 3월 · 5월 · 6월 · 7월은 축약형이 전체 철자와 같아 목록에 없다.
_MONTHS_SHORT = "Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec"
_MONTH_ANY = rf"(?:{_MONTHS}|{_MONTHS_SHORT})"
# 충실도 게이트도 같은 규칙으로 숫자 집계에서 발행 표기를 뺀다 (fidelity.py 가 import).
PUBLISH_DT_RE = re.compile(
    rf"{_MONTH_ANY}\.?\s+\d{{1,2}}\s*,?\s*\d{{4}}|(?:Updated\s+)?\d{{1,2}}:\d{{2}}\s*[ap]m",
    re.I)
_SPACES_RE = re.compile(r"[ \t]{2,}")
# 이름 토큰은 대문자로 시작 · '뒤에 숫자가 오는 월 이름' 과 'Updated' 는 제외
# (바이라인 뒤 날짜에서 끊기 위함).
# 월을 접두로 막으면 안 된다 — Mario 가 Mar + io 로 걸려 사람 이름이 통째로 사라진다.
# 날짜가 뒤따르는지까지 봐야 Aug. 2 는 빠지고 Mario · August (사람 이름) 는 남는다.
# 토큰 사이 구분자는 공백만 — 개행을 넘으면 다음 줄의 'Published' 가 이름에 붙는다 (실측 3건).
_NAME_TOKEN = rf"(?!(?:{_MONTH_ANY}\.?\s+\d|Updated\b))[A-Z][\w'’\-]*"
_NAME_PARTICLE = r"(?:de|van|von|der|del|di|da|le|la)"
_NAME = rf"{_NAME_TOKEN}(?: +(?:{_NAME_PARTICLE} +)?{_NAME_TOKEN})*"
# 공저 구분자는 쉼표와 and — 뒤에 다시 이름이 와야 인정한다 (뒤따르는 시각 · 직함 방지).
_BYLINE_RE = re.compile(rf"\bBy +({_NAME}(?: *(?:,|and) +{_NAME})*)")
_AUTHOR_SPLIT_RE = re.compile(r"\s*,\s*|\s+and\s+")
# 한글로 옮겨진 바이라인 — 게시자가 원문 저자를 번역해 적는다.
# 한글에는 대소문자가 없어 이름 끝을 알 수 없으므로 이름 토큰으로 못 자른다.
# 형태가 둘로 갈린다 (운영 본문 눈검수 2026-08-19).
# → 표지만 있고 이름이 어디서 끝나는지 모르는 것 ('By' · '글:') 은 왼쪽부터 읽어
#   본문이 시작하는 데서 멈춘다.
# → 괄호 · 콜론 · 하이픈은 이름의 끝을 알려 준다. 이때는 잡힌 조각이 전부 이름이어야
#   하고 하나라도 아니면 바이라인이 아니다 — 괄호 안 편집자 주와 그렇게 갈린다.
# '글' 은 흔한 낱말이라 콜론이 있을 때만 근거로 쓴다.
_KO_BYLINE_RE = re.compile(r"(?:\bBy\s+|글\s*[:：]\s*)([가-힣].{0,120})")
_KO_PAREN_RE = re.compile(r"^\s*[\(（]([^)）]{2,80})[\)）]")
_KO_COLON_RE = re.compile(r"^\s*([가-힣][가-힣 ·]{1,30})\s*[:：]\s")
_KO_DASH_RE = re.compile(r"^\s*[A-Za-z][A-Za-z .'’]{2,25}\s*[-–—]\s*([가-힣][가-힣 ·]{1,40})")
_KO_NAME_MAX_CHARS = 14      # 이름 조각의 길이 상한 (실측 최장 '세바스찬 스태포드-블루어' 13자)
_KO_SENTENCE_TAIL = re.compile(r"(다|요|죠)$")
# 직함은 사람이 아니다 — 실측상 이 낱말들이 비-이름 전부를 덮는다 (설계 §1.4).
# writer · editor 는 표지 없는 바이라인 실측에서 더했다 (안건 κ 설계 §4).
_JOB_TITLE_WORDS = r"REPORTER|CORRESPONDENT|WRITER|EDITOR"
_JOB_TITLE_RE = re.compile(_JOB_TITLE_WORDS, re.I)
# 표지 없는 바이라인 — 본문 첫 조각이 '이름 + 직함구' 로 시작한다.
# 실물은 BBC 라이브 포스트 페이지다 ('Alex Howell Arsenal reporter With a squad…').
# 이 페이지는 구조화 정보에 저자를 안 실어서 화면의 이름이 본문 앞머리에만 남는다.
# 이름의 끝을 알려 주는 것은 직함 낱말뿐이라 그것이 없으면 채택하지 않는다 —
# 경계가 없는 형태를 넓히면 첫 문장이 통째로 이름으로 들어온다 (안건 y 가 남긴 규율).
# 직함구는 두 어절까지 앞에 붙을 수 있다 ('Senior football correspondent').
_LEAD_BYLINE_RE = re.compile(
    rf"^\s*({_NAME_TOKEN}(?: +{_NAME_TOKEN})?) +(?:[\w'’\-]+ +){{0,2}}"
    rf"(?i:{_JOB_TITLE_WORDS})\b")


def strip_publish_datetime(body: str) -> str:
    """본문 앞머리 (200자) 의 발행 날짜 · 시각 표기만 지운다 — 기자명은 남긴다.

    같은 정보가 published_at 컬럼에 있어 본문의 표기는 중복이다.
    범위를 앞머리로 한정하는 이유는 뒤쪽 인용 트윗의 작성 시각 보존
    (실측 98건: 앞머리 10건 · 그 밖 3건이 전부 한 행의 인용 트윗).
    제거가 없었으면 원본을 글자 그대로 돌려준다."""
    if not body:
        return body
    head, tail = body[:_BYLINE_HEAD_CHARS], body[_BYLINE_HEAD_CHARS:]
    cleaned, removed = PUBLISH_DT_RE.subn("", head)
    if not removed:
        return body
    return (_SPACES_RE.sub(" ", cleaned) + tail).strip() or body


def _looks_like_a_name(part: str) -> bool:
    """이름 조각의 모양 — 한두 어절 · 짧음 · 숫자 없음 · 종결어미 없음."""
    tokens = part.split()
    return (1 <= len(tokens) <= 2 and len(part) <= _KO_NAME_MAX_CHARS
            and not re.search(r"\d", part) and not _KO_SENTENCE_TAIL.search(part))


def _bounded_korean_authors(head: str) -> list[str]:
    """끝을 알려 주는 표지 (괄호 · 콜론 · 하이픈) 가 감싼 저자 전원.

    감싼 조각이 **전부** 이름 모양이어야 채택한다.
    괄호에는 편집자 주도 들어오고 (`(이 기사는 원래 6월 26일에 …)`) 콜론 앞에는
    기사 제목도 오므로, 하나라도 어긋나면 통째로 버리는 쪽이 맞다."""
    for rx in (_KO_PAREN_RE, _KO_COLON_RE, _KO_DASH_RE):
        m = rx.match(head)
        if not m:
            continue
        parts = [p.strip() for p in re.split(r"\s*[,·]\s*", m.group(1)) if p.strip()]
        # 하이픈 뒤는 이름과 본문이 붙어 있다 — 앞 두 어절까지가 이름이다
        if rx is _KO_DASH_RE and parts:
            parts = [" ".join(parts[0].split()[:2])]
        if parts and all(_looks_like_a_name(p) for p in parts):
            return list(dict.fromkeys(parts))
    return []


def _korean_body_authors(body: str) -> list[str]:
    """한글로 옮겨진 바이라인의 저자 전원.

    이름의 끝을 알려 주는 표지 (괄호 · 콜론 · 하이픈) 가 있으면 그것을 먼저 쓴다.
    없으면 왼쪽부터 읽어 본문이 시작하는 데서 멈춘다 — 쉼표로 쪼개되 오른쪽 끝을
    경계로 쓰면 본문에도 쉼표가 있어 문장이 통째로 이름으로 들어온다
    (실측 '이적료는 7,000만 유로').
    이름만 있는 조각은 그대로 쓰고, 본문이 붙기 시작한 조각에서 멈추되 그 조각의
    앞 두 어절을 마지막 저자로 본다 — 음역된 서양 이름이 일관되게 두 어절이다."""
    head = re.sub(r"\s+", " ", body)[:_BYLINE_HEAD_CHARS]
    bounded = _bounded_korean_authors(head)
    if bounded:
        return bounded
    m = _KO_BYLINE_RE.search(head)
    if not m:
        return []
    out: list[str] = []
    for part in re.split(r"\s*[,·]\s*", m.group(1)):
        tokens = part.split()
        if _looks_like_a_name(part):
            out.append(part)
            continue
        if tokens:
            out.append(" ".join(tokens[:2]))
        break
    return [n for n in dict.fromkeys(out) if n]


def _unmarked_lead_authors(body: str) -> list[str]:
    """표지 없이 본문 첫 조각에 붙은 저자 1명 — 직함 낱말이 이름의 끝이다.

    근거는 페이지가 아니라 **우리가 채택한 본문 조각**이다.
    라이브 페이지 한 장에는 기여자가 여럿 실려 있어서, 페이지에서 이름을 긁으면
    우리가 채택하지 않은 포스트의 저자가 붙는다 (설계 §4.1)."""
    m = _LEAD_BYLINE_RE.match(body)
    return [m.group(1)] if m else []


def extract_body_authors(body: str) -> list[str]:
    """본문 앞머리 바이라인의 저자 전원 — 등장 순서 보존 · 중복 제거.

    fmkorea 전재글은 원문 바이라인이 journalist 컬럼이 아니라 본문 앞머리에만 있다.
    그래서 공저 기사가 저자 각각의 기자 필터에 도달하려면 여기서 전원을 읽어야 한다.
    정규식은 넓히지 않는다 — 새 오염이 나오면 문구가 아니라 '등재 기자만 채택' 으로
    좁힌다 (설계 §2.2 · 경계 사례를 문구로 가르려다 시소에 걸린 전례가 있다)."""
    if not body:
        return []
    m = _BYLINE_RE.search(body[:_BYLINE_HEAD_CHARS])
    if not m:
        return _korean_body_authors(body) or _unmarked_lead_authors(body)
    out: list[str] = []
    for part in _AUTHOR_SPLIT_RE.split(m.group(1)):
        part = part.strip()
        if part and not _JOB_TITLE_RE.search(part) and part not in out:
            out.append(part)
    return out


def extract_body_journalist(body: str) -> str | None:
    """본문 앞머리 바이라인의 대표 기자 1명 — 본문은 건드리지 않는다.

    journalist 컬럼은 단일 문자열이라 첫 저자만 남긴다.
    저자 전원은 authors 로 따로 실린다 (extract_body_authors)."""
    authors = extract_body_authors(body)
    return authors[0] if authors else None


_REPOST_BLOCK_TEXT = "퍼가기가 금지된"

def _is_repost_blocked(html: str) -> bool:
    """퍼가기 금지 표식 감지 — 실측 DOM(2026-07-19): .rd_body 직하위 strong, 본문(.xe_content) 밖."""
    soup = BeautifulSoup(html, "html.parser")
    rb = soup.select_one(".rd_body")
    if rb is None:
        return False
    return any(_REPOST_BLOCK_TEXT in s.get_text()
               for s in rb.select("strong")
               if s.find_parent(class_="xe_content") is None)

_KST = timezone(timedelta(hours=9))
_POST_DATE_RE = re.compile(r"(\d{4})\.(\d{2})\.(\d{2})\s+(\d{2}):(\d{2})")

def _post_published(html: str) -> datetime | None:
    """fmkorea 게시 시각 — 실측 (2026-07-20) `.rd_hd .date` 'YYYY.MM.DD HH:MM' KST → UTC.
    목록 위젯의 .date 다중 매칭 (실측 7개) 이 있어 반드시 .rd_hd 스코프."""
    soup = BeautifulSoup(html, "html.parser")
    el = soup.select_one(".rd_hd .date")
    m = _POST_DATE_RE.search(el.get_text(strip=True)) if el else None
    if not m:
        return None
    y, mo, d, h, mi = map(int, m.groups())
    return datetime(y, mo, d, h, mi, tzinfo=_KST).astimezone(timezone.utc)

def _extract_original_url(html: str, body_selector: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    el = soup.select_one(body_selector)
    if el is None:
        return None
    # 1) 본문 평문 출처 URL 우선 (fmkorea 관례: 본문 끝). 여럿이면 마지막.
    plains = [m.group(0) for m in _URL_RE.finditer(el.get_text(" ", strip=True))
              if "fmkorea.com" not in m.group(0)]
    if plains:
        return plains[-1]
    # 2) 폴백: 외부 앵커 (기자 프로필일 수 있으나 평문 없을 때만)
    for a in el.select("a[href]"):
        href = a.get("href", "")
        if href.startswith("http") and "fmkorea.com" not in href:
            return href
    return None

async def _fetch_og_image(client: httpx.AsyncClient, url: str) -> str | None:
    from bullet_in.adapters.meta import extract_og_image
    try:
        r = await client.get(url, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError:
        return None
    return extract_og_image(r.text)

class FmkoreaAdapter:
    source_type = "html"
    def __init__(self, source_id: str, search_url: str, search_keywords: list[dict],
                 item_selector: str = "a.hx",
                 base_url: str = "https://www.fmkorea.com",
                 body_selector: str = ".xe_content", max_posts: int = 15,
                 proxy: str | None = None, pages: int = 1,
                 request_gap_sec: float = 0.0,
                 exclude_titles: set[str] | None = None,
                 relevance_terms: list[str] | None = None,
                 player_names: set[str] | None = None):
        self.source_id = source_id
        self.search_url = search_url            # {keyword} · {target} 자리표시 포함
        self.search_keywords = search_keywords
        self.item_selector = item_selector
        self.base_url = base_url
        self.body_selector = body_selector
        self.max_posts = max_posts
        self.proxy = proxy
        self.pages = pages
        self.request_gap_sec = request_gap_sec
        self.exclude_titles = exclude_titles or set()
        self.relevance_terms = relevance_terms or []
        self.player_names = player_names or set()
        self.search_failures = 0      # 이번 fetch 에서 실패한 키워드 검색 수
        self.search_failure_codes: Counter = Counter()   # 실패 사유 (HTTP 상태 코드 · 연결 오류)
        self.relevance_dropped = 0    # 무관 글 필터 탈락 수

    async def _gap(self) -> None:
        """fmkorea 요청 사이 간격 — 0 이면 대기 없음 (정기 회차 동작 불변)."""
        if self.request_gap_sec:
            await asyncio.sleep(self.request_gap_sec)

    async def _discover(self, c: httpx.AsyncClient) -> list[tuple[str, str]]:
        """키워드 × 페이지 검색 → a.hx 파싱 → 정규 글 URL.
        키워드별 결과를 라운드로빈으로 max_posts 배분한다."""
        self.search_failures = 0
        self.search_failure_codes = Counter()
        per_kw, seen, first = [], set(), True
        for kw in self.search_keywords:
            results = []
            for page in range(1, self.pages + 1):
                url = self.search_url.format(keyword=quote(kw["keyword"]),
                                             target=kw["target"], page=page)
                if not first:
                    await self._gap()
                first = False
                try:
                    r = await c.get(url)
                    r.raise_for_status()
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429:
                        log.warning("fmkorea 검색 429(rate limit) kw=%s p=%s — 스킵",
                                    kw["keyword"], page)
                    else:
                        log.warning("fmkorea 검색 HTTP %s kw=%s p=%s — 스킵",
                                    e.response.status_code, kw["keyword"], page)
                    self.search_failures += 1
                    self.search_failure_codes[e.response.status_code] += 1
                    break                       # 이 키워드의 남은 페이지도 중단
                except httpx.HTTPError as e:
                    log.warning("fmkorea 검색 실패 kw=%s p=%s err=%s — 스킵",
                                kw["keyword"], page, e)
                    self.search_failures += 1
                    self.search_failure_codes["error"] += 1
                    break
                soup = BeautifulSoup(r.text, "html.parser")
                for a in soup.select(self.item_selector):
                    title = a.get_text(strip=True)
                    post_url = _post_url_from_href(a.get("href", ""), self.base_url)
                    if not title or not post_url or post_url in seen:
                        continue
                    seen.add(post_url)
                    if title in self.exclude_titles:
                        continue            # 이미 적재된 글 — 본문 접촉 없이 건너뛴다
                    must = kw.get("title_must_contain")
                    # title_content 검색은 본문만 스친 글도 잡는다 — 제목 필수어로 좁힌다.
                    # 공백을 무시해 비교한다 (게시자가 '아르테타의' 처럼 붙여 쓴다).
                    if must and _squash(must) not in _squash(title):
                        continue
                    results.append((title, post_url))
            per_kw.append(results)
        return _round_robin(per_kw, self.max_posts)

    def _relevant(self, title: str, body: str) -> bool:
        return is_arsenal_relevant(title, body, self.relevance_terms, self.player_names)

    async def _process(self, c: httpx.AsyncClient,
                       matched: list[tuple[str, str]]) -> list[RawItem]:
        """글별 fetch → 말머리 파싱 → 페이월/무료 라우팅 → RawItem."""
        from bullet_in.adapters.meta import (extract_authors, extract_og_image,
                                             extract_article_body, extract_body_images,
                                             extract_published_at)
        now, out = datetime.now(timezone.utc), []
        for i, (title, url) in enumerate(matched):
            if i:
                await self._gap()
            pub: tuple | None = None
            try:
                rb = await c.get(url)
                rb.raise_for_status()
            except httpx.HTTPError:
                continue  # 글 fetch 실패 — 스킵, 배치 지속
            html = rb.text
            outlet, journalist, _excl = parse_bracket(title)
            if outlet and _OFFICIAL_PREFIX in outlet:
                log.info("fmkorea [공홈] 말머리 drop — 직수집 경로가 커버 url=%s", url)
                continue
            orig = _extract_original_url(html, self.body_selector)
            if orig is None or outlet is None:
                log.warning("fmkorea 원문/말머리 해소 실패 — 스킵 url=%s", url)
                continue
            # 원문 본문을 채택하면 게시글 본문이 사라지므로 바이라인을 그 전에 읽어 둔다.
            # 게시자가 저자를 한글로 옮겨 적은 표기가 여기에만 있다 ('글: 로리 휘트웰, 베렌 크로스').
            post_body = _body_text(html, self.body_selector)
            post_authors = extract_body_authors(post_body)
            origin_authors: list[str] = []
            if outlet in PAYWALLED_OUTLETS:
                body = post_body
                if _is_repost_blocked(html):
                    # E안: 본문은 재작성해 서빙하되 게시글 이미지는 복제하지 않는다
                    # — 이미지는 재작성이 불가능해 리스크의 성격이 다르다.
                    log.info("fmkorea 퍼가기 금지 + 페이월 — 본문 채택 · 이미지 제외 url=%s", url)
                    images = []
                else:
                    # 게시글 이미지 ≈ 원문 기사 이미지 재게재 (spec 확정 결정)
                    images = extract_body_images(html, self.body_selector, base_url=url)
                image = await _fetch_og_image(c, orig)
                lang = "ko"
                material_level = 1        # 채택한 재료 = 커뮤니티가 옮긴 게시글 본문
            else:
                body, lang, material_level = "", "ko", 1
                image, images = None, []
                try:
                    ro = await c.get(orig)
                    ro.raise_for_status()
                except httpx.HTTPError:
                    # 원문 차단 (실측 26건 중 25건이 406 · 403 · 페이월) — 게시글 본문으로 폴백.
                    log.info("fmkorea 원문 접속 실패 — 게시글 본문 채택 url=%s", orig)
                else:
                    # 저자는 본문 채택 여부와 무관하다 — 원문이 오류 안내여서 등급이
                    # 1 로 내려가도 페이지의 구조화 정보에는 저자가 남아 있다.
                    origin_authors = extract_authors(ro.text)
                    origin_body = extract_article_body(ro.text)
                    if origin_body_usable(origin_body):
                        body, lang, material_level = origin_body, "en", 2
                        image = extract_og_image(ro.text)
                        images = extract_body_images(ro.text, base_url=orig)
                        pub = extract_published_at(ro.text)
                    else:
                        log.info("fmkorea 원문이 오류 안내로 보임 (%d자) — 게시글 본문 채택 url=%s",
                                 len((origin_body or "").strip()), orig)
                if material_level == 1:
                    body = post_body
            body = strip_publish_datetime(body)
            if not self._relevant(title, body):
                self.relevance_dropped += 1
                log.info("fmkorea 무관 글 필터 탈락 — title=%s url=%s", title, url)
                continue
            authors = extract_body_authors(body)
            if not authors:
                # 회수는 빈 자리만 채운다 — 이미 저자를 얻고 있던 기사의 대표를 바꾸면
                # 화면의 바이라인이 함께 움직인다.
                authors = origin_authors or post_authors
            if journalist:
                # 말머리 값이 대표 — 본문 공저자는 목록에만 남긴다 (기존 우선순위 유지)
                authors = [journalist] + [a for a in authors if a != journalist]
            else:
                journalist = authors[0] if authors else None
            body_level = material_level if body else 0
            if pub is None:
                post_dt = _post_published(html)
                pub = (post_dt, "time") if post_dt else None
            extra = ({"published": pub[0].isoformat(), "published_precision": pub[1]}
                     if pub else {})
            out.append(RawItem(
                source_id=self.source_id, source_type="html", url=orig,
                fetched_at=now,
                raw_payload={"title": title, "body": body, "body_level": body_level,
                             "lang": lang,
                             "outlet": outlet, "journalist": journalist,
                             "authors": authors,
                             "image_url": image, "images": images, **extra}))
        return out

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=20, follow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0 bullet-in/0.1"},
                                 proxy=self.proxy)

    async def discover(self) -> list[tuple[str, str]]:
        """검색 페이지만 읽어 후보 (제목 · 글 URL) 를 반환한다 — 글 본문은 받지 않는다."""
        async with self._client() as c:
            return await self._discover(c)

    async def fetch(self) -> list[RawItem]:
        async with self._client() as c:
            matched = await self._discover(c)
            return await self._process(c, matched)
