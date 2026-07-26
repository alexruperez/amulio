from amulio.cache import CandidateCache
from amulio.events import update_file_state


def test_download_and_shared_events_update_local_file_state(tmp_path):
    cache = CandidateCache(str(tmp_path / "cache.sqlite3"))
    file_hash = "a" * 32

    update_file_state("download_updated", {"hash": file_hash, "status": "downloading"}, cache)
    assert cache.file_states([file_hash]) == {file_hash: "downloading"}

    update_file_state("shared_updated", {"hash": file_hash, "path": "/data/incoming"}, cache)
    assert cache.file_states([file_hash]) == {file_hash: "ready"}
    cache.close()
