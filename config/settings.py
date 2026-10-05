"""
Central configuration settings for BHU-VISTA 3D (Aayam).
Single source of truth for CRS, vertical datum, tolerance thresholds,
confidence weights, and validation gates.
"""

from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # Project Identity
    PROJECT_NAME: str = "BHU-VISTA 3D"
    PROJECT_SUBTITLE: str = "Aayam – Convert to Higher Dimensions"
    SIH_PROBLEM_STATEMENT: str = "SIH26011"
    TEAM_NAME: str = "Syndicate"
    TEAM_ID: str = "127351"
    ALGORITHM_VERSION: str = "1.0.0"

    # Data Origin & Provenance
    DATA_ORIGIN: str = "SYNTHETIC"  # SYNTHETIC | SIMULATED | AUTHORITATIVE
    FIXED_RANDOM_SEED: int = 42

    # Coordinate Reference System (CRS) & Vertical Datum
    # Pinned to EPSG:32643 (WGS 84 / UTM zone 43N, suitable for Mumbai/Western India)
    HORIZONTAL_SRID: int = 32643
    HORIZONTAL_CRS: str = "EPSG:32643"
    
    # Vertical Datum:
    # MVP uses synthetic local ground datum at entrance (Z_ground = 0.00m).
    # Normalised height H = Z - Z_ground.
    # Production Risk/Roadmap: Must map to orthometric datum (e.g., EGM2008 via PROJ).
    VERTICAL_DATUM: str = "LOCAL_GROUND_Z0"
    Z_GROUND_LEVEL: float = 0.00
    
    # Cesium Conversion Target
    CESIUM_TARGET_CRS: str = "EPSG:4326"

    # Spatial & Volumetric Tolerances
    OVERLAP_TOLERANCE_M3: float = Field(
        default=0.001,
        description="Exclusive 3D intersection volume threshold in m3. Volumes sharing more than this are flagged as an overlap conflict."
    )
    CONTAINMENT_TOLERANCE_M: float = Field(
        default=0.05,
        description="Tolerance in metres for verifying unit polygon containment within the parent footprint envelope."
    )
    ENVELOPE_XY_TOLERANCE_M: float = Field(
        default=0.15,
        description="Tolerance in metres for exterior wall offset / building envelope."
    )

    # Topology & Confidence Gate Thresholds
    GREEN_THRESHOLD: float = Field(
        default=0.80,
        description="Minimum confidence score required for automatic 3D ULPIN issuance (GREEN)."
    )
    AMBER_THRESHOLD: float = Field(
        default=0.50,
        description="Scores between AMBER_THRESHOLD and GREEN_THRESHOLD require human review (AMBER)."
    )

    # Confidence Score Component Weights (Sum = 1.00)
    # Formula: Confidence = (W_reg * S_reg) + (W_pc * S_pc) + (W_edge * S_edge)
    WEIGHT_REGISTRATION_RESIDUAL: float = 0.40
    WEIGHT_POINT_CLOUD_SUPPORT: float = 0.40
    WEIGHT_EDGE_ALIGNMENT: float = 0.20

    # Paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    SAMPLE_DATA_DIR: Path = BASE_DIR / "sample_data"
    BUILDING_SPEC_PATH: Path = SAMPLE_DATA_DIR / "building_spec.json"

    # Database & Redis Settings
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/bhuvista3d"
    REDIS_URL: str = "redis://localhost:6379/0"

    model_config = {"env_file": ".env", "case_sensitive": True, "extra": "ignore"}


# Global settings singleton
settings = Settings()

