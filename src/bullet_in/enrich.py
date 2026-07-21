from __future__ import annotations
import json, logging, re

log = logging.getLogger(__name__)

PAYWALLED_OUTLETS = {"The Athletic"}

from bullet_in import transfer_stage as _stage

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
    'ONLY JSON: {{"title_ko":"...","summary_ko":"...","summary3_ko":["...","...","..."],"body_ko":"..."}}'
    "\n\nTitle: {title}\nBody: {body}")

PARAPHRASE_PROMPT = (
    "다음은 한국어로 번역된 아스날 FC 축구 기사다. 의미·사실·수치·고유명사·인용은 "
    "절대 바꾸지 말고 문장 표현만 자연스럽게 바꿔 다시 쓴다 (paraphrase). 규칙:\n"
    "- title_ko: 제목을 간결한 기사 제목체로 다시 쓴다(말머리 대괄호 제거).\n"
    "- summary_ko: 한 문장 요약, 평어체.\n"
    "- summary3_ko: 핵심 3문장 배열, 평어체.\n"
    "- summary_ko·summary3_ko 존댓말 금지: '확정했습니다' ❌ → '확정했다' ⭕.\n"
    "- body_ko: 본문 전체를 문장 표현만 바꿔 다시 쓴다. 내용 추가·삭제 금지. "
    "2~4문장 단위 문단으로 나누고 문단 사이는 줄바꿈 문자(\\n)로 구분한다.\n"
    "- body_ko 지문도 신문 평어체(종결어미 '~다'): '관심을 갖고 있습니다' ❌ → "
    "'관심을 갖고 있다' ⭕. 인용문(따옴표 안 발화)은 화자의 말투를 그대로 두되, "
    "발화 인용은 반드시 큰따옴표로 감싼다.\n"
    "- 구독·앱 설치·댓글 유도, SNS 팔로우 요청, 팟캐스트·뉴스레터 홍보 등 "
    "기사 내용과 무관한 문구는 body_ko에서 제외.\n"
    "- body_ko 경량 마크다운: 원문의 소제목은 '### ', 원문이 강조한 구절만 '**굵게**', "
    "인용 블록은 '> '. 원문에 없는 장식은 새로 만들지 않는다.\n"
    'ONLY JSON: {{"title_ko":"...","summary_ko":"...","summary3_ko":["...","...","..."],"body_ko":"..."}}'
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

_LOAN_RE = re.compile(r"\bloan", re.IGNORECASE)
# 사유 접두어 — 호출측이 축별로 걸러낼 때 쓴다 (문자열을 옮겨 적으면 조용히 어긋난다).
NAME_MISSING_PREFIX = "인명 누락:"

def detect_title_mistranslation(title_ko: str | None, title_original: str | None,
                                name_map: dict[str, str]) -> list[str]:
    """원문 제목 대비 번역 제목의 결정적 불일치 사유 목록 (환각 검출기의 역방향 축).
    ①원문 제목의 등재 인명 (단어 경계) 이 번역 제목에 **전부** 누락
    — '조르제' (Tzolis) 창작 · 무관 제목 전면 환각 실사례를 잡는다.
    일부만 유지된 경우는 다절 제목 (트윗 · 리스트클) 의 정당한 축약이라 통과.
    ②'임대' 가 원문 근거 (loan · 한국어 원문의 임대) 없이 생성 — permanent 반전 실사례.
    라운드업 (제목 재초점이 정상) 은 호출측에서 제외한다."""
    if not title_ko or not title_original:
        return []
    reasons = []
    folded = _fold_latin(title_original)
    missing, present = [], 0
    for en in dict.fromkeys(name_map.values()):
        if re.search(rf"\b{re.escape(_fold_latin(en))}\b", folded):
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

_CLUB_FIELDS = ("title_ko", "summary_ko", "summary3_ko", "body_ko")

def detect_club_injection(parsed: dict, source_text: str,
                          club_map: dict[str, list[str]]) -> list[str]:
    """번역 산출물 4필드에 등장한 구단명이 원문에 근거 없으면 의심 목록 반환 (게이트 4축).
    이중 대조 — 원문의 한글 표기 (ko 경로 · fmkorea) or 영문 별칭 단어 경계 (en 경로) 중
    하나라도 있으면 근거 인정. 사전 밖 구단은 미검출 (name_map 과 같은 점진 확장).
    실사례: 로저스의 전 소속 (미들즈브러) 학습 지식 주입 — 원문은 Aston Villa 명시."""
    if not club_map:
        return []
    joined = " ".join(filter(None, (parsed.get(k) for k in _CLUB_FIELDS)))
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
BODY_AS_TITLE_SOURCES = {"x_afcstuff"}

def finalize_translation(v: dict, row: dict, glossary: dict[str, str],
                         name_map: dict[str, str],
                         club_map: dict[str, list[str]]
                         ) -> tuple[str | None, str, str, str | None]:
    """번역 결과에 표기 사전 · 환각 게이트 4축 · 문단 보정을 적용해
    set_translation 인자 4필드를 만든다. row 는 rows_missing_translation 의 원본 행.
    회차 경로 (run.py) 와 enrich 전용 백필 패스가 같은 규칙을 쓰도록 여기 한 벌만 둔다
    — 런북 스니펫에 옮겨 적으면 게이트 · 문단 보정이 빠진 채 백필이 돈다."""
    v = apply_glossary(v, glossary)
    h = row.get("content_hash")
    src_text = " ".join(filter(None, [row.get("title_original"),
                                      row.get("body_source"),
                                      row.get("body_excerpt")]))
    # 제목 환각 검출 (설계 ②-A): 1차 검출 = 재번역 큐 (title NULL 저장 → 다음
    # 사이클 재선별), 재검출 (summary_ko 기저장 = 재시도 행) = 원문 제목 폴백.
    suspects = detect_title_hallucination(v["title_ko"], src_text, name_map)
    # 역방향 축: 원문 제목 인명 누락 · 무근거 '임대' — 라운드업 (gossip) 은 제목 재초점이 정상이라 제외
    if row.get("source_id") != "bbc_gossip":
        reasons = detect_title_mistranslation(
            v["title_ko"], row.get("title_original"), name_map)
        if row.get("source_id") in BODY_AS_TITLE_SOURCES:
            reasons = [r for r in reasons if not r.startswith(NAME_MISSING_PREFIX)]
        suspects = suspects + reasons
    # 라운드업 단신 누락 게이트: 원문 괄호 출처 vs 번역 병기 대조 (환각 큐와 같은 재시도 1회)
    omissions = detect_roundup_omission(row.get("body_source"), v["body_ko"])
    # 원문에 없는 구단명 게이트 (4축): 번역 4필드 × 원문 이중 대조 — 인명 suspects 와 분리
    # (합치면 body 만 오염된 케이스에 불필요한 원문 제목 폴백이 걸린다)
    club_suspects = detect_club_injection(v, src_text, club_map)
    title_ko = v["title_ko"]
    retry = bool(row.get("summary_ko"))
    if suspects and retry:
        log.warning("제목 환각 재발 — 원문 제목 폴백 content_hash=%s 의심=%s", h, suspects)
        title_ko = row.get("title_original")
    elif (suspects or omissions or club_suspects) and not retry:
        log.warning(
            "재번역 큐 content_hash=%s 환각의심=%s 단신누락=%s 원문에 없는 구단명=%s",
            h, suspects, omissions, club_suspects)
        title_ko = None
    if omissions and retry:
        log.warning(
            "라운드업 단신 누락 잔존 — 수동 확인 content_hash=%s 누락=%s", h, omissions)
    if club_suspects and retry:
        log.warning(
            "원문에 없는 구단명 잔존 — 수동 확인 content_hash=%s 구단=%s", h, club_suspects)
    return title_ko, v["summary_ko"], v["summary3_ko"], paragraphize(v["body_ko"])

def _extract_full(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
        s3 = d["summary3_ko"]
        s3 = "\n".join(s3) if isinstance(s3, list) else str(s3)
        return {"title_ko": d["title_ko"], "summary_ko": d["summary_ko"],
                "summary3_ko": s3, "body_ko": d["body_ko"]}
    except (json.JSONDecodeError, KeyError, TypeError):
        return None

def partition_by_paywall(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    para, trans = [], []
    for r in rows:
        (para if r.get("outlet") in PAYWALLED_OUTLETS else trans).append(r)
    return para, trans

def enrich_rows(rows: list[dict], client, model: str, mode: str = "translate"
                ) -> dict[str, dict]:
    prompt = PARAPHRASE_PROMPT if mode == "paraphrase" else TRANSLATE_PROMPT
    result: dict[str, dict] = {}
    for r in rows:
        h = r["content_hash"]
        try:
            msg = client.models.generate_content(
                model=model,
                contents=prompt.format(title=r["title_original"],
                                       body=r.get("body_source") or r.get("body_excerpt") or ""),
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

# 주의: 아래 단계 목록(rumour·interest·negotiating·personal_terms·medical·agreed·other)은
# transfer_stage.VALID_STAGES와 동기화되어야 한다. 새 단계를 추가하면 이 프롬프트도
# 업데이트해야 하며, tests/test_enrich.py::test_stage_prompt_lists_llm_stages_and_excludes_official()에서
# 불일치를 검출한다.
STAGE_PROMPT = (
    "다음은 아스날 FC 관련 기사 목록이다. 각 기사를 이적 진행 단계로 분류한다.\n"
    "단계 (반드시 아래 영문 값 중 하나로 답한다):\n"
    "- rumour: 근거 약한 소문 · 연결설\n"
    "- interest: 구단이 실제 관심 표명 · 스카우팅\n"
    "- negotiating: 구단 간 · 에이전트와 이적료/조건 협상 중\n"
    "- personal_terms: 선수와 개인 조건 (연봉 등) 합의\n"
    "- medical: 메디컬 테스트 진행 · 통과\n"
    "- agreed: 구단 간 이적 합의 · 딜 확정/임박 보도 (타 매체의 공식 발표 보도 포함)\n"
    "- other: 이적과 무관하거나 단계를 판단할 수 없음\n"
    "각 기사의 content_hash는 그대로 두고 stage만 채운다.\n"
    'ONLY JSON 배열: [{{"content_hash":"...","stage":"rumour"}}]\n\n'
    "기사 목록:\n{items}")


def _extract_stages(text: str) -> dict[str, str] | None:
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        out: dict[str, str] = {}
        for item in data:
            h, s = item.get("content_hash"), item.get("stage")
            if h and s:
                out[h] = s
        return out
    except (json.JSONDecodeError, TypeError, AttributeError):
        return None


def classify_stage_rows(rows: list[dict], client, model: str,
                        batch_size: int = 20) -> dict[str, str]:
    """미태깅 행을 batch_size 단위로 묶어 영입 단계를 분류한다.

    content_hash -> stage(enum) 를 반환한다. 허용 enum 밖 값은 other로 강등하고,
    응답에 없는 hash는 결과에서 빠져 (NULL 유지) 다음 사이클에 재시도된다.
    429를 만나면 그 회차는 즉시 중단한다 (남은 배치 다음 사이클 누적)."""
    result: dict[str, str] = {}
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        items = json.dumps(
            [{"content_hash": r["content_hash"],
              "title": r["title_original"],
              "summary": r.get("summary_ko") or ""} for r in batch],
            ensure_ascii=False)
        try:
            msg = client.models.generate_content(
                model=model,
                contents=STAGE_PROMPT.format(items=items),
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
        for h, stage in parsed.items():
            stage = _stage.normalize(stage)
            if stage == "official":
                # 규칙 경로 전용 불변량 (spec §4.3) — 프롬프트 밖 응답 방어
                log.warning("LLM이 official 반환 — agreed로 강등 content_hash=%s", h)
                stage = "agreed"
            result[h] = stage
    return result
