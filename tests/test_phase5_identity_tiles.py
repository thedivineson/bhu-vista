"""
Phase 5 Test Suite — 3D ULPIN Identity, 3D Tiles Exporter & API Endpoints.
Covers:
  1. 3D ULPIN string format: <ParentULPIN>|LV=<Level>|Z=<Zmin>:<Zmax>|V=<VolumeID>
  2. Automatic issuance for GREEN volumes (issuance_basis=GREEN_AUTO)
  3. Approval gate for AMBER volumes (blocked until approved -> AMBER_HUMAN_APPROVED)
  4. Hard gate: RED volumes NEVER receive a 3D ULPIN (raises PermissionError)
  5. Registry lookups (by 3D ULPIN string, by parent ULPIN, by volume ID)
  6. Pipeline versioning & re-run (version+1, volume IDs preserved, previous superseded)
  7. OGC 3D Tiles 1.1 generation & GLB binary export per level
  8. Official npx 3d-tiles-validator execution (zero errors)
  9. FastAPI HTTP endpoints integration via TestClient
"""

import re
import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import settings
from validation.service import ValidationReviewService
from identity.generator import Ulpin3DGenerator
from tiles.exporter import TileExporter
from api.main import app


# ────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def validated_vols():
    """Runs full validation once for Phase 5 tests."""
    return ValidationReviewService().run_full_validation()


@pytest.fixture(scope="module")
def vols_dict(validated_vols):
    return {v["volume_id"]: v for v in validated_vols}


@pytest.fixture(scope="module")
def id_generator():
    return Ulpin3DGenerator()


@pytest.fixture(scope="module")
def tile_exp(tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("test_tileset")
    return TileExporter(output_dir=out_dir)


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


# ────────────────────────────────────────────────────────────────
# 1. 3D ULPIN String Format
# ────────────────────────────────────────────────────────────────

def test_ulpin3d_string_format_specification():
    """Validates exact format: <ParentULPIN>|LV=<Level>|Z=<Zmin>:<Zmax>|V=<VolumeID>"""
    s = Ulpin3DGenerator.format_ulpin3d_string(
        parent_ulpin="12345678901234",
        level_code="F03",
        zmin=9.60,
        zmax=12.80,
        volume_id="008",
    )
    assert s == "12345678901234|LV=F03|Z=9.60:12.80|V=008"

    # Regex validation: 14 digits | LV=... | Z=...:... | V=3 digits
    pattern = r"^\d{14}\|LV=[A-Z0-9]{3}\|Z=-?\d+\.\d{2}:-?\d+\.\d{2}\|V=\d{3}$"
    assert re.match(pattern, s), f"String '{s}' does not match 3D ULPIN specification"


def test_ulpin3d_format_subsurface():
    """Validates 3D ULPIN formatting for negative elevation basement."""
    s = Ulpin3DGenerator.format_ulpin3d_string(
        parent_ulpin="12345678901234",
        level_code="B01",
        zmin=-3.20,
        zmax=0.00,
        volume_id="001",
    )
    assert s == "12345678901234|LV=B01|Z=-3.20:0.00|V=001"


# ────────────────────────────────────────────────────────────────
# 2. GREEN Volume Auto-Issuance
# ────────────────────────────────────────────────────────────────

def test_green_volume_auto_issuance(id_generator, vols_dict):
    """GREEN volumes (e.g. 001) are automatically issued with GREEN_AUTO basis."""
    v001 = vols_dict["001"]
    assert v001["topology_status"] == "GREEN"

    rec = id_generator.issue_ulpin3d(v001)
    assert rec["issuance_basis"] == "GREEN_AUTO"
    assert rec["volume_id"] == "001"
    assert rec["parent_ulpin"] == "12345678901234"
    assert rec["ulpin3d_string"] == "12345678901234|LV=B01|Z=-3.20:0.00|V=001"


# ────────────────────────────────────────────────────────────────
# 3. AMBER Approval Gate
# ────────────────────────────────────────────────────────────────

def test_unapproved_amber_volume_blocked(id_generator, vols_dict):
    """Unapproved AMBER volume (009 with review_status=PENDING) MUST raise PermissionError."""
    v009 = vols_dict["009"]
    assert v009["topology_status"] == "AMBER"
    assert v009["review_status"] == "PENDING"

    with pytest.raises(PermissionError, match="ERR_AMBER_UNAPPROVED"):
        id_generator.issue_ulpin3d(v009)


def test_approved_amber_volume_issued(id_generator, vols_dict):
    """Approved AMBER volume receives 3D ULPIN with AMBER_HUMAN_APPROVED basis."""
    approved_vol = dict(vols_dict["009"])
    approved_vol["review_status"] = "APPROVED"

    rec = id_generator.issue_ulpin3d(approved_vol)
    assert rec["issuance_basis"] == "AMBER_HUMAN_APPROVED"
    assert rec["volume_id"] == "009"
    assert rec["ulpin3d_string"] == "12345678901234|LV=F03|Z=9.60:12.80|V=009"


# ────────────────────────────────────────────────────────────────
# 4. RED Hard Gate (Never Issued)
# ────────────────────────────────────────────────────────────────

def test_red_volume_006_never_issued(id_generator, vols_dict):
    """Volume 006 (F02 RED conflict) CANNOT receive a 3D ULPIN under any circumstance."""
    v006 = vols_dict["006"]
    assert v006["topology_status"] == "RED"

    with pytest.raises(PermissionError, match="ERR_RED_VOLUME_INELIGIBLE"):
        id_generator.issue_ulpin3d(v006)


def test_red_volume_007_never_issued(id_generator, vols_dict):
    """Volume 007 (F02 RED encroachment) CANNOT receive a 3D ULPIN under any circumstance."""
    v007 = vols_dict["007"]
    assert v007["topology_status"] == "RED"

    with pytest.raises(PermissionError, match="ERR_RED_VOLUME_INELIGIBLE"):
        id_generator.issue_ulpin3d(v007)


# ────────────────────────────────────────────────────────────────
# 5. Batch Issuance & Registry Lookups
# ────────────────────────────────────────────────────────────────

def test_issue_all_eligible_volumes(id_generator, validated_vols):
    """issue_all_eligible issues all GREEN volumes and blocks RED/unapproved AMBER."""
    result = id_generator.issue_all_eligible(validated_vols)
    assert result["total_volumes"] == 9
    assert result["issued_count"] == 6  # 6 GREEN volumes
    assert result["blocked_count"] == 3  # 006, 007 (RED) and 009 (unapproved AMBER)

    blocked_ids = [b["volume_id"] for b in result["blocked"]]
    assert "006" in blocked_ids
    assert "007" in blocked_ids
    assert "009" in blocked_ids


def test_registry_lookup_by_string(id_generator):
    """Lookup by full 3D ULPIN string returns corresponding record."""
    ulpin_str = "12345678901234|LV=B01|Z=-3.20:0.00|V=001"
    rec = id_generator.get_by_ulpin3d(ulpin_str)
    assert rec is not None
    assert rec["volume_id"] == "001"
    assert rec["level_code"] == "B01"


def test_registry_lookup_by_parent(id_generator):
    """Lookup by parent ULPIN returns all issued child volumes."""
    records = id_generator.get_by_parent_ulpin("12345678901234")
    assert len(records) >= 6


# ────────────────────────────────────────────────────────────────
# 6. OGC 3D Tiles 1.1 Exporter
# ────────────────────────────────────────────────────────────────

def test_3d_tileset_export_structure(tile_exp, validated_vols):
    """Exports valid OGC 3D Tiles 1.1 tileset.json and per-level GLB files."""
    res = tile_exp.export_3d_tileset(validated_vols)
    assert Path(res["tileset_file"]).exists()
    assert res["levels_exported"] == 5

    # Check tileset.json structure
    tileset = res["tileset"]
    assert tileset["asset"]["version"] == "1.1"
    assert "root" in tileset
    assert "transform" in tileset["root"]
    assert len(tileset["root"]["transform"]) == 16
    assert len(tileset["root"]["children"]) == 5


def test_all_level_glb_files_exist(tile_exp):
    """Verifies that all 5 level GLB files were exported and are non-empty."""
    levels = ["B01", "G00", "F01", "F02", "F03"]
    for lvl in levels:
        glb = tile_exp.levels_dir / f"{lvl}.glb"
        assert glb.exists(), f"GLB file for level {lvl} missing"
        assert glb.stat().st_size > 1000, f"GLB file for level {lvl} unexpectedly small"


def test_npx_3d_tiles_validator_passes(tile_exp):
    """Runs official npx 3d-tiles-validator and asserts zero errors."""
    val_report = tile_exp.validate_tileset()
    assert val_report["passed"] is True, f"3D Tiles validator failed: {val_report['output']}"
    assert "numErrors\": 0" in val_report["output"] or "numErrors: 0" in val_report["output"]


# ────────────────────────────────────────────────────────────────
# 7. FastAPI Integration Endpoints
# ────────────────────────────────────────────────────────────────

def test_api_issue_green_ulpin3d(client):
    """POST /api/v1/identity/issue/001 issues 3D ULPIN for GREEN volume."""
    response = client.post("/api/v1/identity/issue/001")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ISSUED"
    assert data["ulpin3d"]["issuance_basis"] == "GREEN_AUTO"
    assert data["ulpin3d"]["volume_id"] == "001"


def test_api_issue_red_ulpin3d_fails_with_400(client):
    """POST /api/v1/identity/issue/006 (RED) MUST fail with 400 Bad Request."""
    response = client.post("/api/v1/identity/issue/006")
    assert response.status_code == 400
    assert "ERR_RED_VOLUME_INELIGIBLE" in response.json()["detail"]


def test_api_issue_unapproved_amber_fails_with_400(client):
    """POST /api/v1/identity/issue/009 (Unapproved AMBER) MUST fail with 400 Bad Request."""
    from api.main import validation_service
    validation_service._in_memory_reviews.pop("009", None)

    response = client.post("/api/v1/identity/issue/009")
    assert response.status_code == 400
    assert "ERR_AMBER_UNAPPROVED" in response.json()["detail"]


def test_api_tileset_json_endpoint(client):
    """GET /api/v1/tiles/tileset.json returns valid 3D Tiles 1.1 structure."""
    response = client.get("/api/v1/tiles/tileset.json")
    assert response.status_code == 200
    data = response.json()
    assert data["asset"]["version"] == "1.1"
    assert "root" in data


def test_api_level_glb_tile_endpoint(client):
    """GET /api/v1/tiles/levels/B01.glb returns binary GLB stream."""
    response = client.get("/api/v1/tiles/levels/B01.glb")
    assert response.status_code == 200
    assert len(response.content) > 1000
    assert response.headers["content-type"] in ("model/gltf-binary", "application/octet-stream")


def test_api_pipeline_rerun_versioning(client):
    """
    POST /api/v1/pipeline/rerun increments version, preserves volume IDs,
    and resets previous approvals per Principle 7.
    """
    response = client.post("/api/v1/pipeline/rerun")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "SUCCESS"
    assert data["new_version"] == 2
    assert data["previous_version_superseded"] is True
    # Volume IDs preserved identically ('001' to '009')
    assert data["volume_ids_preserved"] == ["001", "002", "003", "004", "005", "006", "007", "008", "009"]
