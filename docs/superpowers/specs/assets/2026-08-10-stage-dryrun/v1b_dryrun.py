"""collapsed 경계 문안 1판 보강 (v1b) 소표본 재검증 — 적용 회차 (스펙 §6.1 잔여 결함).

v1 (채택판) 대비 바뀐 것은 collapsed 관련 문안뿐이다.
- ① 타 구단 무산 침범 차단: "기사에 {club} 이 등장하지 않는 타 구단 간 딜" 은 collapsed 불가 명시.
- ② 협상 거부 방침 오독 차단: "협상·매각 거부 방침 보도는 종결이 아니다" 명시.
- 하이재킹 완결 규칙 단순화 (스펙 §3.2 재조정): 주관점 판별 문장을 제거하고
  "경쟁 구단의 영입 확정 = collapsed · 방향은 {club} 이 시도했던 축" 으로 교체.
  이에 따라 기대값 2행 (28ae2559 · 745f1094) 을 collapsed·in 으로 갱신해 채점한다.

기대값은 expected.json 재사용 (하이재킹 2행만 덮어씀) · 판 1개 × 2회 · 40행 = 총 4호출.
"""
import json
import os
import sys
import time
from pathlib import Path

import sqlalchemy as sa

from bullet_in import enrich
from bullet_in import transfer_stage as _stage
from google import genai

BASE = Path(__file__).parent
EXPECTED = json.loads((BASE / "expected.json").read_text())
# 스펙 §3.2 재조정 (하이재킹 완결 = collapsed · 방향은 아스날이 시도했던 축) 반영
EXPECTED["28ae2559"] = {"group": "overreach", "v0": ["agreed"], "new": ["collapsed"], "dir": "in"}
EXPECTED["745f1094"] = {"group": "preserve", "v0": ["agreed"], "new": ["collapsed"], "dir": "in"}
DB = "bulletin_after_0808"

V1B_PROMPT = (
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
    "- collapsed: {club} 이 당사자이거나 영입 경쟁을 벌였던 딜의 종결이 확정된 보도 — "
    "영입 대상의 잔류 확정 · 현 소속 구단과의 재계약 체결 · 협상 결렬 확정 · "
    "{club} 이 노리던 선수를 경쟁 구단이 영입 확정 (하이재킹 완결). "
    "기사에 {club} 이 등장하지 않는 타 구단 간 딜의 무산·결렬은 collapsed 가 아니다 — "
    "그 딜이 도달했던 마지막 단계로 답한다. "
    "진행 중인 잔류·재계약 협상, 상대 구단이 협상·매각을 거부한다는 방침 보도는 "
    "종결이 아니다 — 그 딜의 진행 단계 (interest·negotiating) 로 답한다\n"
    "- other: 이적과 무관하거나 단계를 판단할 수 없음\n"
    "방향 (direction — 반드시 아래 영문 값 중 하나로 답한다):\n"
    "- in: {club} 로 오는 이적 (임대 영입 포함)\n"
    "- out: {club} 에서 나가는 이적 (방출 · 매각 · 임대 방출 포함)\n"
    "- none: 이적 무관 기사 · 방향을 판단할 수 없음\n"
    "방향은 {club} 기준이다 — {club} 이 이적의 당사자 (사는 쪽 또는 파는 쪽) 가 아니면 반드시 none 으로 답한다.\n"
    "{club} 이 관심만 가졌던 딜, 이미 {club} 을 떠난 선수의 새 소속 이적도 none 이다.\n"
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


def fetch_rows():
    url = os.environ["MARIADB_URL"]
    url = url.rsplit("/", 1)[0] + "/" + DB
    eng = sa.create_engine(url)
    rows = {}
    with eng.connect() as conn:
        for p in EXPECTED:
            r = conn.execute(sa.text(
                "SELECT content_hash, title_original, summary_ko "
                "FROM articles WHERE content_hash LIKE :p"), {"p": p + "%"}).mappings().first()
            if r is None:
                sys.exit(f"row not found: {p}")
            rows[p] = dict(r)
    return rows


def main():
    _stage.VALID_STAGES.update({"done", "collapsed"})
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    rows = fetch_rows()
    print("loaded rows:", len(rows), "| enrich module:", enrich.__file__)

    prompt = V1B_PROMPT.replace("{club}", "아스날").replace("{roster}", "(제공되지 않음)")
    orig_prompt = enrich.STAGE_PROMPT
    for name in ("v1b_r1", "v1b_r2"):
        out_path = BASE / f"result_{name}.json"
        if out_path.exists():
            print(name, "already done, skip")
            continue
        enrich.STAGE_PROMPT = prompt
        inputs = [{"content_hash": r["content_hash"],
                   "title_original": r["title_original"],
                   "summary_ko": (r["summary_ko"] or "").replace("\n", " ")}
                  for r in rows.values()]
        t0 = time.time()
        result = enrich.classify_stage_rows(inputs, client, "gemini-3.1-flash-lite")
        enrich.STAGE_PROMPT = orig_prompt
        short = {h[:8]: [s, d] for h, (s, d) in result.items()}
        out_path.write_text(json.dumps(short, ensure_ascii=False, indent=1))
        print(f"{name}: {len(short)}/{len(rows)} classified in {time.time()-t0:.1f}s")
        time.sleep(4.5)

    # 채점 — v1 결과와 나란히 (신규 회귀 감시)
    print("\n=== scoring (기대값: 하이재킹 2행 §3.2 재조정 반영) ===")
    for name in ("v1_r1", "v1_r2", "v1b_r1", "v1b_r2"):
        res = json.loads((BASE / f"result_{name}.json").read_text())
        stats, fails = {}, []
        for p, exp in EXPECTED.items():
            got = res.get(p)
            g = exp["group"]
            stats.setdefault(g, [0, 0, 0])
            if got is None:
                stats[g][2] += 1
                fails.append((p, g, "MISSING", exp["new"]))
                continue
            stage_ok = got[0] in exp["new"]
            dir_ok = (exp["dir"] is None) or (got[1] == exp["dir"])
            stats[g][0] += stage_ok
            stats[g][1] += dir_ok
            if not (stage_ok and dir_ok):
                fails.append((p, g, tuple(got), exp["new"], exp["dir"]))
        line = " | ".join(f"{g}: stage {v[0]} dir {v[1]} miss {v[2]}" for g, v in sorted(stats.items()))
        print(f"{name}: {line}")
        for f in fails:
            print("   FAIL", f)


if __name__ == "__main__":
    main()
