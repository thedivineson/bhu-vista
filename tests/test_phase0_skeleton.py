"""
Automated Unit & Integration Tests for Phase 0: Repository Skeleton,
Configuration, Deterministic Metadata, and Health Endpoints.

Includes both success tests and strict failure cases as mandated.
"""

import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import Polygon

from config.settings import settings
from cadastre.generator import CadastralDataGenerator
from api.main import app

client = TestClient(app)


def test_version_manifest_integrity():
    """Verify that the version manifest contains all required locked dependency versions."""
    manifest_path = settings.BASE_DIR / "config" / "versions.json"
    assert manifest_path.exists(), "versions.json must exist in config/"
    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    manifest = data["version_manifest"]
    required_deps = [
        "postgresql", "postgis", "sfcgal", "redis", "fastapi",
        "celery", "pydantic", "shapely", "trimesh", "pyproj",
        "cesium", "resium"
    ]
    for dep in required_deps:
        assert dep in manifest, f"Missing dependency '{dep}' in version manifest"
        assert len(manifest[dep]) > 0, f"Version for '{dep}' must not be empty"


def test_settings_and_tolerances():
    """Verify central configuration thresholds, SRID, and confidence weight normalization."""
    assert settings.HORIZONTAL_SRID == 32643
    assert settings.HORIZONTAL_CRS == "EPSG:32643"
    assert settings.VERTICAL_DATUM == "LOCAL_GROUND_Z0"
    assert settings.Z_GROUND_LEVEL == 0.00
    assert settings.OVERLAP_TOLERANCE_M3 == 0.001
    assert settings.CONTAINMENT_TOLERANCE_M == 0.05
    assert settings.GREEN_THRESHOLD == 0.80
    assert settings.AMBER_THRESHOLD == 0.50
    assert settings.DATA_ORIGIN == "SYNTHETIC"

    # Verify confidence weights sum exactly to 1.00
    weight_sum = (
        settings.WEIGHT_REGISTRATION_RESIDUAL
        + settings.WEIGHT_POINT_CLOUD_SUPPORT
        + settings.WEIGHT_EDGE_ALIGNMENT
    )
    assert abs(weight_sum - 1.00) < 1e-6, f"Weights must sum to 1.00, got {weight_sum}"


def test_building_spec_single_source_of_truth():
    """Verify building_spec.json structure, ULPIN format, and level heights."""
    assert settings.BUILDING_SPEC_PATH.exists()
    with open(settings.BUILDING_SPEC_PATH, "r", encoding="utf-8") as f:
        spec = json.load(f)

    # 14-digit ULPIN check
    parent_ulpin = spec["parcel"]["parent_ulpin"]
    assert len(parent_ulpin) == 14 and parent_ulpin.isdigit()
    assert spec["crs"] == "EPSG:32643"
    assert spec["data_origin"] == "SYNTHETIC"

    # Level sequence check (B01, G00, F01, F02, F03)
    level_codes = [lvl["level_code"] for lvl in spec["levels"]]
    assert level_codes == ["B01", "G00", "F01", "F02", "F03"]

    # Verify basement has negative Z range and is marked subsurface
    b01 = spec["levels"][0]
    assert b01["zmin"] == -3.20 and b01["zmax"] == 0.00
    assert b01["is_subsurface"] is True


def test_cadastral_generator_execution(tmp_path: Path):
    """Verify that CadastralDataGenerator creates valid GeoJSONs and deterministic volume IDs."""
    generator = CadastralDataGenerator()
    generated = generator.run_all(output_dir=tmp_path)

    # Check parcel GeoJSON
    with open(generated["parcel"], "r", encoding="utf-8") as f:
        parcel_data = json.load(f)
    assert parcel_data["type"] == "FeatureCollection"
    assert parcel_data["features"][0]["properties"]["parent_ulpin"] == "12345678901234"
    assert parcel_data["features"][0]["properties"]["data_origin"] == "SYNTHETIC"

    # Check footprint GeoJSON
    with open(generated["footprint"], "r", encoding="utf-8") as f:
        footprint_data = json.load(f)
    assert footprint_data["type"] == "FeatureCollection"
    footprint_geom = footprint_data["features"][0]["geometry"]["coordinates"][0]
    poly_footprint = Polygon(footprint_geom)
    assert poly_footprint.is_valid
    assert poly_footprint.area == 384.0

    # Check floorplans GeoJSON
    with open(generated["floorplans"], "r", encoding="utf-8") as f:
        floorplans_data = json.load(f)
    assert len(floorplans_data["features"]) == 9  # 1 on B01 + 2 on G00 + 2 on F01 + 2 on F02 + 2 on F03

    # Check deterministic volume IDs (001 to 009)
    with open(generated["metadata"], "r", encoding="utf-8") as f:
        meta = json.load(f)
    vol_ids = [u["volume_id"] for u in meta["units"]]
    assert vol_ids == ["001", "002", "003", "004", "005", "006", "007", "008", "009"]


def test_deliberate_red_conflict_in_spec():
    """Verify that level F02 declaratively contains the 1.5m horizontal overlap between Unit 201 and 202."""
    with open(settings.BUILDING_SPEC_PATH, "r", encoding="utf-8") as f:
        spec = json.load(f)

    f02_level = next(lvl for lvl in spec["levels"] if lvl["level_code"] == "F02")
    unit_a = f02_level["units"][0]
    unit_b = f02_level["units"][1]

    poly_a = Polygon(unit_a["coordinates"])
    poly_b = Polygon(unit_b["coordinates"])

    intersection = poly_a.intersection(poly_b)
    assert intersection.is_valid
    assert not intersection.is_empty
    # Overlap area in XY must be 1.5m * 16.0m = 24.0 m2
    assert abs(intersection.area - 24.0) < 1e-4

    # 3D overlap volume: 24.0 m2 * 3.2m height = 76.80 m3
    height = f02_level["zmax"] - f02_level["zmin"]
    overlap_volume = intersection.area * height
    assert abs(overlap_volume - 76.80) < 1e-4
    assert overlap_volume > settings.OVERLAP_TOLERANCE_M3


def test_deliberate_amber_weak_evidence_in_spec():
    """Verify that level F03 Unit 302 has closed valid geometry and weak evidence attributes."""
    with open(settings.BUILDING_SPEC_PATH, "r", encoding="utf-8") as f:
        spec = json.load(f)

    f03_level = next(lvl for lvl in spec["levels"] if lvl["level_code"] == "F03")
    unit_a = f03_level["units"][0]
    unit_b = f03_level["units"][1]

    poly_b = Polygon(unit_b["coordinates"])
    assert poly_b.is_valid and poly_b.exterior.is_closed

    # Zero interior overlap with Unit A on F03 (only shared boundary line)
    poly_a = Polygon(unit_a["coordinates"])
    intersection = poly_a.intersection(poly_b)
    assert intersection.area == 0.0  # Shared boundary only, no interior overlap

    # Check weak evidence parameters
    ev = unit_b["evidence_spec"]
    assert ev["control_points_count"] == 2
    assert ev["registration_residual_m"] > 0.10
    assert ev["point_cloud_density_pct"] <= 50.0


def test_api_health_and_version_endpoints():
    """Verify API root, health, and version manifest endpoints."""
    # Root endpoint
    res_root = client.get("/")
    assert res_root.status_code == 200
    root_data = res_root.json()
    assert root_data["project"] == "BHU-VISTA 3D"
    assert root_data["data_origin"] == "SYNTHETIC"
    assert "SIMULATED / SYNTHETIC" in root_data["honest_labelling_notice"]

    # Health endpoint
    res_health = client.get("/health")
    assert res_health.status_code == 200
    health_data = res_health.json()
    assert health_data["status"] == "HEALTHY"
    assert health_data["checks"]["config_loaded"] is True
    assert health_data["tolerances"]["overlap_m3"] == 0.001

    # Manifest endpoint
    res_manifest = client.get("/api/v1/version-manifest")
    assert res_manifest.status_code == 200
    assert "postgis" in res_manifest.json()["version_manifest"]


# --- FAILURE CASES (Mandated by non-negotiable principles) ---

def test_failure_invalid_ulpin_format(tmp_path: Path):
    """Failure case: Parent ULPIN that is not a 14-digit numeric string must raise ValueError."""
    bad_spec = {
        "seed": 42,
        "data_origin": "SYNTHETIC",
        "crs": "EPSG:32643",
        "parcel": {"parent_ulpin": "INVALID_ULPIN_99"},  # Not 14 digits!
        "building_footprint": {"coordinates": []},
        "levels": []
    }
    bad_spec_file = tmp_path / "bad_ulpin_spec.json"
    with open(bad_spec_file, "w", encoding="utf-8") as f:
        json.dump(bad_spec, f)

    with pytest.raises(ValueError, match="14-digit numeric string"):
        CadastralDataGenerator(spec_path=bad_spec_file)


def test_failure_missing_required_key(tmp_path: Path):
    """Failure case: Spec missing a mandatory top-level key must raise ValueError."""
    incomplete_spec = {
        "seed": 42,
        "data_origin": "SYNTHETIC",
        # 'crs' is missing!
        "parcel": {"parent_ulpin": "12345678901234"},
        "building_footprint": {"coordinates": []},
        "levels": []
    }
    bad_spec_file = tmp_path / "missing_key_spec.json"
    with open(bad_spec_file, "w", encoding="utf-8") as f:
        json.dump(bad_spec_file.name, f)
        # Write dict
    with open(bad_spec_file, "w", encoding="utf-8") as f:
        json.dump(incomplete_spec, f)

    with pytest.raises(ValueError, match="missing required key 'crs'"):
        CadastralDataGenerator(spec_path=bad_spec_file)


def test_failure_nonexistent_spec_file(tmp_path: Path):
    """Failure case: Pointing generator to non-existent file must raise FileNotFoundError."""
    non_existent = tmp_path / "does_not_exist.json"
    with pytest.raises(FileNotFoundError):
        CadastralDataGenerator(spec_path=non_existent)
