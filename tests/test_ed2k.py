import pytest

from amulio.ed2k import build_file_link


def test_build_file_link_encodes_filename_and_normalizes_hash():
    link = build_file_link(
        name="A film (2026).mkv",
        size=123,
        file_hash="ABCDEF0123456789ABCDEF0123456789",
    )

    assert link == "ed2k://|file|A film (2026).mkv|123|abcdef0123456789abcdef0123456789|/"


@pytest.mark.parametrize("name", ["", "../file.mkv", "folder/file.mkv", "a|b.mkv"])
def test_build_file_link_rejects_unsafe_names(name: str):
    with pytest.raises(ValueError):
        build_file_link(name=name, size=1, file_hash="a" * 32)
