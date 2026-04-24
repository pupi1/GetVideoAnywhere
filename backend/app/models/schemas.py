from typing import Any
from pydantic import BaseModel, Field, HttpUrl


class ParseRequest(BaseModel):
    url: HttpUrl


class DownloadRequest(BaseModel):
    url: HttpUrl
    format_id: str | None = None
    filename_prefix: str | None = None


class BatchDownloadRequest(BaseModel):
    urls: list[HttpUrl] = Field(min_length=1, max_length=20)
    format_id: str | None = None


class AITextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    target_language: str | None = "zh"


class APIResponse(BaseModel):
    success: bool = True
    message: str = "ok"
    data: Any | None = None
