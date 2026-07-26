from urllib.parse import quote


def build_file_link(*, name: str, size: int, file_hash: str) -> str:
    """Create an ed2k file link from a search result without trusting a client URL."""
    if not name or "|" in name or "/" in name or "\\" in name:
        raise ValueError("The eD2K filename contains unsupported path or field separators")
    if size <= 0:
        raise ValueError("The eD2K file size must be positive")
    normalized_hash = file_hash.lower()
    valid_hash = len(normalized_hash) == 32 and all(
        char in "0123456789abcdef" for char in normalized_hash
    )
    if not valid_hash:
        raise ValueError("The eD2K hash must be a 32-character MD4 hex string")
    encoded_name = quote(name, safe=" .-()[]")
    return f"ed2k://|file|{encoded_name}|{size}|{normalized_hash}|/"
