"""역할 값 산출 규칙의 시제품과 채점기 — 스펙 2026-08-12 §5.

Gemini 를 부르지 않는다. 이미 저장된 추출 출력 (result_*.json) 과 운영 사본의
기사 · 명단만 읽어 역할을 계산하고 expected.json 으로 채점한다.
문구 탐색이 시소로 중단된 뒤 (§4.1) 대안을 재는 데 쓴 스크립트이고,
다음 회차가 규칙을 고칠 때 같은 잣대로 재비교하라고 남긴다.

    python -u role_rule.py                 # 방식별 비교표
    python -u role_rule.py --fails         # 채택안의 오답 전건
"""
import argparse
import json
import os
import re
from collections import defaultdict
from pathlib import Path

import sqlalchemy as sa

from bullet_in.enrich import _fold_latin

BASE = Path(__file__).parent
DB = os.environ.get("ROLE_RULE_DB", "bulletin_extract")   # 사본 이름은 세션마다 다르다
EXTRACTION = "result_v0_r2.json"   # 역할 계산의 입력 (현행 프롬프트 출력)
VETO = "result_v1_r1.json"         # 거부권 입력 (v1 문안의 role 값)

# 병렬 트랙이 독립적으로 라벨을 준 기사 — 순환 확인용 (§4.3)
INDEPENDENT = {"a418e338", "681dfde6", "d43f214d", "054b82ec", "b6281445"}


def squash(s: str | None) -> str:
    return re.sub(r"\s+", "", s or "")


def load():
    exp = json.loads((BASE / "expected.json").read_text())
    exp.pop("_meta", None)
    got = json.loads((BASE / EXTRACTION).read_text())
    veto = json.loads((BASE / VETO).read_text())
    url = os.environ["MARIADB_URL"].rsplit("/", 1)[0] + "/" + DB
    eng = sa.create_engine(url)
    arts, roster = {}, {}
    with eng.connect() as c:
        for h in exp:
            row = c.execute(sa.text(
                "SELECT title_ko, title_original, body_ko FROM articles "
                "WHERE content_hash LIKE :p"), {"p": h + "%"}).mappings().first()
            if row is None:
                raise SystemExit(f"{DB} 에 기사가 없다: {h} — 사본이 표본보다 오래됐다")
            arts[h] = dict(row)
        for r in c.execute(sa.text(
                "SELECT full_name, ko_name, ko_full_name, surname FROM players")).mappings():
            roster[_fold_latin(r["full_name"] or "")] = dict(r)
    return exp, got, veto, arts, roster


def name_keys(item: dict, roster: dict, use_roster: bool):
    """이름 후보 — 모델이 낸 표기 + (선택) 명단 표기. 한글 · 라틴을 나눠 돌려준다."""
    ko = (item.get("ko") or "").strip()
    fn = (item.get("full_name") or "").strip()
    kk = [squash(ko)] + ([squash(ko.split()[-1])] if len(ko.split()) > 1 else [])
    lat = [_fold_latin(fn)] + ([_fold_latin(fn.split()[-1])] if len(fn.split()) > 1 else [])
    if use_roster:
        p = roster.get(_fold_latin(fn))
        if p is None and len(fn.split()) > 1:
            # 성 폴백은 동성이 하나일 때만 (record_article_players 와 같은 규율)
            sn = _fold_latin(fn.split()[-1])
            cand = [v for v in roster.values() if _fold_latin(v["surname"] or "") == sn]
            p = cand[0] if len(cand) == 1 else None
        if p:
            for x in (p["ko_name"], p["ko_full_name"]):
                if x:
                    kk += [squash(x)] + ([squash(x.split()[-1])] if len(x.split()) > 1 else [])
            for x in (p["full_name"], p["surname"]):
                if x:
                    lat.append(_fold_latin(x))
    return [k for k in set(kk) if len(k) >= 2], [l for l in set(lat) if len(l) > 3]


def decide(art: dict, item: dict, roster: dict, use_roster: bool, veto_role: str | None):
    """(역할, 제목근거, 소제목근거) — 스펙 §5.1 의 네 단계."""
    kk, lat = name_keys(item, roster, use_roster)
    paras = [p for p in (art["body_ko"] or "").split("\n") if p.strip()]
    heads = [p for p in paras if p.strip().startswith("###")]

    # 음역 흔들림은 명단 표기가 잡는다. 한글 유사도 폴백 (SequenceMatcher) 을 붙여
    # 봤으나 명단을 재료로 쓰면 기여가 0 이었다 — 임계값을 0.5 까지 낮춰도 150/156
    # 으로 동일. 짧은 표기에서 한 글자 차이는 0.7 을 못 넘기도 한다 (제수스 ↔ 제주스
    # 0.667 · 촐리스 ↔ 졸리스 0.667). 그래서 폴백을 두지 않는다.
    def hit(text: str | None, korean: bool = True) -> bool:
        if not text:
            return False
        if any(k in squash(text) for k in kk):
            return True
        return any(l in _fold_latin(text) for l in lat)

    in_title = hit(art["title_ko"]) or hit(art["title_original"], korean=False)
    in_head = any(hit(x) for x in heads)
    role = "subject" if (in_title or in_head) else "mention"
    # 제목만 근거일 때에 한해 모델이 언급이라 하면 내린다. 모델의 subject 는 못 뒤집는다.
    if role == "subject" and in_title and not in_head and veto_role == "mention":
        role = "mention"
    return role, in_title, in_head


def evaluate(exp, got, veto, arts, roster, use_roster, use_veto):
    tab = defaultdict(lambda: [0, 0])
    indep = [0, 0]
    fails = []
    for h, e in exp.items():
        rows = got.get(h)
        if rows is None:
            continue
        by = {_fold_latin(p.get("full_name") or ""): p for p in rows}
        vd = {_fold_latin(p.get("full_name") or ""): (p.get("role") or "")
              for p in (veto.get(h) or [])}
        for pn, want in e["players"].items():
            it = by.get(_fold_latin(pn))
            if it is None:
                continue
            v = vd.get(_fold_latin(pn)) if use_veto else None
            role, t, hd = decide(arts[h], it, roster, use_roster, v)
            ok = role in want["role"]
            key = "/".join(want["role"])
            tab[key][1] += 1
            tab[key][0] += ok
            if h in INDEPENDENT:
                indep[1] += 1
                indep[0] += ok
            if not ok:
                fails.append((h, it.get("ko") or pn, role, key, t, hd, e["title"]))
    return tab, indep, fails


def line(tag, tab, indep):
    s, m = tab["subject"], tab["mention"]
    tot = [sum(x[0] for x in tab.values()), sum(x[1] for x in tab.values())]
    print(f"  {tag:<34} subject {s[0]}/{s[1]} ({s[0]/s[1]:.0%})  "
          f"mention {m[0]}/{m[1]} ({m[0]/m[1]:.0%})  "
          f"합산 {tot[0]}/{tot[1]} ({tot[0]/tot[1]:.0%})  독립 {indep[0]}/{indep[1]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fails", action="store_true", help="채택안의 오답 전건")
    args = ap.parse_args()
    exp, got, veto, arts, roster = load()
    print(f"표본 {len(exp)}건 · 추출 입력 {EXTRACTION} · 거부권 입력 {VETO}\n")
    variants = [("규칙 — 모델 표기만", False, False),
                ("규칙 — 모델 + 명단", True, False),
                ("하이브리드 — 모델 표기만", False, True),
                ("하이브리드 — 모델 + 명단 (채택)", True, True)]
    for tag, r, v in variants:
        tab, indep, fails = evaluate(exp, got, veto, arts, roster, r, v)
        line(tag, tab, indep)
        if args.fails and tag.endswith("(채택)"):
            print("\n  오답 전건")
            for h, ko, role, want, t, hd, title in fails:
                print(f"    [{h}] {ko:<18} 판정 {role:<8} 기대 {want:<16} "
                      f"(제목={t} 소제목={hd})")
                print(f"             {title[:56]}")


if __name__ == "__main__":
    main()
