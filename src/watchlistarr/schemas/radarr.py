from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class RadarrItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tmdb_id: int
    title: str | None = None
    imdb_id: str | None = None
