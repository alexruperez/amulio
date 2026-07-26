from pydantic import BaseModel, Field


class AmuleSearchResult(BaseModel):
    hash: str = Field(pattern=r"^[0-9a-fA-F]{32}$")
    name: str
    size: int = Field(gt=0)
    sources: dict[str, int] = Field(default_factory=dict)
    already_have: bool = False
    status: str = "new"


class AmuleFile(BaseModel):
    hash: str = Field(pattern=r"^[0-9a-fA-F]{32}$")
    name: str
    size: int = Field(gt=0)
    path: str
    status: str | None = None


class Candidate(BaseModel):
    hash: str = Field(pattern=r"^[0-9a-fA-F]{32}$")
    name: str
    size: int = Field(gt=0)
    sources_total: int = 0
    sources_complete: int = 0
    ed2k_link: str
    quality: str | None = None
    score: int = 0
