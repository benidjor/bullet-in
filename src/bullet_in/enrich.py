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
    "- 여러 구단 소식을 나열한 라운드업(가십 등) 기사도 발췌하지 않는다: "
    "아스날 무관 구단 항목까지 본문 전체를 빠짐없이 번역한다.\n"
    "- body_ko 지문도 신문 평어체(종결어미 '~다'): '관심을 갖고 있습니다' ❌ → "
    "'관심을 갖고 있다' ⭕. 인용문(따옴표 안 발화)은 화자의 말투를 그대로 두되, "
    "발화 인용은 반드시 큰따옴표로 감싼다.\n"
    "- 구독·앱 설치·댓글 유도, SNS 팔로우 요청, 팟캐스트·뉴스레터 홍보 등 "
    "기사 내용과 무관한 문구는 body_ko에서 제외.\n"
    "- body_ko 경량 마크다운: 원문의 소제목은 '### ', 원문이 강조한 구절만 '**굵게**', "
    "인용 블록은 '> '. 원문에 없는 장식은 새로 만들지 않는다.\n"
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
