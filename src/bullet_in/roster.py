"""enrich 추출 쌍 → players · article_players 반영 (스펙 §4.1)."""
from __future__ import annotations
import logging, re
from bullet_in import transfer_stage as _stage
from bullet_in.enrich import _fold_latin
from bullet_in.storage.players import MENTION, PlayerStore, ROLES, SUBJECT

log = logging.getLogger(__name__)

_MAX_PAIRS = 30          # 모델이 폭주 출력을 내도 회차당 처리 상한
_MAX_FULL_NAME = 100     # players.full_name VARCHAR(100)
_MAX_KO = 50             # players.ko_candidate VARCHAR(50)
_HANGUL_RE = re.compile(r"[가-힣]")
_MIN_KO_KEY = 2          # 한글 이름 후보 길이 하한 (「사카」 같은 2자 표기를 살린다)
_MIN_LATIN_KEY = 4       # 라틴 후보 길이 하한 — 세 글자 이하는 일반 단어에 걸린다
_DUP_DISTANCE = 2        # 중복 의심 판정의 이름 편집거리 상한 (스펙 §8.5 의 8쌍이 전부 1 ~ 2)


def normalize_role(raw) -> str | None:
    """추출이 낸 역할 값 정규화 — 어휘 밖은 미기입 (None) 으로 떨어뜨린다.

    미기입은 서빙에서 옛 규칙 (단계 `other` 제외) 으로 판정되므로 (스펙 §3.2
    전환 규칙), 모델이 값을 빠뜨려도 종전 화면이 유지된다."""
    if not isinstance(raw, str):
        return None
    v = raw.strip().lower()
    return v if v in ROLES else None


def _squash(text: str | None) -> str:
    """한글 이름 대조용 — 띄어쓰기를 지운다 (「가브리엘 제주스」 ↔ 「가브리엘제주스」)."""
    return re.sub(r"\s+", "", text or "")


def _name_keys(pair: dict, forms: dict | None) -> tuple[set[str], set[str]]:
    """이름 후보 (한글, 라틴) — 모델이 낸 표기 + 명단 표기 (스펙 §5.1 ①).

    한글은 전체와 마지막 어절 (성) 을, 영문은 전체와 성을 쓴다.
    명단 표기를 함께 쓰는 이유는 음역 흔들림이다 — 「졸리스」 · 「촐리스」 처럼
    회차마다 갈리는 표기를 명단의 확정 표기가 직접 일치로 잡는다.
    유사도 폴백은 두지 않는다: 명단을 재료로 쓰면 기여가 0 이었고, 짧은 표기에서는
    한 글자 차이가 임계값을 못 넘는다 (제수스 ↔ 제주스 0.667 · 스펙 §5.1)."""
    ko, fn = (pair.get("ko") or "").strip(), (pair.get("full_name") or "").strip()
    kk = [_squash(ko)]
    if len(ko.split()) > 1:
        kk.append(_squash(ko.split()[-1]))
    lat = [_fold_latin(fn)]
    if len(fn.split()) > 1:
        lat.append(_fold_latin(fn.split()[-1]))
    forms = forms or {}
    for key in ("ko_name", "ko_full_name"):
        x = forms.get(key)
        if x:
            kk.append(_squash(x))
            if len(x.split()) > 1:
                kk.append(_squash(x.split()[-1]))
    for key in ("full_name", "surname"):
        x = forms.get(key)
        if x:
            lat.append(_fold_latin(x))
    return ({k for k in kk if len(k) >= _MIN_KO_KEY},
            {l for l in lat if len(l) >= _MIN_LATIN_KEY})


def decide_role(article: dict, pair: dict, forms: dict | None = None) -> str:
    """이 기사가 그 인물을 하나의 소식으로 다루는지 (스펙 §5.1).

    제목 (번역 · 원제) 이나 소제목에 이름이 있으면 subject, 아니면 mention 이다.
    소제목은 body_ko 에서 '###' 로 시작하는 줄이다.
    모델에게는 거부권만 준다 — 제목만 근거인데 모델이 mention 이라 답하면 내리고,
    모델의 subject 는 규칙을 뒤집지 못한다. 모델이 거의 전부를 subject 라 부르므로
    (dry-run 에서 subject 재현율 99% · mention 40%) 올리는 쪽 근거가 없다.

    **이 값이 채워진 행은 서빙이 옛 규칙 대신 역할로 판정한다** — 잘못된 mention
    은 그 기사를 선수 페이지에서 지운다 (스펙 §5.5 의 실패 방향)."""
    kk, lat = _name_keys(pair, forms)
    heads = [ln for ln in (article.get("body_ko") or "").split("\n")
             if ln.strip().startswith("###")]

    def hit(text: str | None) -> bool:
        if not text:
            return False
        return (any(k in _squash(text) for k in kk)
                or any(l in _fold_latin(text) for l in lat))

    in_title = hit(article.get("title_ko")) or hit(article.get("title_original"))
    in_head = any(hit(x) for x in heads)
    if not (in_title or in_head):
        return MENTION
    if in_title and not in_head and pair.get("role") == MENTION:
        return MENTION
    return SUBJECT


def _edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def duplicate_suspects(full_name: str, surname: str,
                       existing: list[dict]) -> list[dict]:
    """성이 같고 이름이 비슷한 기존 선수 — 중복 등재 의심 (스펙 §8.5).

    **병합 판단이 아니라 사람에게 보여줄 목록이다.** 편집거리도 한글 표기 일치도
    근거가 못 된다 — Nico Williams 와 Neco Williams 는 편집거리 2 에 한글 표기까지
    같은데 다른 선수다 (하나는 아스날 영입 대상 · 하나는 노팅엄 포레스트 기사).
    갈리는 것은 기사 맥락뿐이라 자동 병합을 하지 않는다."""
    sn = _fold_latin(surname)
    out = []
    for p in existing:
        if _fold_latin(p.get("surname") or "") != sn:
            continue
        if _edit_distance(_fold_latin(full_name),
                          _fold_latin(p["full_name"])) > _DUP_DISTANCE:
            continue
        out.append({"id": p["id"], "full_name": p["full_name"]})
    return out


def normalize_pairs(raw, source_id: str | None = None,
                    glossary: dict[str, str] | None = None,
                    accept_path: str | None = None) -> list[dict]:
    """모델 출력 players 필드 검증 — 이름 없는 항목 · 비 dict · 중복은 버리고
    stage 는 enum 정규화.

    공홈 기사면 모델이 낸 stage 와 무관하게 official 로 덮어쓴다 (스펙 §8.1 의
    승격 규칙과 동일) — 추출 프롬프트가 stage 선택지에서 official 을 빼 놓아
    모델은 공홈에서도 agreed 등을 답하므로, "official 이면 유지" 방식으로는
    승격이 일어나지 않는다. 기사 단위 경로 (run.py 의 stage_ruled) 와 소급
    UPDATE 가 이미 공홈 기사의 stage 를 조건 없이 official 로 덮어쓰고 있어
    여기서도 같은 규칙을 적용해 소급분과 이후 적재분이 갈리지 않게 한다.
    판정은 rule_stage() 를 재사용한다 (arsenal_official 문자열의 단일 출처 유지).
    accept_path 도 함께 넘겨 기사 단위와 같은 답을 받는다 — 제목 어휘로만 채택된
    공홈 기사는 official 고정에서 빠지므로 (공홈 수집 개정 스펙 2026-08-12 §3.3)
    여기서 고정하면 한 기사가 목록 카드와 선수 페이지에서 다른 단계를 말하게 된다.
    스키마 폭 (VARCHAR 100/50) 을 넘는 출력과 배열 폭주는 여기서 걸러 DB 예외를 막는다.

    glossary 는 표기 교정 사전 (오표기 → 통용) 이며 ko 에 적용한다 (스펙 §8.4).
    추출은 영문 원문을 읽고 한글 표기를 직접 만들어 음역이 회차마다 흔들리는데
    (같은 선수에 「졸리스」 · 「크리스토스 촐리스」 · 「크리스토스 졸리스」 가 판본별로
    나왔다), 그 표기가 그대로 후보 등재 이름이 된다. 세 프롬프트가 모두 이 함수를
    지나므로 여기 한 곳이면 된다."""
    if not isinstance(raw, list):
        return []
    ruled_official = _stage.rule_stage(source_id, accept_path)[0] == "official"
    out, seen = [], set()
    for item in raw[:_MAX_PAIRS]:
        if not isinstance(item, dict):
            continue
        fn = (item.get("full_name") or "").strip()
        if not fn or len(fn) > _MAX_FULL_NAME or _HANGUL_RE.search(fn):
            continue
        folded = _fold_latin(fn)
        if folded in seen:
            continue
        seen.add(folded)
        stage = _stage.normalize(item.get("stage"))
        if ruled_official:
            stage = "official"
        elif stage == "official":
            # 강등 목적지는 기사 단위 경로와 동일하게 done (2026-08-10 스펙 §4)
            stage = "done"
        ko = (item.get("ko") or "").strip() or None
        if ko:
            for wrong, right in (glossary or {}).items():
                ko = ko.replace(wrong, right)
        if ko and len(ko) > _MAX_KO:
            ko = None
        out.append({"full_name": fn, "ko": ko, "stage": stage,
                    "role": normalize_role(item.get("role"))})
    return out


def record_article_players(store: PlayerStore, content_hash: str,
                           pairs: list[dict], article: dict) -> list[dict]:
    """쌍을 저장하고 명단 밖 선수는 후보 등재 — 신규 후보 목록을 반환한다 (알림 입력).
    매칭은 접힌 full_name 우선, 다음 접힌 성 (동성 복수면 제외) — 성 폴백은 한 단어
    출력에만 적용한다. 풀네임 (두 단어 이상) 이 by_full 미스면 성 폴백 없이 후보로
    등재한다 — 동성 타인 (예: Harvey White) 이 기존 선수 (Ben White) 에게 조용히
    링크되는 것을 막는다.

    역할 값은 여기서 규칙으로 계산한다 (스펙 §5.1) — 이 시점에 player_id 가 잡혀
    있어 명단 표기를 이름 재료로 쓸 수 있다. article 은 판정 재료로 쓰는 기사 본문
    ({title_ko, title_original, body_ko}) 이며, 저장된 것과 같은 문자열을 넘겨야
    수집 경로와 재추출 경로의 판정이 갈리지 않는다 (표기 교정 사전 적용 뒤 값)."""
    if not pairs:
        return []
    by_full, by_surname = store.match_maps()
    name_rows = store.name_rows()
    forms = {r["id"]: r for r in name_rows}
    created: list[dict] = []
    for p in pairs:
        folded = _fold_latin(p["full_name"])
        tokens = p["full_name"].split()
        pid = by_full.get(folded)
        if pid is None and len(tokens) == 1:
            pid = by_surname.get(_fold_latin(tokens[-1]))
        if pid is None:
            surname = tokens[-1]
            if len(surname) > 50:
                log.warning("성 길이 초과 (50자) — 후보 등재 · 링크 skip: %s",
                           p["full_name"])
                continue
            first_name = " ".join(tokens[:-1]) or None
            if first_name and len(first_name) > 50:
                first_name = None
            dups = duplicate_suspects(p["full_name"], surname, name_rows)
            pid = store.insert_candidate(
                full_name=p["full_name"],
                first_name=first_name,
                surname=surname,
                ko_candidate=p["ko"],
                first_seen=content_hash)
            by_full[folded] = pid
            created.append({**p, "player_id": pid, "dup_suspects": dups})
            log.info("후보 등재: %s (%s) stage=%s 근거=%s",
                     p["ko"] or "?", p["full_name"], p["stage"], content_hash[:8])
            if dups:
                log.warning("중복 후보 의심 — 병합은 사람이 판단: %s ↔ %s",
                            p["full_name"],
                            " · ".join(f"{d['full_name']}(id {d['id']})"
                                       for d in dups))
        store.link_article(content_hash, pid, p["stage"],
                           decide_role(article, p, forms.get(pid)))
    return created
