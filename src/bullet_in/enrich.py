from __future__ import annotations
import json, logging, re

log = logging.getLogger(__name__)

from bullet_in import transfer_stage as _stage
from bullet_in.fidelity import RETENTION_THRESHOLD, gate_verdict, select_best

def _is_rate_limit(exc: Exception) -> bool:
    if getattr(exc, "code", None) == 429:
        return True
    s = str(exc)
    return "429" in s or "RESOURCE_EXHAUSTED" in s

SUMMARY_PROMPT = ("다음 한국어 축구 뉴스를 한 문장으로 요약한다. "
                  "신문 평어체(종결어미 '~다'), 사실 중심, 추측·과장 금지. "
                  "존댓말 금지: '영입을 확정했습니다' ❌ → '영입을 확정했다' ⭕. "
                  "고유명사는 통용 한글 표기(Arsenal=아스날). "
                  'JSON만 반환: {{"summary_ko": "..."}}\n\n제목: {title}\n본문: {body}')

RESUMMARY_PROMPT = (
    "다음 한국어 축구 기사의 요약을 다시 쓴다. 규칙:\n"
    "- summary_ko: 한 문장, 신문 평어체(종결어미 '~다'), 사실 중심.\n"
    "- summary3_ko: 핵심을 3문장으로, 각 문장 평어체. 문자열 3개 배열.\n"
    "- 존댓말 금지: '영입을 확정했습니다' ❌ → '영입을 확정했다' ⭕.\n"
    "- 고유명사는 통용 한글 표기(Arsenal=아스날).\n"
    'ONLY JSON: {{"summary_ko":"...","summary3_ko":["...","...","..."]}}'
    "\n\n제목: {title}\n본문: {body}")

# 세 프롬프트 (TRANSLATE · PARAPHRASE · EXTRACT_PLAYERS) 공통 players 조항 —
# 근거 조건 · 단계 정의의 정본은 스펙 2026-08-07-player-stage-reextraction-design.md §3.1.
# 단계 정의는 STAGE_PROMPT 의 한 줄 요약 계열과 어긋나면 안 된다 (두 프롬프트가
# 서로 다른 정의를 갖지 않게). 포함을 조인 만큼 (언급 인물 제외) 잘못 삼킬 이웃
# (라운드업 당사자 · 근황 인물 · 잔류 협상) 을 보존 조항으로 함께 적는다.
PLAYERS_CLAUSE = (
    "- 이 기사가 직접 다루는 인물만 넣는다. 다음 인물은 넣지 않는다: "
    "과거 사례 · 비교 · 순위 목록으로만 나열된 인물 (예: 역대 이적료 상위 선수들), "
    "아스날과 무관한 타 구단 간 소식의 인물, 기사에 없는 인물.\n"
    "- 단, 여러 아스날 관련 소식을 모은 기사면 각 소식의 당사자는 모두 넣고, "
    "경기 · 근황 · 부상만 다뤄진 인물도 기사가 직접 다루면 stage 를 other 로 넣는다.\n"
    "- 아스날 영입 대상 선수의 잔류 · 재계약 · 경쟁 구단 제안 소식도 그 선수의 "
    "거취 관련이므로 넣는다. stage 는 아스날 건 기준으로 매기고, 잔류 · 재계약이 "
    "체결 · 확정된 보도면 collapsed, 기사가 아스날 건의 진행을 말하지 않으면 other. "
    "아스날 언급이 없어도 기사의 주제가 한 선수와 현 소속 구단 사이의 잔류 · 재계약 "
    "건이면 그 선수를 넣고 stage 는 같은 기준 (체결 · 확정이면 collapsed · 그 밖은 "
    "other) 으로 한다. 다른 구단이 그 선수의 영입을 추진하는 기사에는 적용하지 않는다.\n"
    "- stage 는 이 기사가 그 선수에 대해 보도하는 진행 단계다. 기사 밖에서 아는 "
    "그 선수의 상황으로 답하지 않는다. 이 기사가 그 선수의 진행 단계를 말하지 "
    "않으면 other. stage 는 언제나 아스날 건 기준이다. 그 인물에 관해 이 기사가 "
    "전하는 것이 아스날과 무관한 딜뿐이면 other 다 — done 과 collapsed 는 특히 "
    "그렇다.\n"
    "- role 은 이 기사가 그 인물을 하나의 소식으로 다루는지다. subject = 제목이 그 "
    "인물을 내세우거나, 그 인물 이름이 들어간 소제목 · 별도 바이라인의 절이 있거나, "
    "라운드업에서 그 인물 몫의 단신이 독립적으로 있거나, 기사가 그 인물의 거취를 "
    "논평 대상으로 삼는다. mention = 한 문단 안에서 여러 인물과 함께 이름만 "
    "나열되거나 배경 · 과거 비교 · 대체자 · 경쟁자 · 이적료 기준점으로 불려 나온다. "
    "지면에서 차지하는 자리로 정한다 — 그 인물이 중요한 선수인지로 정하지 않는다.\n"
    "- stage 값: rumour(근거 약한 소문 · 연결설) · interest(구단의 실제 관심 · "
    "스카우팅 · 후보 검토) · negotiating(이적료 · 조건 협상 중 · 제안 · 거절 · "
    "합의 임박 · 근접) · personal_terms(선수-구단 개인 조건 합의) · medical(메디컬 테스트) · "
    "agreed(구단 간 완전 합의 도달 · 딜 확정을 사실로 보도 — 임박은 negotiating) · "
    "done(이미 완료된 아스날 이적의 후속 · 부대 보도 — 타 구단 간 완료 이적이 "
    "문장 안에 나열된 것은 other) · collapsed(아스날 관련 딜의 종결 — 잔류 확정 · "
    "재계약 체결 · 결렬 확정. 아스날이 자기 소속 선수와 맺는 신규 · 연장 계약은 "
    "종결이 아니다) · other(이적 무관 · 경기 · 근황 · 단계 불명).\n")

# 확정 링크 명단 조항 — 세 프롬프트가 공유한다 (추출 범위 개정 스펙 §6.5).
# 아스날이 한 글자도 안 나오는 기사에서 "이 선수가 아스날 영입 대상인가" 를 모델의
# 세계 지식이 아니라 검증된 재료로 판단하게 한다 (2026-08-08 소표본 실측: 아스날
# 미언급 잔류 · 재계약 트윗은 문구만으로는 안정적으로 안 잡힘).
ROSTER_CLAUSE = (
    "- 아스날 이적 링크가 확정된 선수 명단: {roster}.\n"
    "- 이 명단의 선수를 기사가 직접 다루면 — 잔류 · 재계약, 타 구단의 영입 접근, "
    "근황 포함 — 기사에 아스날 언급이 없어도 넣는다. stage 는 아스날 건 기준으로 "
    "매기고, 기사가 아스날 건의 진행을 말하지 않으면 other.\n")

TRANSLATE_PROMPT = (
    "아스날 FC 축구 뉴스를 한국어로 번역·요약한다. 규칙:\n"
    "- title_ko: 한국 스포츠 기사 제목체로 간결하게 (명사형 위주).\n"
    "- summary_ko: 한 문장, 신문 평어체(종결어미 '~다'), 사실 중심.\n"
    "- summary3_ko: 핵심을 3문장으로, 각 문장 평어체. 문자열 3개 배열.\n"
    "- summary_ko·summary3_ko 존댓말 금지: '확정했습니다' ❌ → '확정했다' ⭕.\n"
    "- body_ko: 본문 전체를 자연스러운 한국어로 번역. 2~4문장 단위 문단으로 나누고 "
    "문단 사이는 줄바꿈 문자(\\n)로 구분한다.\n"
    "- body_ko 는 요약이 아니라 완역이다: 기사 본문의 모든 문단을 순서대로 빠짐없이 "
    "옮기고, 수치 · 인용 · 세부 사실을 임의로 줄이거나 합치지 않는다. 기사 내용과 "
    "무관한 홍보 문구만 제외한다.\n"
    "- 여러 구단 소식을 나열한 라운드업(가십 등) 기사도 발췌하지 않는다: "
    "아스날 무관 구단 항목까지 본문 전체를 빠짐없이 번역하고, 단신을 하나도 빠뜨리지 않는다.\n"
    "- 라운드업 단신 끝의 괄호 출처 표기 — 예: (Sky Sports) — 는 번역하지 않고 "
    "원문 그대로 괄호 병기한다. ' - in Italian'·' - requires subscription' 류 "
    "부가 설명과 ', external' 링크 잔재는 제외.\n"
    "- body_ko 지문도 신문 평어체(종결어미 '~다'): '관심을 갖고 있습니다' ❌ → "
    "'관심을 갖고 있다' ⭕. 인용문(따옴표 안 발화)은 화자의 말투를 그대로 두되, "
    "발화 인용은 반드시 큰따옴표로 감싼다.\n"
    "- 구독·앱 설치·댓글 유도, SNS 팔로우 요청, 팟캐스트·뉴스레터 홍보 등 "
    "기사 내용과 무관한 문구는 body_ko에서 제외.\n"
    "- body_ko 경량 마크다운: 원문의 소제목은 '### ', 원문이 강조한 구절만 '**굵게**', "
    "인용 블록은 '> '. 원문에 없는 장식은 새로 만들지 않는다.\n"
    "- title_ko 는 원문 제목에 등장하는 선수 · 감독 이름을 최소 하나는 그대로 남긴다. "
    "여러 명이면 기사 핵심 인물을 우선한다.\n"
    "- 고유명사는 통용 한글 표기(Arsenal=아스날).\n"
    "- players: 이 기사에서 아스날의 이적 · 거취 · 계약과 관련해 다뤄진 선수 · 감독 "
    "목록. 각 항목은 "
    '{{"full_name":"영문 풀네임","ko":"이 기사에서 쓴 한글 표기","stage":"단계",'
    '"role":"subject 또는 mention"}}.\n'
    + PLAYERS_CLAUSE + ROSTER_CLAUSE +
    'ONLY JSON: {{"title_ko":"...","summary_ko":"...","summary3_ko":["...","...","..."],'
    '"body_ko":"...","players":[{{"full_name":"...","ko":"...","stage":"...","role":"..."}}]}}'
    "\n\nTitle: {title}\nBody: {body}")

PARAPHRASE_PROMPT = (
    "다음은 한국어로 옮겨진 아스날 FC 축구 기사다. 두 단계로 다시 쓴다.\n"
    "1단계 — 원문에서 사실 단위를 모두 뽑는다: 누가 · 무엇을 · 얼마에 · 언제 · "
    "어느 구단과 · 어떤 상태인지. 평가와 전망도 원문이 말한 것이면 사실 단위다.\n"
    "2단계 — 그 목록만 재료로 삼아 글을 새로 구성하고 표현을 전부 바꾼다. "
    "원문 문장을 하나씩 문장 단위로 대응해 옮기지 않는다. "
    "쓰다가 목록에 없는 내용이 나오면 그 문장을 버린다.\n"
    "규칙:\n"
    "- title_ko: 제목을 간결한 기사 제목체로 다시 쓴다 (말머리 대괄호 제거).\n"
    "- summary_ko: 한 문장 요약, 평어체.\n"
    "- summary3_ko: 핵심 3문장 배열, 평어체.\n"
    "- summary_ko·summary3_ko 존댓말 금지: '확정했습니다' ❌ → '확정했다' ⭕.\n"
    "- body_ko: 사실 단위를 하나도 빠뜨리지 않고 전부 담는다. 요약이 아니다. "
    "2~4문장 단위 문단으로 나누고 문단 사이는 줄바꿈 문자(\\n)로 구분한다.\n"
    "- body_ko 지문은 신문 평어체(종결어미 '~다'): '관심을 갖고 있습니다' ❌ → "
    "'관심을 갖고 있다' ⭕.\n"
    "- 인용문(따옴표 안 발화)은 재작성 대상이 아니다. 큰따옴표를 포함해 원문 "
    "글자 그대로 옮긴다. 줄이거나 다듬지 않는다.\n"
    "- 사실 · 수치 · 고유명사 · 평가 · 인과를 새로 만들지 않는다. 원문에 없는 "
    "구단명 · 사람 이름 · 숫자를 쓰면 안 된다.\n"
    "- 원문에 나오는 모든 숫자 (금액 · 나이 · 연도 · 경기 수 · 기록) 를 하나도 "
    "빠뜨리지 않는다.\n"
    "- 숫자는 원문 표기를 그대로 쓴다 (£50m 을 5,000만 파운드로 바꾸지 않는다).\n"
    "- 원문에 없는 수식어 · 부사 · 역할 명칭 (미드필더 · 공격수 · 감독 등) 을 "
    "붙이지 않는다.\n"
    "- 원문에 없는 시간 · 정도 표현 (즉시 · 이미 · 크게 · 확고히 · 전격 등) 을 "
    "넣지 않는다.\n"
    "- 원문이 단정한 것을 추측으로, 추측한 것을 단정으로 바꾸지 않는다.\n"
    "- 구독·앱 설치·댓글 유도, SNS 팔로우 요청, 팟캐스트·뉴스레터 홍보 등 "
    "기사 내용과 무관한 문구는 body_ko에서 제외.\n"
    "- body_ko 경량 마크다운: 원문의 소제목은 '### ', 원문이 강조한 구절만 "
    "'**굵게**', 인용 블록은 '> '. 원문에 없는 소제목을 만들지 않는다. "
    "원문에 없는 장식도 새로 만들지 않는다.\n"
    "- players: 이 기사에서 아스날의 이적 · 거취 · 계약과 관련해 다뤄진 선수 · 감독 "
    "목록. 각 항목은 "
    '{{"full_name":"영문 풀네임","ko":"이 기사에서 쓴 한글 표기","stage":"단계",'
    '"role":"subject 또는 mention"}}.\n'
    + PLAYERS_CLAUSE + ROSTER_CLAUSE +
    'ONLY JSON: {{"title_ko":"...","summary_ko":"...","summary3_ko":["...","...","..."],'
    '"body_ko":"...","players":[{{"full_name":"...","ko":"...","stage":"...","role":"..."}}]}}'
    "\n\nTitle: {title}\nBody: {body}")

# 재추출 · 백필 경로 전용 — 번역 없이 players 필드만 뽑는다.
EXTRACT_PLAYERS_PROMPT = (
    "다음 아스날 FC 관련 기사에서 아스날의 이적 · 거취 · 계약과 관련해 "
    "다뤄진 선수 · 감독을 추출한다.\n"
    '각 항목은 {{"full_name":"영문 풀네임","ko":"이 기사에서 쓴 한글 표기",'
    '"stage":"단계","role":"subject 또는 mention"}}.\n'
    + PLAYERS_CLAUSE + ROSTER_CLAUSE +
    'ONLY JSON: {{"players":[...]}}'
    "\n\nTitle: {title}\nBody: {body}")

def apply_glossary(parsed: dict, mapping: dict[str, str]) -> dict:
    """번역 결과의 한국어 필드에 통용 표기 사전 (오표기 → 통용) 을 치환 적용한다."""
    if not mapping:
        return parsed
    out = dict(parsed)
    for k, v in out.items():
        if isinstance(v, str):
            for wrong, right in mapping.items():
                v = v.replace(wrong, right)
            out[k] = v
    return out

def _fold_latin(text: str) -> str:
    """casefold + 결합 분음부호 제거 (Gyökeres → gyokeres). NFD 미분해 문자만 수동 치환."""
    import unicodedata
    folded = unicodedata.normalize("NFD", text.casefold())
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return folded.replace("ø", "o").replace("æ", "ae").replace("ß", "ss")

def _strip_marks(text: str) -> str:
    """결합 분음부호만 제거하고 대소문자는 보존 (Guimarães → Guimaraes).
    _fold_latin 은 casefold 까지 하므로 '성 앞 단어가 대문자인가' 판정에 쓸 수 없다."""
    import unicodedata
    out = unicodedata.normalize("NFD", text)
    out = "".join(ch for ch in out if not unicodedata.combining(ch))
    return (out.replace("ø", "o").replace("Ø", "O")
               .replace("æ", "ae").replace("Æ", "AE").replace("ß", "ss"))

# 성 앞 대문자 단어가 이름이 아니라 문장 첫머리 기능어인 경우를 걸러낸다
# (With Arteta's Backing… 의 With). 목록은 영어 기능어뿐 아니라 deal · news · report ·
# latest · official · exclusive · breaking 같은 헤드라인 상용어도 섞여 있어, 기능어 사전과
# 달리 앞으로 늘어날 수 있다. 목록을 바꾸면 스펙 4.3절 실측치 (라이브 412행 기준 검사 면제
# 4건 · 3%) 를 다시 재야 한다 — 바꾸기 전에 그 재측정을 감안할 것.
_NAME_CONTEXT_STOPWORDS = frozenset({
    "a", "after", "an", "and", "as", "at", "before", "breaking", "but", "by",
    "can", "could", "deal", "exclusive", "for", "from", "had", "has", "have",
    "he", "her", "his", "how", "if", "in", "is", "it", "its", "latest", "new",
    "news", "not", "now", "of", "official", "on", "over", "report", "she",
    "that", "the", "their", "they", "this", "to", "under", "was", "we", "were",
    "what", "when", "where", "who", "why", "will", "with", "would", "you",
})

def _has_name_context(source: str, surname: str) -> bool:
    """원문에 '이름 + 성' 형태가 있는지 — 성 단독 출현을 인명 근거로 인정하지 않는다.
    앞 단어가 기능어면 근거로 치지 않는다 (With Arteta's Backing… 오탐 차단).
    실측 (2026-07-30 · 라이브 412행): 제목에 등재 성이 나온 132건 중 128건이 이 근거를 가지고,
    근거가 없는 4건 중 2건이 확인된 오탐이다 (스펙 4.3절).
    name_map 값이 단일 단어 성이라는 전제의 패턴이다 (2026-07-31 현재 39개 전부 충족)
    — 두 단어 값 (Van Dijk 류) 은 대소문자 보존 매칭이 근거를 못 찾아 축이 조용히 꺼진다."""
    marked = _strip_marks(source)
    pat = rf"\b([A-Z][a-z]+)[\s-]+{re.escape(_strip_marks(surname))}\b"
    return any(m.group(1).lower() not in _NAME_CONTEXT_STOPWORDS
               for m in re.finditer(pat, marked))

_LOAN_RE = re.compile(r"\bloan", re.IGNORECASE)
# 사유 접두어 — 호출측이 축별로 걸러낼 때 쓴다 (문자열을 옮겨 적으면 조용히 어긋난다).
NAME_MISSING_PREFIX = "인명 누락:"

def detect_title_mistranslation(title_ko: str | None, title_original: str | None,
                                name_map: dict[str, str],
                                source_text: str = "") -> list[str]:
    """원문 제목 대비 번역 제목의 결정적 불일치 사유 목록 (환각 검출기의 역방향 축).
    ①원문 제목의 등재 인명 (단어 경계) 이 번역 제목에 **전부** 누락
    — '조르제' (Tzolis) 창작 · 무관 제목 전면 환각 실사례를 잡는다.
    일부만 유지된 경우는 다절 제목 (트윗 · 리스트클) 의 정당한 축약이라 통과.
    ②'임대' 가 원문 근거 (loan · 한국어 원문의 임대) 없이 생성 — permanent 반전 실사례.
    성 단독 출현은 인명으로 세지 않는다 — 원문 (제목 + source_text) 에 '이름 + 성' 형태가
    있어야 인정한다 (white flag 관용구 · With Arteta's Backing 프레이밍 오탐 차단).
    라운드업 (제목 재초점이 정상) 은 호출측에서 제외한다."""
    if not title_ko or not title_original:
        return []
    reasons = []
    folded = _fold_latin(title_original)
    context = f"{title_original} {source_text}"
    missing, present = [], 0
    for en in dict.fromkeys(name_map.values()):
        if re.search(rf"\b{re.escape(_fold_latin(en))}\b", folded):
            if not _has_name_context(context, en):
                continue
            if any(ko in title_ko for ko, v in name_map.items() if v == en):
                present += 1
            else:
                missing.append(f"{NAME_MISSING_PREFIX}{en}")
    if missing and present == 0:
        reasons.extend(missing)
    if "임대" in title_ko and "임대" not in title_original \
            and not _LOAN_RE.search(title_original):
        reasons.append("임대 무근거")
    return reasons

# BBC 가십 라운드업의 단신별 출처 링크 표지 — 실측 두 형태 (2026-07-20):
# "(출처) , external" 과 "( 출처 , external )" (', external' 이 괄호 안).
# 일반 괄호 (£50.9m) 는 external 이 없어 구분된다.
_ATTRIB_RE = re.compile(
    r"\(\s*([^()]{2,60}?)\s*(?:,\s*external\s*\)|\)\s*,\s*external)")

def attrib_core(label: str) -> str:
    """출처 표지에서 부가 (" - in Italian" · ", in French" · " via …") 를 떼고 출처명만 남긴다."""
    return re.split(r"\s+-\s+|,\s+|\s+via\s+", label)[0].strip()

def roundup_attrib_counts(body_source: str | None) -> dict[str, int]:
    """라운드업 원문의 '(출처) , external' 표지를 출처명 (core) 등장 횟수로 집계.
    표지 없는 일반 기사는 빈 dict — 누락 게이트 · 서빙 항목화가 같은 집합을 공유한다."""
    counts: dict[str, int] = {}
    for m in _ATTRIB_RE.finditer(body_source or ""):
        core = attrib_core(m.group(1))
        if core:
            counts[core] = counts.get(core, 0) + 1
    return counts

def detect_roundup_omission(body_source: str | None,
                            body_ko: str | None) -> list[str]:
    """라운드업 원문의 괄호 출처가 번역문에 빠졌으면 누락 출처 목록 반환.
    출처 병기 = 단신 1건의 표지이므로 누락 출처 = 누락 단신의 결정적 신호.
    같은 출처 단신 복수 건은 등장 횟수로 대조한다."""
    if not body_source:
        return []
    ko = body_ko or ""
    return [core for core, n in roundup_attrib_counts(body_source).items()
            if ko.count(core) < n]

def detect_title_hallucination(title_ko: str | None, source_text: str,
                               name_map: dict[str, str]) -> list[str]:
    """번역 제목의 인명이 원문 (제목 + 본문) 에 근거 없으면 의심 목록 반환.
    사전 (한글 표기 → 영문 성) 기반 결정적 대조 — 사전 밖 인명은 미검출 (점진 확장).
    한국어 원문 (paraphrase 경로) 은 한글 표기 포함 여부로 같은 함수가 판정한다."""
    if not title_ko or not name_map:
        return []
    folded_src = _fold_latin(source_text or "")
    suspects = []
    for ko, en in name_map.items():
        if ko in title_ko and ko not in (source_text or "") \
                and _fold_latin(en) not in folded_src:
            suspects.append(ko)
    return suspects

def _ko_present(text: str, name: str) -> bool:
    """한글 표기 존재 판정 — 직전 문자가 한글 음절이면 불인정 ("리즈" ⊄ "시리즈").
    직후 문자는 조사 결합 ("리즈가") 이 정상이라 판정에 쓰지 않는다."""
    start = text.find(name)
    while start != -1:
        if start == 0 or not ("가" <= text[start - 1] <= "힣"):
            return True
        start = text.find(name, start + 1)
    return False

_GATE_FIELDS = ("title_ko", "summary_ko", "summary3_ko", "body_ko")

def detect_club_injection(parsed: dict, source_text: str,
                          club_map: dict[str, list[str]]) -> list[str]:
    """번역 산출물 4필드에 등장한 구단명이 원문에 근거 없으면 의심 목록 반환 (게이트 4축).
    이중 대조 — 원문의 한글 표기 (ko 경로 · fmkorea) or 영문 별칭 단어 경계 (en 경로) 중
    하나라도 있으면 근거 인정. 사전 밖 구단은 미검출 (name_map 과 같은 점진 확장).
    실사례: 로저스의 전 소속 (미들즈브러) 학습 지식 주입 — 원문은 Aston Villa 명시."""
    if not club_map:
        return []
    joined = " ".join(filter(None, (parsed.get(k) for k in _GATE_FIELDS)))
    if not joined:
        return []
    src = source_text or ""
    folded_src = _fold_latin(src)
    # 동일 별칭 목록 = 같은 구단의 복수 한글 표기 (맨유 · 맨체스터 유나이티드) — 근거를 상호 인정
    # (ko 경로 패러프레이즈의 동의어 축약 오탐 방지, 최종 리뷰 반영)
    synonyms: dict[frozenset, list[str]] = {}
    for k, al in club_map.items():
        synonyms.setdefault(frozenset(al), []).append(k)
    suspects = []
    for ko, aliases in club_map.items():
        if not _ko_present(joined, ko):
            continue
        if any(_ko_present(src, k2) for k2 in synonyms[frozenset(aliases)]):
            continue
        if any(re.search(rf"\b{re.escape(_fold_latin(a))}\b", folded_src)
               for a in aliases):
            continue
        suspects.append(ko)
    return suspects

def detect_name_injection(parsed: dict, source_text: str,
                          name_map: dict[str, str]) -> list[str]:
    """산출물 4필드의 등재 인명이 원문에 근거 없으면 의심 목록 반환 (게이트 4축).

    detect_title_hallucination 과 같은 이중 대조 (한글 표기 or 영문 성) 를
    제목이 아니라 4필드 전체에 적용한다 — 본문에만 주입된 인명을 잡는다.
    사전 밖 인명은 미검출이다 (구단 축과 같은 점진 확장)."""
    if not name_map:
        return []
    joined = " ".join(filter(None, (parsed.get(k) for k in _GATE_FIELDS)))
    if not joined:
        return []
    src = source_text or ""
    folded_src = _fold_latin(src)
    suspects = []
    for ko, en in name_map.items():
        if not _ko_present(joined, ko):
            continue
        if _ko_present(src, ko):
            continue
        if re.search(rf"\b{re.escape(_fold_latin(en))}\b", folded_src):
            continue
        suspects.append(ko)
    return suspects

# 문장 종결 (마침표류 + 닫는 따옴표) 뒤가 공백 · 블록 끝일 때만 경계 — 소수점 (2.5) 오분할 방지
_SENT_END_RE = re.compile(r'[.!?…]["”\'』」]?(?=\s|$)')

def _split_sentences(block: str) -> list[str]:
    out, start = [], 0
    for m in _SENT_END_RE.finditer(block):
        out.append(block[start:m.end()].strip())
        start = m.end()
    tail = block[start:].strip()
    if tail:
        out.append(tail)
    return [s for s in out if s]

def paragraphize(text: str | None, max_len: int = 400) -> str | None:
    """max_len 초과 무분할 블록을 문장 경계에서 재분할한다.
    프롬프트의 문단화 지시 (2~4문장 단위) 를 LLM 이 간헐 미준수하는 것의 결정적 보정.
    마크다운 블록 ('### ' · '> ') 과 문장 경계 없는 블록은 건드리지 않는다."""
    if not text:
        return text
    blocks_out: list[str] = []
    for block in text.split("\n"):
        if len(block) <= max_len or block.lstrip().startswith(("### ", "> ")):
            blocks_out.append(block)
            continue
        sents = _split_sentences(block)
        if len(sents) <= 1:
            blocks_out.append(block)
            continue
        chunk, chunks = "", []
        for s in sents:
            cand = f"{chunk} {s}" if chunk else s
            if chunk and len(cand) > max_len:
                chunks.append(chunk)
                chunk = s
            else:
                chunk = cand
        if chunk:
            chunks.append(chunk)
        blocks_out.extend(chunks)
    return "\n".join(blocks_out)

# 트윗은 별도 제목이 없어 title_original 에 본문 전문이 들어간다
# (2026-07-22 실측 평균 211자 · 기사 제목은 39~83자).
# 그래서 '원문 제목의 인명이 번역 제목에 남았는가' 축은 본문 대 제목 비교가 되어 구조적으로 오탐한다
# — 여섯 명이 나오는 트윗에서 제목이 한둘만 담는 것은 정상이다.
# 라운드업 (bbc_gossip) 을 축 전체에서 뺀 것과 같은 이유지만, 트윗은 '임대 무근거' 축이
# 그대로 유효하므로 축을 끄지 않고 인명 누락 사유만 걸러낸다.
# x_ornstein 도 같은 트윗 구조 (제목 = 본문 전문) 라 동일 예외 대상.
BODY_AS_TITLE_SOURCES = {"x_afcstuff", "x_ornstein"}

def finalize_translation(v: dict, row: dict, glossary: dict[str, str],
                         name_map: dict[str, str],
                         club_map: dict[str, list[str]]
                         ) -> tuple[str | None, str, str, str | None, list[str]]:
    """번역 결과에 표기 사전 · 환각 게이트 4축 · 문단 보정을 적용해
    set_translation 인자 4필드 + 재시도 잔존 의심 사유 목록 (flagged) 을 만든다.
    row 는 rows_missing_translation 의 원본 행.
    회차 경로 (run.py) 와 enrich 전용 백필 패스가 같은 규칙을 쓰도록 여기 한 벌만 둔다
    — 런북 스니펫에 옮겨 적으면 게이트 · 문단 보정이 빠진 채 백필이 돈다."""
    v = apply_glossary(v, glossary)
    h = row.get("content_hash")
    src_text = " ".join(filter(None, [row.get("title_original"),
                                      row.get("body_source"),
                                      row.get("body_excerpt")]))
    # 제목 환각 검출 (설계 ②-A): 1차 검출 = 재번역 큐 (title NULL 저장 → 다음
    # 사이클 재선별), 재검출 (summary_ko 기저장 = 재시도 행) = 번역 제목 채택 + 경고 (설계 5.2).
    suspects = detect_title_hallucination(v["title_ko"], src_text, name_map)
    # 역방향 축: 원문 제목 인명 누락 · 무근거 '임대' — 라운드업 (gossip) 은 제목 재초점이 정상이라 제외
    if row.get("source_id") != "bbc_gossip":
        reasons = detect_title_mistranslation(
            v["title_ko"], row.get("title_original"), name_map, src_text)
        if row.get("source_id") in BODY_AS_TITLE_SOURCES:
            reasons = [r for r in reasons if not r.startswith(NAME_MISSING_PREFIX)]
        suspects = suspects + reasons
    # 라운드업 단신 누락 게이트: 원문 괄호 출처 vs 번역 병기 대조 (환각 큐와 같은 재시도 1회)
    omissions = detect_roundup_omission(row.get("body_source"), v["body_ko"])
    # 원문에 없는 구단명 게이트 (4축): 번역 4필드 × 원문 이중 대조 — 인명 suspects 와 분리
    # (합치면 body 만 오염된 케이스에 불필요한 원문 제목 폴백이 걸린다)
    club_suspects = detect_club_injection(v, src_text, club_map)
    title_ko = v["title_ko"]
    flagged: list[str] = []
    retry = bool(row.get("summary_ko"))
    if suspects and retry:
        # 종착 상태 (설계 5.2): 재시도 1회로 끝내고 번역 제목을 채택 + 경고.
        # NULL 재큐는 게이트가 충족 불가능한 요구를 하면 회차마다 무한 반복됐다
        # (white flag 관용구를 벤 화이트로 오인 · 2026-07-30 실측 하루 8회).
        flagged = suspects
        log.warning("제목 의심 잔존 — 수동 확인 content_hash=%s 의심=%s", h, suspects)
    elif (suspects or omissions or club_suspects) and not retry:
        log.warning(
            "재번역 큐(1차) content_hash=%s 환각의심=%s 단신누락=%s 원문에 없는 구단명=%s",
            h, suspects, omissions, club_suspects)
        title_ko = None
    elif retry and not suspects:
        log.info("제목 해소 content_hash=%s title_ko=%s", h, title_ko)
    if omissions and retry:
        log.warning(
            "라운드업 단신 누락 잔존 — 수동 확인 content_hash=%s 누락=%s", h, omissions)
    if club_suspects and retry:
        log.warning(
            "원문에 없는 구단명 잔존 — 수동 확인 content_hash=%s 구단=%s", h, club_suspects)
    return (title_ko, v["summary_ko"], v["summary3_ko"],
            paragraphize(v["body_ko"]), flagged)

def retranslation_summary(finals: dict[str, tuple], by_hash: dict[str, dict]
                          ) -> tuple[int, int, int]:
    """finalize_translation 결과로 재번역 큐 추이를 집계 → (신규, 채택, 해소).

    신규 = 신규 행 (summary_ko 없음) 이 NULL 로 큐 진입,
    채택 = 재시도 행이 의심을 남긴 채 제목을 확정 (운영자 수동 확인 대상),
    해소 = 재시도 행이 의심 없이 제목 확보.
    정상 신규 성공 (NULL 아님 · 재시도 아님) 은 집계 밖.
    채택 · 해소 판정은 제목 축 (flagged) 만 본다 — 구단명 · 단신 누락 축의 잔존은
    행별 '수동 확인' 경고로만 관측되고 여기서는 해소로 잡힌다.
    관측 ② — 호출측 (run.py) 이 사이클 요약 한 줄로 로깅한다."""
    new_q = adopted = resolved = 0
    for h, final in finals.items():
        title_ko, flagged = final[0], final[4]
        retry = bool(by_hash.get(h, {}).get("summary_ko"))
        if title_ko is None and not retry:
            new_q += 1
        elif retry and flagged:
            adopted += 1
        elif retry and title_ko is not None:
            resolved += 1
    return new_q, adopted, resolved

def _extract_full(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
        s3 = d["summary3_ko"]
        s3 = "\n".join(s3) if isinstance(s3, list) else str(s3)
        pairs = d.get("players")
        return {"title_ko": d["title_ko"], "summary_ko": d["summary_ko"],
                "summary3_ko": s3, "body_ko": d["body_ko"],
                "players": pairs if isinstance(pairs, list) else []}
    except (json.JSONDecodeError, KeyError, TypeError):
        return None

POST_BODY_LEVEL = 1     # 게시글 본문 — 커뮤니티가 옮긴 것 (수집 라인 트랙 계약)

def partition_by_body_level(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """(재작성 행, 번역 행) — 본문 출처 등급으로 가른다.

    등급 1 은 이미 한국어라 번역이 아니라 재작성 대상이다.
    매체명 문자열로 가르면 표기 변종마다 갈린다 (배포판에 '더 선' · '더선' · '더썬'
    이 따로 존재한다 — 스펙 §4.2). 등급이 없는 레거시 행은 번역 쪽으로 보낸다."""
    rewrite, trans = [], []
    for r in rows:
        (rewrite if r.get("body_level") == POST_BODY_LEVEL else trans).append(r)
    return rewrite, trans

def extract_players_rows(rows: list[dict], client, model: str,
                         roster: str = "(없음)") -> dict[str, list]:
    """백필 · 재추출 전용 (선수, 단계) 쌍 추출 — 번역 없이 players 필드만 (스펙 §7).
    재료는 body_source → body_excerpt → body_ko 폴백 (재추출 스펙 §3.2) — 트윗처럼
    원문 본문이 빈 행은 번역 본문이라도 줘야 제목 한 줄 추출 (세계 지식 오염) 을 막는다.
    roster 는 확정 링크 명단 문자열 ("한글이름(영문)" 나열) — 아스날 미언급 기사의
    근거 재료 (프롬프트 주석 참조). 429 는 그 회차 즉시 중단, 파싱 실패는 행 스킵
    (기존 enrich 루프와 동일 규칙)."""
    result: dict[str, list] = {}
    for r in rows:
        h = r["content_hash"]
        try:
            msg = client.models.generate_content(
                model=model,
                contents=EXTRACT_PLAYERS_PROMPT.format(
                    title=r["title_original"],
                    body=r.get("body_source") or r.get("body_excerpt")
                         or r.get("body_ko") or "",
                    roster=roster),
                config={"max_output_tokens": 4096,
                        "response_mime_type": "application/json"})
        except Exception as e:
            if _is_rate_limit(e):
                log.warning("Gemini rate limit(429), 추출 중단 — 남은 행 재실행 시 이어짐")
                break
            log.warning("Gemini 호출 실패, 스킵 content_hash=%s: %s", h, e)
            continue
        m = re.search(r"\{.*\}", msg.text or "", re.DOTALL)
        try:
            pairs = json.loads(m.group(0))["players"] if m else None
        except (json.JSONDecodeError, KeyError, TypeError):
            pairs = None
        if not isinstance(pairs, list):
            log.warning("Gemini 응답 파싱 실패, 스킵 content_hash=%s", h)
            continue
        result[h] = pairs
    return result


def enrich_rows(rows: list[dict], client, model: str, mode: str = "translate",
                roster: str = "(없음)") -> dict[str, dict]:
    """번역 · 요약 · 추출 쌍 생성. roster 는 확정 링크 명단 문자열이며 아스날
    미언급 기사의 판단 근거로 프롬프트에 실린다 (스펙 §6.5)."""
    prompt = PARAPHRASE_PROMPT if mode == "paraphrase" else TRANSLATE_PROMPT
    result: dict[str, dict] = {}
    for r in rows:
        h = r["content_hash"]
        try:
            msg = client.models.generate_content(
                model=model,
                contents=prompt.format(title=r["title_original"],
                                       body=r.get("body_source") or r.get("body_excerpt") or "",
                                       roster=roster),
                config={"max_output_tokens": 8192,
                        "response_mime_type": "application/json"})
        except Exception as e:
            if _is_rate_limit(e):
                log.warning("Gemini rate limit(429), enrich 중단 — 남은 행 다음 사이클")
                break
            log.warning("Gemini 호출 실패, 스킵 content_hash=%s: %s", h, e)
            continue
        parsed = _extract_full(msg.text)
        if parsed is None:
            log.warning("Gemini 응답 파싱 실패, 스킵 content_hash=%s", h)
            continue
        result[h] = parsed
    return result

MISSING_RETRY = (
    "\n\n[누락] 직전 시도에서 다음 숫자가 누락됐다 — {tokens}.\n"
    "이 수치들을 원문 맥락 그대로 반드시 포함한다.")
DUPLICATE_RETRY = (
    "\n\n[복제] 직전 시도는 원문 표현을 지나치게 그대로 옮겼다.\n"
    "사실 · 수치 · 인용은 그대로 두되 문장 구성과 표현을 크게 바꿔 다시 쓴다.\n"
    "단 원문에 없는 내용 · 수식어 · 소제목을 새로 넣지 않는다.")
EXTRA_RETRY = (
    "\n\n[신규 수치] 직전 시도는 원문에 없는 숫자를 만들었다 — {tokens}.\n"
    "원문에 없는 수치는 쓰지 않는다.")
QUOTE_RETRY = (
    "\n\n[인용 훼손] 직전 시도는 원문 인용문을 바꿔 썼다 — {quotes}.\n"
    "따옴표 안 발화는 원문 그대로 옮긴다.")
CLUB_RETRY = (
    "\n\n[구단 주입] 직전 시도는 원문에 없는 구단을 넣었다 — {clubs}.\n"
    "원문에 나오지 않는 구단명은 쓰지 않는다.")
NAME_RETRY = (
    "\n\n[인명 주입] 직전 시도는 원문에 없는 인물을 넣었다 — {names}.\n"
    "원문에 나오지 않는 사람 이름은 쓰지 않는다.")

def rewrite_rows_guarded(rows: list[dict], client, model: str,
                         threshold: float = RETENTION_THRESHOLD,
                         max_attempts: int = 3,
                         name_map: dict[str, str] | None = None,
                         club_map: dict[str, list[str]] | None = None,
                         roster: str = "(없음)"
                         ) -> tuple[dict[str, dict], dict[str, dict]]:
    """게시글 본문 재작성 — 게이트 4축에 걸리면 사유를 붙여 재생성하고 최선을 채택한다.

    게이트는 재생성 트리거이지 폐기 조건이 아니다 (스펙 §4.4 · 사용자 확정 2026-08-03).
    네 축 = 구단 · 인명 · 수치 (누락 · 신규) · 인용 보존.
    반환: (결과, 리포트) — 리포트는 잔존율 · 축별 잔존 기록 · ops 노출용."""
    name_map, club_map = name_map or {}, club_map or {}
    results: dict[str, dict] = {}
    reports: dict[str, dict] = {}
    for r in rows:
        h = r["content_hash"]
        source = r.get("body_source") or r.get("body_excerpt") or ""
        # 주입 판정의 근거는 모델에게 준 재료 전부다 — 제목에만 있는 인명 · 수치를
        # 주입으로 오탐하지 않게 한다 (finalize_translation 과 같은 범위).
        grounding = " ".join(filter(None, (r.get("title_original"), source)))
        base = PARAPHRASE_PROMPT.format(title=r["title_original"], body=source,
                                        roster=roster)
        attempts: list[dict] = []
        rate_limited = False
        for i in range(max_attempts):
            note = ""
            if attempts:
                last = attempts[-1]
                if last["missing"]:
                    note += MISSING_RETRY.format(tokens=", ".join(last["missing"]))
                if last["extra"]:
                    note += EXTRA_RETRY.format(tokens=", ".join(last["extra"]))
                if last["quotes"]:
                    note += QUOTE_RETRY.format(quotes=" / ".join(last["quotes"]))
                if last["clubs"]:
                    note += CLUB_RETRY.format(clubs=", ".join(last["clubs"]))
                if last["names"]:
                    note += NAME_RETRY.format(names=", ".join(last["names"]))
                if last["retention"] > threshold:
                    note += DUPLICATE_RETRY
            try:
                msg = client.models.generate_content(
                    model=model, contents=base + note,
                    config={"max_output_tokens": 8192,
                            "response_mime_type": "application/json"})
            except Exception as e:
                if _is_rate_limit(e):
                    log.warning("Gemini rate limit(429), 재작성 중단 — 남은 행 다음 사이클")
                    rate_limited = True
                    break
                log.warning("Gemini 호출 실패, 스킵 content_hash=%s: %s", h, e)
                break
            parsed = _extract_full(msg.text)
            if parsed is None:
                log.warning("Gemini 응답 파싱 실패, 스킵 content_hash=%s", h)
                break
            v = gate_verdict(source, parsed["body_ko"] or "", threshold,
                             grounding=grounding)
            names = detect_name_injection(parsed, grounding, name_map)
            clubs = detect_club_injection(parsed, grounding, club_map)
            attempts.append({"parsed": parsed, "missing": v["missing"],
                             "extra": v["extra"], "quotes": v["quotes"],
                             "names": names, "clubs": clubs,
                             "retention": v["retention"]})
            if v["ok"] and not names and not clubs:
                break
        if rate_limited:
            break
        if not attempts:
            continue
        best = select_best(attempts, threshold)
        results[h] = best["parsed"]
        reports[h] = {"retention": best["retention"], "missing": best["missing"],
                      "extra": best["extra"], "quotes": best["quotes"],
                      "names": best["names"], "clubs": best["clubs"],
                      "attempts": len(attempts)}
        if (best["retention"] > threshold or best["missing"] or best["extra"]
                or best["quotes"] or best["names"] or best["clubs"]):
            log.warning("재작성 게이트 잔존 content_hash=%s 잔존율=%.3f 누락=%s "
                        "신규수치=%s 인용훼손=%s 인명=%s 구단=%s 시도=%d",
                        h, best["retention"], best["missing"], best["extra"],
                        best["quotes"], best["names"], best["clubs"], len(attempts))
    return results, reports

TITLE_ONLY_PROMPT = (
    "다음 축구 뉴스 제목을 한국어로 옮긴다. 규칙:\n"
    "- 한국 스포츠 기사 제목체로 간결하게 (명사형 위주).\n"
    "- 제목에 없는 내용을 덧붙이지 않는다.\n"
    "- 원문 제목의 선수 · 감독 이름을 최소 하나는 그대로 남긴다.\n"
    "- 고유명사는 통용 한글 표기(Arsenal=아스날).\n"
    'ONLY JSON: {{"title_ko":"..."}}'
    "\n\nTitle: {title}")


def partition_generatable(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """(생성 대상, 제목만 대상) — 재료가 없으면 본문 · 요약을 만들지 않는다.

    원인은 재료 없는 행에 완역을 지시한 것이다 — 번역할 원문이 없으니 모델이
    빈칸을 채워 넣었다 (스펙 §1). 트윗 소스는 title_original 에 전문이 있어
    재료가 갖춰져 있으므로 빠지지 않는다."""
    gen, title_only = [], []
    for r in rows:
        has_material = bool((r.get("body_source") or "").strip()
                            or (r.get("body_excerpt") or "").strip())
        if has_material or r.get("source_id") in BODY_AS_TITLE_SOURCES:
            gen.append(r)
        else:
            title_only.append(r)
    return gen, title_only


def title_only_rows(rows: list[dict], client, model: str) -> dict[str, dict]:
    """제목만 생성 — 본문 · 요약 필드는 None 으로 둔다.
    행을 아예 건너뛰면 title_ko 가 NULL 로 남아 매 회차 재선별되고 '번역 대기'
    배지가 영구히 붙는다."""
    out: dict[str, dict] = {}
    for r in rows:
        h = r["content_hash"]
        try:
            msg = client.models.generate_content(
                model=model,
                contents=TITLE_ONLY_PROMPT.format(title=r["title_original"]),
                config={"max_output_tokens": 512,
                        "response_mime_type": "application/json"})
        except Exception as e:
            if _is_rate_limit(e):
                log.warning("Gemini rate limit(429), 제목 생성 중단 — 남은 행 다음 사이클")
                break
            log.warning("Gemini 호출 실패, 스킵 content_hash=%s: %s", h, e)
            continue
        m = re.search(r"\{.*\}", msg.text, re.DOTALL)
        try:
            title_ko = json.loads(m.group(0))["title_ko"] if m else None
        except (json.JSONDecodeError, KeyError, TypeError):
            title_ko = None
        if not title_ko:
            log.warning("제목 생성 파싱 실패, 스킵 content_hash=%s", h)
            continue
        out[h] = {"title_ko": title_ko, "summary_ko": None,
                  "summary3_ko": None, "body_ko": None}
    return out


def partition_translation_rows(rows: list[dict], sources: dict[str, dict]
                               ) -> tuple[list[dict], list[dict]]:
    """소스 lang 기준으로 (ko_rows, en_rows) 로 분리. lang 미지정은 en 취급."""
    ko, en = [], []
    for r in rows:
        lang = sources.get(r.get("source_id"), {}).get("lang", "en")
        (ko if lang == "ko" else en).append(r)
    return ko, en

def _extract_summary(text: str) -> str | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))["summary_ko"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None

def summarize_ko_rows(rows: list[dict], client, model: str) -> dict[str, str]:
    """한국어 행을 번역 없이 한국어 한 줄 요약만 생성. content_hash -> summary_ko.
    한 행이 실패해도 배치 전체를 중단하지 않는다 (run 측에서 본문 발췌로 폴백)."""
    result: dict[str, str] = {}
    for r in rows:
        h = r["content_hash"]
        try:
            msg = client.models.generate_content(
                model=model,
                contents=SUMMARY_PROMPT.format(title=r["title_original"],
                                               body=r.get("body_excerpt") or ""),
                config={"max_output_tokens": 200,
                        "response_mime_type": "application/json"})
        except Exception as e:
            if _is_rate_limit(e):
                log.warning("Gemini rate limit(429), 요약 중단 — 남은 행은 다음 사이클 누적")
                break
            log.warning("Gemini 호출 실패, 요약 스킵 content_hash=%s: %s", h, e)
            continue
        s = _extract_summary(msg.text)
        if s is None:
            log.warning("Gemini 응답 파싱 실패, 요약 스킵 content_hash=%s", h)
            continue
        result[h] = s
    return result

def _extract_resummary(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
        s = d["summary_ko"]
        if not isinstance(s, str) or not s.strip():
            return None  # 빈/비문자열 요약이 기존 값을 덮어쓰지 않게 스킵
        s3 = d["summary3_ko"]
        s3 = "\n".join(s3) if isinstance(s3, list) else str(s3)
        return {"summary_ko": s, "summary3_ko": s3}
    except (json.JSONDecodeError, KeyError, TypeError):
        return None

def resummarize_rows(rows: list[dict], client, model: str) -> dict[str, dict]:
    """말투 백필: 저장된 한국어 본문에서 요약만 재생성한다.
    content_hash -> {summary_ko, summary3_ko}. 429는 그 회차 즉시 중단,
    파싱 실패는 행 단위 스킵 (다음 사이클에 검출 기반으로 재선별)."""
    result: dict[str, dict] = {}
    for r in rows:
        h = r["content_hash"]
        try:
            msg = client.models.generate_content(
                model=model,
                contents=RESUMMARY_PROMPT.format(
                    title=r.get("title_ko") or r["title_original"],
                    body=r.get("body_ko") or r.get("body_excerpt") or ""),
                config={"max_output_tokens": 1024,
                        "response_mime_type": "application/json"})
        except Exception as e:
            if _is_rate_limit(e):
                log.warning("Gemini rate limit(429), 말투 백필 중단 — 남은 행 다음 사이클")
                break
            log.warning("Gemini 호출 실패, 말투 백필 스킵 content_hash=%s: %s", h, e)
            continue
        parsed = _extract_resummary(msg.text)
        if parsed is None:
            log.warning("Gemini 응답 파싱 실패, 말투 백필 스킵 content_hash=%s", h)
            continue
        result[h] = parsed
    return result

# 주의: 아래 단계 목록(rumour·interest·negotiating·personal_terms·medical·agreed·done·
# collapsed·other)은 transfer_stage.VALID_STAGES와 동기화되어야 한다. 새 단계를 추가하면
# 이 프롬프트도 업데이트해야 하며,
# tests/test_enrich.py::test_stage_prompt_lists_llm_stages_and_excludes_official()에서
# 불일치를 검출한다.
# 문안 정본은 스펙 2026-08-10-article-stage-redefinition-design.md §4 — dry-run 채택판
# (v1c · specs/assets/2026-08-10-stage-dryrun/) 원문 그대로다. 경계 문구를 고칠 때는
# 소표본 재검증을 거친다 (시소 함정: troubleshooting 2026-08-08).
# {club} 은 멀티 클럽 확장 대비 파라미터 (스펙 §9) · {roster} 는 완료 명단 재료 자리
# (이번 개정에서는 미주입 — dry-run v2 기각 · 명단 갱신 뒤 재평가).
STAGE_PROMPT = (
    "다음은 {club} 관련 기사 목록이다. 각 기사를 이적 진행 단계로 분류한다.\n"
    "단계 (반드시 아래 영문 값 중 하나로 답한다):\n"
    "- rumour: 근거 약한 소문 · 연결설\n"
    "- interest: 구단이 실제 관심 표명 · 스카우팅 · 후보 검토\n"
    "- negotiating: 이적료·조건 협상 중 · 제안 · 거절, 그리고 합의 임박·근접·눈앞·마무리 단계 보도 "
    "(기사가 합의 도달을 사실로 전하지 않는 한 여기다)\n"
    "- personal_terms: 선수와 구단이 개인 조건 (연봉·계약 기간) 을 합의 "
    "(구두 합의라도 당사자가 선수-구단이면 여기). 조건 제시 준비·계획·근접은 합의가 아니다 — "
    "negotiating 또는 interest 로 답한다\n"
    "- medical: 메디컬 테스트 진행 · 통과\n"
    "- agreed: 구단 간 완전 합의 도달 · 딜 확정을 사실로 보도 (구두 합의 · 원칙적 합의 · "
    "here we go 류 · 체결 합의를 새 소식으로 전하는 기사). 임박·근접 보도는 agreed 가 아니라 negotiating 이다\n"
    "- done: 이미 완료된 이적의 후속 · 부대 보도 — 계약 체결 완료 · 등번호 배정 · 입단 소감 · "
    "완료된 이적의 회고 · 해설 · 손익 분석. 완료 명단 참고: {roster}. "
    "명단은 보조 근거다 — 기사가 협상·합의의 진행을 새 소식으로 전하면 그 진행 단계로 답한다\n"
    "- collapsed: {club} 관련 딜의 종결 — 영입 대상의 잔류 확정 · 현 소속 구단과의 재계약 체결 · "
    "협상 결렬 확정 · 경쟁 구단의 영입 확정, 즉 {club} 의 실패·무산이 기사의 주된 내용일 때. "
    "타 구단 간 딜의 무산·결렬은 그 딜이 도달했던 마지막 단계로 답한다. "
    "진행 중인 잔류·재계약 협상은 collapsed 가 아니다. 상대 구단이 협상·매각을 거부한다는 "
    "방침 보도도 종결이 아니다 — 그 딜의 진행 단계 (interest·negotiating) 로 답한다\n"
    "- other: 이적과 무관하거나 단계를 판단할 수 없음\n"
    "방향 (direction — 반드시 아래 영문 값 중 하나로 답한다):\n"
    "- in: {club} 로 오는 이적 (임대 영입 포함)\n"
    "- out: {club} 에서 나가는 이적 (방출 · 매각 · 임대 방출 포함)\n"
    "- none: 이적 무관 기사 · 방향을 판단할 수 없음\n"
    "방향은 {club} 기준이다 — {club} 이 이적의 당사자 (사는 쪽 또는 파는 쪽) 가 아니면 반드시 none 으로 답한다.\n"
    "{club} 이 관심을 가졌거나 경쟁에서 밀린 딜도 none 이다 — 예: {club} 이 노리던 선수를 다른 구단이 "
    "영입하면 none, 이미 {club} 을 떠난 선수의 새 소속 이적도 none.\n"
    "이때 단계는 규칙대로 그대로 매긴다 — 방향만 none 이고 단계는 그대로다.\n"
    "방향은 제목이 내세우는 주된 이적 하나로 정한다 — 요약 말미의 부수 언급은 무시한다.\n"
    "제목이 영입과 방출을 병기하는 대등 혼합이면 out 으로 답한다.\n"
    "{club} 이 노리던 선수를 경쟁 구단이 영입 확정한 기사 (하이재킹 완결) 는 collapsed 로 답하고, "
    "이때만 예외로 방향을 {club} 이 시도했던 축 (영입 경쟁이었으면 in) 으로 답한다.\n"
    "합의 보도는 당사자로 가른다 — 구단과 구단이면 agreed, 선수와 구단이면 personal_terms.\n"
    "이적 주체가 {club} 이 아니어도 (타 구단 간 이적) 그 이적의 단계로 분류한다.\n"
    "other 는 이적과 정말 무관한 글에만 쓴다 — 아래는 모두 이적 기사이므로 단계를 매긴다.\n"
    "- 타 구단 간 딜의 무산 · 결렬 · 포기 · 이적설 부인: 그 연결이 도달했던 마지막 단계로 분류하고, "
    "도달 단계를 알 수 없으면 rumour\n"
    "- 몸값 · 이적료 책정 보도: 구단이 영입 의사를 보인 상태면 interest, 그렇지 않으면 rumour\n"
    "- 이적 건에서 파생된 분쟁 · 법적 절차: 그 이적 건의 마지막 알려진 단계\n"
    "- 대안 후보군 · 연쇄 반응: 특정 선수를 후보로 검토한다는 보도면 interest\n"
    "여러 이적을 한 글에 모은 시장 라운드업 · 총평 · 칼럼은 대표 단계가 성립하지 않으므로 other 로 둔다.\n"
    "아래는 선수 이적이 아니므로 단계를 매기지 말고 other 로 둔다.\n"
    "- 스폰서십 · 유니폼 · 중계권 같은 상업 계약\n"
    "- 소속 구단과의 재계약 · 계약 연장 ({club} 과 무관한 구단의 경우 — {club} 영입 대상의 잔류 · "
    "재계약 체결은 collapsed 다)\n"
    "- 감독 · 스태프 인사\n"
    "- 기사가 아닌 공지 · 안내 · 목록 링크\n"
    "각 기사의 content_hash는 그대로 두고 stage와 direction만 채운다.\n"
    'ONLY JSON 배열: [{{"content_hash":"...","stage":"rumour","direction":"in"}}]\n\n'
    "기사 목록:\n{items}")


def _extract_stages(text: str) -> dict[str, tuple[str, str | None]] | None:
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        out: dict[str, tuple[str, str | None]] = {}
        for item in data:
            h, s = item.get("content_hash"), item.get("stage")
            if h and s:
                out[h] = (s, item.get("direction"))
        return out
    except (json.JSONDecodeError, TypeError, AttributeError):
        return None


def classify_stage_rows(rows: list[dict], client, model: str,
                        batch_size: int = 20) -> dict[str, tuple[str, str]]:
    """미태깅 행을 batch_size 단위로 묶어 이적 단계 · 방향을 분류한다.

    content_hash -> (stage, direction) 을 반환한다. 허용 enum 밖 stage는 other,
    direction은 none으로 강등하고, 응답에 없는 hash는 결과에서 빠져 (NULL 유지)
    다음 사이클에 재시도된다. 429를 만나면 그 회차는 즉시 중단한다."""
    result: dict[str, tuple[str, str]] = {}
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        items = json.dumps(
            [{"content_hash": r["content_hash"],
              "title": r["title_original"],
              "summary": r.get("summary_ko") or ""} for r in batch],
            ensure_ascii=False)
        try:
            # club 은 확장 전까지 아스날 고정 (스펙 §9) · roster 는 미주입 상태의
            # 채택판 문안 그대로 (dry-run v1c — 주입은 명단 갱신 뒤 재평가)
            msg = client.models.generate_content(
                model=model,
                contents=STAGE_PROMPT.format(club="아스날", roster="(제공되지 않음)",
                                             items=items),
                config={"max_output_tokens": 2048,
                        "response_mime_type": "application/json"})
        except Exception as e:
            if _is_rate_limit(e):
                log.warning("Gemini rate limit(429), 단계 분류 중단 — 남은 배치 다음 사이클")
                break
            log.warning("Gemini 호출 실패, 단계 분류 배치 스킵: %s", e)
            continue
        parsed = _extract_stages(msg.text)
        if parsed is None:
            log.warning("Gemini 응답 파싱 실패, 단계 분류 배치 스킵")
            continue
        for h, (stage, direction) in parsed.items():
            stage = _stage.normalize(stage)
            if stage == "official":
                # 규칙 경로 전용 불변량 — 프롬프트 밖 응답 방어. 강등 목적지는
                # done (타 매체의 "오피셜" 보도는 새 체계에서 완료 계열 — 2026-08-10 스펙 §4)
                log.warning("LLM이 official 반환 — done으로 강등 content_hash=%s", h)
                stage = "done"
            result[h] = (stage, _stage.normalize_direction(direction))
    return result
