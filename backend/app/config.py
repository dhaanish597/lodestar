# backend/app/config.py
import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class Corridor(BaseModel):
    bbox: tuple[float, float, float, float]  # lat_min, lon_min, lat_max, lon_max
    note: str | None = None

    def contains(self, lat: float, lon: float) -> bool:
        lat_min, lon_min, lat_max, lon_max = self.bbox
        return lat_min <= lat <= lat_max and lon_min <= lon <= lon_max


class AisBox(BaseModel):
    """A bounding box in the single AISStream subscription.

    AISStream accepts multiple boxes in one subscription's ``BoundingBoxes``
    field. Boxes are configured in ``backend/data/ais_boxes.json`` — see the
    "AIS coverage reality" note in docs/03 for why we subscribe beyond Hormuz.
    ``corridor`` links a box to the corridor whose risk features it feeds
    (null for boxes that only supply map evidence).
    """

    bbox: tuple[float, float, float, float]  # lat_min, lon_min, lat_max, lon_max
    corridor: str | None = None
    note: str | None = None

    def contains(self, lat: float, lon: float) -> bool:
        lat_min, lon_min, lat_max, lon_max = self.bbox
        return lat_min <= lat <= lat_max and lon_min <= lon <= lon_max


class CrudeGrade(BaseModel):
    grade: str
    origin: str
    api_gravity: float
    sulfur_pct: float
    class_: str = Field(alias="class")
    voyage_days: float
    price_differential_usd_bbl: float
    base_congestion_penalty: float
    grade_match: float
    best_fit_refineries: list[str]


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

    @property
    def ais_boxes(self) -> dict[str, AisBox]:
        raw = json.loads((DATA_DIR / "ais_boxes.json").read_text())
        return {name: AisBox(**value) for name, value in raw.items()}

    @property
    def crude_grades(self) -> list[CrudeGrade]:
        raw = json.loads((DATA_DIR / "crude_grades.json").read_text())
        return [CrudeGrade(**g) for g in raw["grades"]]


@lru_cache
def get_settings() -> Settings:
    return Settings()
