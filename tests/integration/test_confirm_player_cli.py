from bullet_in.confirm_player import main
from bullet_in.storage.players import PlayerStore
from tests.integration.conftest import TEST_URL


def test_main_blocks_ko_name_conflict(engine, monkeypatch):
    # main() 이 자체 엔진을 os.environ["MARIADB_URL"] 로 여는 경로를 그대로 태워
    # store 조회가 아니라 CLI 전체 경로에서 충돌 차단이 걸리는지 고정한다 (이월 지시).
    monkeypatch.setenv("MARIADB_URL", TEST_URL)
    store = PlayerStore(engine)

    pid_a = store.insert_candidate(full_name="Nico Williams", first_name="Nico",
                                   surname="Williams", ko_candidate="테스트표기",
                                   first_seen=None)
    store.confirm(pid_a, ko_name="테스트표기", category="external",
                  transfer_status="in_link", club="Athletic Club")

    pid_b = store.insert_candidate(full_name="Inaki Williams", first_name="Inaki",
                                   surname="Williams", ko_candidate="이냐키 윌리엄스",
                                   first_seen=None)

    rc = main(["--name", "Inaki Williams", "--ko", "테스트표기"])

    assert rc == 1
    b = store.get_player("Inaki Williams")
    assert b["id"] == pid_b
    assert b["status"] == "candidate"      # confirm 이 호출되지 않고 그대로 유지
    assert b["ko_name"] is None
