from datetime import datetime, timezone

from bullet_in.serve import render
from bullet_in.transfer_windows import TRANSFER_WINDOWS, in_transfer_window


def _u(s):
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def test_summer_window_closes_at_23_bst():
    assert in_transfer_window(_u("2026-09-01T21:59:00"))
    assert not in_transfer_window(_u("2026-09-01T22:00:00"))


def test_winter_window_bounds():
    assert not in_transfer_window(_u("2026-12-31T23:59:00"))
    assert in_transfer_window(_u("2027-01-01T00:00:00"))
    assert not in_transfer_window(_u("2027-02-01T23:00:00"))


def test_mid_november_is_outside():
    assert not in_transfer_window(_u("2026-11-15T12:00:00"))


def test_render_uses_the_same_list():
    assert render.TRANSFER_WINDOWS is TRANSFER_WINDOWS
