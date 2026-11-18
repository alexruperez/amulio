from amulio.download_manager import public_download


def test_public_download_bounds_completed_bytes_for_progress_rendering():
    item = {"hash": "A" * 32, "name": "active.mkv", "size": 100, "size_done": 140}

    assert public_download(item) == {
        "hash": "a" * 32,
        "name": "active.mkv",
        "size": 100,
        "size_done": 100,
        "speed_bps": 0,
        "status": "unknown",
    }
    assert public_download({**item, "size_done": -1})["size_done"] == 0
