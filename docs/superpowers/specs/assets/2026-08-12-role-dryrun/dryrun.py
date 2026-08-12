"""역할 값 · 선수 축 종결 개정 dry-run 하네스 — 스펙 2026-08-12 §5.1.

프로덕션 함수 (enrich.extract_players_rows) 를 그대로 쓰고, 판본 전환은
enrich.EXTRACT_PLAYERS_PROMPT 상수 대입으로만 한다 (런북 2026-08-07 §3).
v0 = 현행판 · v1 = §4.1 ~ §4.4 개정판. 각 판 2회 (흔들림 측정).
결과는 판별 JSON 으로 저장하고 이미 있으면 건너뛴다 (429 대비 재개).

    python -u dryrun.py --plan      # 호출 수만 출력 (Gemini 미접촉)
    python -u dryrun.py             # 실행
    python -u dryrun.py --score     # 저장된 결과만 채점
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import sqlalchemy as sa

from bullet_in import enrich
from bullet_in.enrich import _fold_latin
from bullet_in.reextract_article_players import roster_text

BASE = Path(__file__).parent
EXPECTED = json.loads((BASE / "expected.json").read_text())
EXPECTED.pop("_meta", None)
DB = "bulletin_extract"
MODEL = "gemini-3.1-flash-lite"
PASSES = ("v0_r1", "v0_r2", "v1_r1", "v1_r2", "v1c_r1", "v1c_r2",
          "v1d_r1", "v1d_r2")

# ---------------------------------------------------------------- 판본 문안

ROLE_CLAUSE = (
    "- role 은 이 기사가 그 인물을 하나의 소식으로 다루는지다. subject = 제목이 그 "
    "인물을 내세우거나, 그 인물 이름이 들어간 소제목 · 별도 바이라인의 절이 있거나, "
    "라운드업에서 그 인물 몫의 단신이 독립적으로 있거나, 기사가 그 인물의 거취를 "
    "논평 대상으로 삼는다. mention = 한 문단 안에서 여러 인물과 함께 이름만 "
    "나열되거나 배경 · 과거 비교 · 대체자 · 경쟁자 · 이적료 기준점으로 불려 나온다. "
    "지면에서 차지하는 자리로 정한다 — 그 인물이 중요한 선수인지로 정하지 않는다.\n")

# v1c — v1 실측에서 subject 99% · mention 40% 로 한 방향으로만 부족했다. 두 정의를
# 나란히 놓으면 subject 신호 넷이 먼저 나와 무게가 그쪽으로 기운다. 순서 판정으로
# 바꾸고 mention 을 기본값 (④ 그 밖에는) 으로 둔다. 제목 신호에는 단서를 다는데,
# 없으면 681dfde6 의 트로사르 · b6281445 의 살리바처럼 제목에 이름이 있으나 남의
# 소식의 배경인 인물이 subject 로 올라간다.
ROLE_CLAUSE_V1C = (
    "- role 은 이 기사가 그 인물을 하나의 소식으로 다루는지다. 아래 순서로 판단하고 "
    "어디에도 해당하지 않으면 mention 이다.\n"
    "  ① 제목이 그 인물의 이적 · 거취 · 계약을 이 기사의 소식으로 내세우면 subject. "
    "제목에 이름이 있어도 다른 인물 소식의 배경 · 대체 대상 · 계기로 나오면 해당하지 않는다.\n"
    "  ② 그 인물 이름이 들어간 소제목이나 별도 바이라인의 절이 있으면 subject.\n"
    "  ③ 여러 소식을 모은 기사에서 그 인물 몫의 단신이 독립적으로 있거나, 기사가 그 "
    "인물의 거취를 논평 대상으로 삼으면 subject.\n"
    "  ④ 그 밖에는 mention 이다 — 그 인물에 관한 서술이 한두 문장뿐이거나, 한 문단 "
    "안에서 여러 인물과 함께 이름만 나열되거나, 배경 · 과거 비교 · 대체자 · 경쟁자 · "
    "이적료 기준점으로 불려 나온다.\n"
    "  지면에서 차지하는 자리로 정한다 — 그 인물이 중요한 선수인지로 정하지 않는다.\n")

# v1d — v1c 는 표적을 살렸으나 (mention 40% → 81%) 과잉 경계 넷을 깨뜨렸다
# (e1348256 · b251ca2e · 8a19cc9e · c898d75c). 넷 다 제목 · 소제목에 이름이 있는데
# mention 으로 떨어졌고, 원인은 ④ 를 잔여 규칙으로 두면서 그 안에 "한두 문장뿐이면"
# 이라는 적극 기준을 함께 넣어 ①~③ 통과자에게도 ④ 가 적용된 것이다. 410자 트윗
# (e1348256) 은 제목이 내세운 셋이 전원 한 문장이라 그대로 걸렸다.
# 고치는 곳은 둘 — ①~③ 우선을 명시하고, ④ 에서 문장 수 기준을 뺀다.
ROLE_CLAUSE_V1D = (
    "- role 은 이 기사가 그 인물을 하나의 소식으로 다루는지다. 아래 ① ~ ③ 중 "
    "하나라도 해당하면 subject 이고, 그때는 ④ 를 보지 않는다. 어디에도 해당하지 "
    "않을 때만 mention 이다.\n"
    "  ① 제목이 그 인물의 이적 · 거취 · 계약을 이 기사의 소식으로 내세우면 subject. "
    "제목에 이름이 있어도 다른 인물 소식의 배경 · 대체 대상 · 계기로 나오면 해당하지 않는다.\n"
    "  ② 그 인물 이름이 들어간 소제목이나 별도 바이라인의 절이 있으면 subject.\n"
    "  ③ 여러 소식을 모은 기사에서 그 인물 몫의 단신이 독립적으로 있거나, 기사가 그 "
    "인물의 거취를 논평 대상으로 삼으면 subject.\n"
    "  ④ 그 밖에는 mention 이다 — 한 문단 안에서 여러 인물과 함께 이름만 나열되거나, "
    "배경 · 과거 비교 · 대체자 · 경쟁자 · 이적료 기준점으로 불려 나온다.\n"
    "  지면에서 차지하는 자리로 정한다 — 그 인물이 중요한 선수인지로 정하지 않는다.\n")

# (찾을 것, 바꿀 것) — 전부 정확히 1회 치환돼야 한다. 0회면 상수가 바뀐 것이고
# 그대로 두면 "개정했는데 효과 없음" 이라는 가짜 결론이 나온다.
CLAUSE_EDITS = [
    # §4.2 아스날 기준을 독립 조항으로
    # 앵커를 짧게 잡으면 아래 명단 조항의 "…말하지 않으면 other." 와 둘 다 걸린다.
    ("그 선수의 진행 단계를 말하지 "
     "않으면 other.\n",
     "그 선수의 진행 단계를 말하지 않으면 other. stage 는 언제나 아스날 건 "
     "기준이다. 그 인물에 관해 이 기사가 전하는 것이 아스날과 무관한 딜뿐이면 "
     "other 다 — done 과 collapsed 는 특히 그렇다.\n"),
    # §4.3 done 한정
    ("done(이미 완료된 이적의 후속 · 부대 보도) · ",
     "done(이미 완료된 아스날 이적의 후속 · 부대 보도 — 타 구단 간 완료 이적이 "
     "문장 안에 나열된 것은 other) · "),
    # §4.4 collapsed 배제 한 문장
    ("collapsed(아스날 관련 딜의 종결 — "
     "잔류 확정 · 재계약 체결 · 결렬 확정) · ",
     "collapsed(아스날 관련 딜의 종결 — 잔류 확정 · 재계약 체결 · 결렬 확정. "
     "아스날이 자기 소속 선수와 맺는 신규 · 연장 계약은 종결이 아니다) · "),
]


def build_v1_prompt(role_clause: str = ROLE_CLAUSE) -> str:
    """현행 EXTRACT_PLAYERS_PROMPT 에서 개정 네 곳만 바꾼 문자열을 만든다.
    v1 과 v1c 의 차이는 role 조항 하나뿐이다 — 나머지 세 곳은 같은 문자열을 쓴다."""
    p = enrich.EXTRACT_PLAYERS_PROMPT
    for old, new in CLAUSE_EDITS:
        if p.count(old) != 1:
            sys.exit(f"치환 실패 ({p.count(old)}회): {old[:40]!r}\n"
                     "프로덕션 상수가 바뀌었다. 하네스를 먼저 맞춰라.")
        p = p.replace(old, new)
    # §4.1 role — 조항 추가 + JSON 뼈대 두 곳
    p = p.replace('"stage":"단계"}}', '"stage":"단계","role":"subject 또는 mention"}}')
    if '"role"' not in p:
        sys.exit("role 뼈대 치환 실패 — JSON 예시 문자열이 바뀌었다.")
    marker = "- stage 값:"
    if p.count(marker) != 1:
        sys.exit("role 조항을 넣을 자리를 못 찾았다.")
    head, tail = p.split(marker, 1)
    return head + role_clause + marker + tail


# ---------------------------------------------------------------- 입력 · 실행

def fetch_rows(engine) -> list[dict]:
    out = []
    with engine.connect() as c:
        for pref in EXPECTED:
            rs = c.execute(sa.text(
                "SELECT content_hash, title_original, body_source, body_excerpt, body_ko "
                "FROM articles WHERE content_hash LIKE :p"), {"p": pref + "%"}).mappings().all()
            if len(rs) != 1:
                sys.exit(f"행 매칭 {len(rs)}건: {pref}")
            out.append(dict(rs[0]))
    return out


def run_pass(name: str, prompt: str, rows: list[dict], client, roster: str) -> None:
    path = BASE / f"result_{name}.json"
    if path.exists():
        print(f"{name}: 결과 있음, 건너뜀")
        return
    orig = enrich.EXTRACT_PLAYERS_PROMPT
    enrich.EXTRACT_PLAYERS_PROMPT = prompt
    t0 = time.time()
    try:
        result = enrich.extract_players_rows(rows, client, MODEL, roster=roster)
    finally:
        enrich.EXTRACT_PLAYERS_PROMPT = orig
    short = {h[:8]: pairs for h, pairs in result.items()}
    path.write_text(json.dumps(short, ensure_ascii=False, indent=1))
    print(f"{name}: {len(short)}/{len(rows)}건 · {time.time() - t0:.0f}초")


# ---------------------------------------------------------------- 채점

def score(name: str) -> None:
    path = BASE / f"result_{name}.json"
    if not path.exists():
        print(f"{name}: 결과 없음")
        return
    res = json.loads(path.read_text())
    stats: dict[str, list[int]] = {}
    fails: list[str] = []
    blank = total = 0
    for pref, exp in EXPECTED.items():
        g = exp["group"]
        s = stats.setdefault(g, [0, 0, 0, 0])   # role맞음, role대상, stage맞음, stage대상
        got = res.get(pref)
        if got is None:
            fails.append(f"  MISSING {pref} ({g})")
            continue
        by_name = {_fold_latin(p.get("full_name") or ""): p for p in got if isinstance(p, dict)}
        for pn, want in exp["players"].items():
            p = by_name.get(_fold_latin(pn))
            if p is None:
                fails.append(f"  누락 {pref}/{pn} ({g})")
                s[1] += 1
                if want["stage"]:
                    s[3] += 1
                continue
            total += 1
            role = (p.get("role") or "").strip()
            if not role:
                blank += 1
            s[1] += 1
            if role in want["role"]:
                s[0] += 1
            else:
                fails.append(f"  role {pref}/{pn} ({g}): {role or '미기입'} ∉ {want['role']}")
            if want["stage"]:
                s[3] += 1
                st = (p.get("stage") or "").strip()
                if st in want["stage"]:
                    s[2] += 1
                else:
                    fails.append(f"  stage {pref}/{pn} ({g}): {st} ∉ {want['stage']}")
        extra = set(by_name) - {_fold_latin(x) for x in exp["players"]}
        for e in exp.get("must_exclude", []):
            if _fold_latin(e) in by_name:
                fails.append(f"  제외 위반 {pref}/{e}")
        if extra:
            fails.append(f"  (참고) {pref} 미등록 인물 {len(extra)}명")
    line = " | ".join(
        f"{g}: role {v[0]}/{v[1]}" + (f" stage {v[2]}/{v[3]}" if v[3] else "")
        for g, v in sorted(stats.items()))
    rate = f"{blank}/{total}" if total else "-"
    print(f"\n[{name}] {line}\n  role 미기입 {rate}")
    for f in fails:
        print(f)


def consistency() -> None:
    """같은 판 2회의 role 판정 일치 — 흔들리는 값은 표시 규칙의 근거로 못 쓴다."""
    for v in ("v0", "v1", "v1c", "v1d"):
        a, b = (BASE / f"result_{v}_r1.json", BASE / f"result_{v}_r2.json")
        if not (a.exists() and b.exists()):
            continue
        ra, rb = json.loads(a.read_text()), json.loads(b.read_text())
        same = diff = 0
        for pref, exp in EXPECTED.items():
            ma = {_fold_latin(p.get("full_name") or ""): (p.get("role") or "")
                  for p in ra.get(pref, []) if isinstance(p, dict)}
            mb = {_fold_latin(p.get("full_name") or ""): (p.get("role") or "")
                  for p in rb.get(pref, []) if isinstance(p, dict)}
            for pn in exp["players"]:
                k = _fold_latin(pn)
                if k in ma and k in mb:
                    if ma[k] == mb[k]:
                        same += 1
                    else:
                        diff += 1
                        print(f"  흔들림 {pref}/{pn}: {ma[k] or '미기입'} ↔ {mb[k] or '미기입'}")
        print(f"[{v}] 2회 일치 {same} · 불일치 {diff}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true", help="호출 수만 출력")
    ap.add_argument("--score", action="store_true", help="저장된 결과만 채점")
    ap.add_argument("--sleep", type=float, default=4.5)
    args = ap.parse_args()

    if args.score:
        for n in PASSES:
            score(n)
        print()
        consistency()
        return

    engine = sa.create_engine(os.environ["MARIADB_URL"].rsplit("/", 1)[0] + "/" + DB)
    rows = fetch_rows(engine)
    roster = roster_text(engine)
    v1 = build_v1_prompt()
    v1c = build_v1_prompt(ROLE_CLAUSE_V1C)
    v1d = build_v1_prompt(ROLE_CLAUSE_V1D)
    if len({v1, v1c, v1d}) != 3:
        sys.exit("판본 문자열이 겹친다 — role 조항 치환이 안 걸렸다.")
    prompts = {"v0": enrich.EXTRACT_PLAYERS_PROMPT, "v1": v1, "v1c": v1c, "v1d": v1d}
    todo = [n for n in PASSES if not (BASE / f"result_{n}.json").exists()]
    print(f"표본 {len(rows)}건 · 판본 {len(PASSES)} · 남은 판 {len(todo)} "
          f"→ 호출 {len(rows) * len(todo)}회")
    print(f"명단 재료 {roster.count('(')}명 · {len(roster)}자")
    print(f"enrich 모듈 {enrich.__file__}")
    print(f"프롬프트 길이 — 현행 {len(enrich.EXTRACT_PLAYERS_PROMPT)} · v1 {len(v1)} · v1c {len(v1c)} · v1d {len(v1d)}자")
    if args.plan:
        return

    from google import genai
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    for n in PASSES:
        run_pass(n, prompts[n.rsplit("_", 1)[0]], rows, client, roster)
        time.sleep(args.sleep)

    print("\n=== 채점 ===")
    for n in PASSES:
        score(n)
    print()
    consistency()


if __name__ == "__main__":
    main()
