from datetime import date

from docqa.usage import DailyLimit


def test_limit_blocks_after_n_requests(tmp_path):
    lim = DailyLimit(tmp_path / "usage.json", 2)
    assert lim.try_use() and lim.try_use()
    assert not lim.try_use()
    assert lim.used() == 2 and lim.remaining() == 0


def test_count_resets_on_a_new_day(tmp_path):
    day = {"d": date(2026, 11, 22)}
    lim = DailyLimit(tmp_path / "usage.json", 1, today=lambda: day["d"])
    assert lim.try_use() and not lim.try_use()
    day["d"] = date(2026, 11, 23)
    assert lim.try_use()


def test_zero_means_unlimited_and_survives_a_corrupt_file(tmp_path):
    path = tmp_path / "usage.json"
    path.write_text("not json")
    lim = DailyLimit(path, 0)
    assert all(lim.try_use() for _ in range(50))
    assert lim.remaining() is None
