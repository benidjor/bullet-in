"""수집 범위 판정 — 갈래 넷과 2026-10-06 실측 제목 (설계 2026-10-07 §2)."""
import json
from pathlib import Path

import yaml

from bullet_in.scope import DROPPED_CHARS, DROPPED_MAX, ScopeRule, record, scope_names

FX = json.loads((Path(__file__).parent / "fixtures" / "scope_titles_2026-10-06.json").read_text())
KEYWORDS = yaml.safe_load(Path("config/sources.yaml").read_text())["transfer_keywords"]
EXTRAS = ["Gabriel", "Bruno", "Ødegaard"]
FULL_ONLY = ["White", "Rice", "Jesus", "Timber", "Salmon"]
NAMES = scope_names([tuple(r) for r in FX["roster"]], EXTRAS, FULL_ONLY)


def test_branches_in_order():
    rule = ScopeRule(["deal"], {"Saka"})
    assert rule.match("Arteta agrees new deal") == "keyword"
    assert rule.match("Saka signs a new deal") == "keyword"        # 처음 맞은 갈래 하나
    assert rule.match("Bournemouth to resist interest in Scott") == "extra"
    assert rule.match("Sunderland v Arsenal player ratings") == "extra"
    assert rule.match("Saka at the double for England") == "name"
    assert rule.match("Arsenal shelve plans for Emirates Stadium") == "team"
    assert rule.match("Arsenal demand meeting with Pro Ref") == "team"
    assert rule.match("Fans have their say!") is None


def test_full_only_surnames_need_full_name():
    rule = ScopeRule([], scope_names([("Declan Rice", "Rice"), ("Ben White", "White")],
                                     full_only=["Rice", "White"]))
    assert rule.match("Declan Rice scores again") == "name"
    assert rule.match("Ben White back in training") == "name"
    assert rule.match("Rice on target for England") is None
    assert rule.match("rice prices rise") is None
    assert rule.match("Spurs return to White Hart Lane") is None


def test_names_match_whole_words_only():
    rule = ScopeRule([], {"Saka", "Lewis-Skelly", "Ødegaard"})
    assert rule.match("Sakai joins Gamba Osaka") is None
    assert rule.match("Myles Lewis-Skelly nominated") == "name"
    assert rule.match("Ødegaard assists for Norway") == "name"
    assert rule.match("saka at the double") is None                 # 이름은 대소문자 구분


def test_extra_and_team_words_ignore_case():
    rule = ScopeRule([], set())
    assert rule.match("INJURY update") == "team"
    assert rule.match("Player Ratings") == "extra"
    assert rule.match("Interesting times") is None                  # 낱말 단위


def test_no_names_drops_only_the_name_branch():
    rule = ScopeRule(["deal"], set())
    assert rule.match("Saka at the double") is None
    assert rule.match("Arteta agrees new deal") == "keyword"


def test_scope_names_keeps_full_names_and_extras():
    names = scope_names([("Mikel Arteta", "Arteta"), ("Ben White", "White")],
                        extras=["Gabriel"], full_only=["White"])
    assert names == {"Mikel Arteta", "Arteta", "Ben White", "Gabriel"}


def test_record_counts_passed_and_caps_dropped():
    f = {}
    record(f, "a", "name")
    record(f, "b", "name")
    record(f, "c", "keyword")
    for _ in range(DROPPED_MAX + 5):
        record(f, "x" * (DROPPED_CHARS + 30), None)
    assert f["passed_by"] == {"name": 2, "keyword": 1}
    assert len(f["dropped"]) == DROPPED_MAX
    assert all(len(t) == DROPPED_CHARS for t in f["dropped"])


def _split(titles, rule):
    out = {}
    for t in titles:
        r = rule.match(t)
        if r:
            out[r] = out.get(r, 0) + 1
    return out


def test_press_titles_measured_on_2026_10_06():
    """설계 §2.3 의 결과표를 그대로 고정한다."""
    rule = ScopeRule(KEYWORDS, NAMES)
    assert _split(FX["press"]["bbc_sport"], rule) == {"keyword": 5, "extra": 2, "name": 7, "team": 1}
    assert _split(FX["press"]["skysports"], rule) == {"keyword": 3, "name": 4}
    assert _split(FX["press"]["guardian"], rule) == {"keyword": 1, "name": 6, "team": 2}


def test_names_ignore_diacritics():
    rule = ScopeRule([], {"Viktor Gyokeres", "Gyokeres", "Ødegaard"})
    assert rule.match("Viktor Gyökeres the difference as Arsenal claim nervy win") == "name"
    assert rule.match("Odegaard assists for Norway") == "name"
    assert rule.match("gyökeres") is None                            # 대소문자 구분은 그대로


def test_new_extra_words():
    rule = ScopeRule([], set())
    assert rule.match("Timber hits 100 Arsenal appearances against Forest") == "extra"
    assert rule.match("Team news: Six changes made for Slavia Prague showdown") == "extra"
    assert rule.match("Teams newsletter") is None


def test_report_and_preview_prefix():
    rule = ScopeRule([], set())
    assert rule.match("Report: Liverpool 0-1 Arsenal") == "report"
    assert rule.match("Preview: Arsenal v Hull City") == "report"
    assert rule.match("Match report on Arsenal") is None


def test_surname_only_title_is_confirmed_by_full_name_in_context():
    rule = ScopeRule([], scope_names([("Ben White", "White"), ("Declan Rice", "Rice")],
                                     full_only=["White", "Rice"]),
                     confirm={"White": "Ben White", "Rice": "Declan Rice"})
    t = "Tuchel defends White after more Wembley boos"
    assert rule.needs_context(t)
    assert rule.match(t) is None
    assert rule.match(t, context="England manager Thomas Tuchel defended Ben White.") == "fullname"
    assert rule.match("Toure recalls winning the league at White Hart Lane",
                      context="Kolo Toure on Arsenal at White Hart Lane") is None
    assert rule.match("PSG could rival Arsenal for Gibbs-White",
                      context="Nottingham Forest's Morgan Gibbs-White") is None
    assert rule.match("Rice relishing title race", context="") is None
    assert not rule.needs_context("Arsenal back at Highbury")


def test_config_covers_new_transfer_words_and_aliases():
    cfg = yaml.safe_load(Path("config/sources.yaml").read_text())
    assert {"sale", "monitor"} <= set(cfg["transfer_keywords"])
    assert {"Gabi", "Ezri"} <= set(cfg["scope_name_extras"])
    rule = ScopeRule(cfg["transfer_keywords"], set(cfg["scope_name_extras"]))
    assert rule.match("Arsenal monitor Leverkusen striker Kofane") == "keyword"
    assert rule.match("Big Gabi enjoys latest clean sheet") == "name"
