# backend/app/config.py
import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class Corridor(BaseModel):
    bbox: tuple[float, float, float, float]  # lat_min, lon_min, lat_max, lon_max
    note: str | None = None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    aisstream_api_key: str = ""
    eia_api_key: str = ""
    alphavantage_api_key: str = ""
    opensanctions_api_key: str = ""
    fred_api_key: str = ""

    @property
    def corridors(self) -> dict[str, Corridor]:
        raw = json.loads((DATA_DIR / "corridors.json").read_text())
        return {name: Corridor(**value) for name, value in raw.items()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
