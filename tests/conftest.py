import pytest


@pytest.fixture(autouse=True)
def stub_serving_player_names(monkeypatch):
    """serve 단위 테스트가 DB 없이 돌도록 서빙 사건 사전을 이관 명단으로 대체한다.
    실경로 (DB 조회 · env 폴백) 테스트를 쓸 땐 이 autouse 스텁이 가리므로 해제가 필요하다."""
    from bullet_in.roster_seed import ROSTER
    names = sorted((r["ko_name"] for r in ROSTER), key=len, reverse=True)
    monkeypatch.setattr("bullet_in.serve.render.load_player_names",
                        lambda engine=None: names)


@pytest.fixture(autouse=True)
def stub_loading_page_players(monkeypatch):
    """write_site 에서 선수 페이지 렌더가 DB 없이 돌도록 page_player_links 조회를 빈 목록으로 대체한다.
    선수 페이지 단위 테스트 (write_player_pages 직접 호출) 는 이 스텁을 거치지 않으므로
    저장소 연결 실패도 정상적으로 검증된다."""
    monkeypatch.setattr("bullet_in.serve.render.load_page_players",
                        lambda engine=None: [])
