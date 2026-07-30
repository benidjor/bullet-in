import pytest


@pytest.fixture(autouse=True)
def stub_serving_player_names(monkeypatch):
    """serve 단위 테스트가 DB 없이 돌도록 서빙 사건 사전을 이관 명단으로 대체한다."""
    from bullet_in.roster_seed import ROSTER
    names = sorted((r["ko_name"] for r in ROSTER), key=len, reverse=True)
    monkeypatch.setattr("bullet_in.serve.render.load_player_names",
                        lambda engine=None: names)
