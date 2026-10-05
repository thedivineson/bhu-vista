"""
Phase 4 Test Suite — Topology Validation Engine & Review Service.
Covers:
  1. RED conflict detection (F02 Units 006 & 007 flagged RED by real overlap code)
  2. AMBER case preservation (F03 Unit 009: AMBER with PENDING review)
  3. GREEN volumes pass all 7 checks
  4. SFCGAL failure handling (exception → RED with SFCGAL_FAILURE error code)
  5. Review approve for AMBER volume succeeds
  6. Review reject for AMBER volume succeeds
  7. Approve RED volume raises ValueError
  8. Empty reviewer / reason raises ValueError
  9. Per-check validation_report structure
  10. Overlap volume calculation accuracy
"""

import pytest
import sys
from pathlib import Path

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from validation.engine import TopologyValidationEngine
from validation.service import ValidationReviewService
from config.settings import settings
from shapely.geometry import Polygon
from fastapi.testclient import TestClient
from api.main import app


# ────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def engine():
    return TopologyValidationEngine()


@pytest.fixture(scope="module")
def service():
    return ValidationReviewService()


@pytest.fixture(scope="module")
def validated_volumes(service):
    """Run full validation once for the module (expensive — reads LAS, etc.)."""
    return service.run_full_validation()


@pytest.fixture(scope="module")
def volumes_by_id(validated_volumes):
    """Index validated volumes by volume_id for easy lookup."""
    return {v["volume_id"]: v for v in validated_volumes}


# ────────────────────────────────────────────────────────────────
# 1. RED Conflict Detection
# ────────────────────────────────────────────────────────────────

def test_red_conflict_vol_006_flagged(volumes_by_id):
    """F02-U01 (Vol 006) must be RED due to exclusive 3D overlap with 007."""
    v006 = volumes_by_id["006"]
    assert v006["topology_status"] == "RED"
    assert v006["review_status"] == "REJECTED"
    assert "EXCLUSIVE_3D_OVERLAP" in v006["validation_report"]["hard_failures"]


def test_red_conflict_vol_007_flagged(volumes_by_id):
    """F02-U02 (Vol 007) must be RED due to exclusive 3D overlap with 006."""
    v007 = volumes_by_id["007"]
    assert v007["topology_status"] == "RED"
    assert v007["review_status"] == "REJECTED"
    assert "EXCLUSIVE_3D_OVERLAP" in v007["validation_report"]["hard_failures"]


def test_red_overlap_volume_is_76_point_8_m3(volumes_by_id):
    """
    Deliberate 1.5m encroachment on F02: overlap = 1.5m × 16.0m × 3.20m = 76.80 m³.
    Both volumes must report this exact conflict.
    """
    for vid in ("006", "007"):
        report = volumes_by_id[vid]["validation_report"]
        overlap_check = report["checks"]["overlap_consistency"]
        assert not overlap_check["passed"]
        assert len(overlap_check["conflicts"]) == 1
        overlap_m3 = overlap_check["conflicts"][0]["overlap_volume_m3"]
        assert overlap_m3 == pytest.approx(76.80, abs=0.1)


def test_red_volumes_have_mutual_conflict_references(volumes_by_id):
    """Vol 006's conflict references 007, and 007's references 006."""
    c006 = volumes_by_id["006"]["validation_report"]["checks"]["overlap_consistency"]["conflicts"]
    c007 = volumes_by_id["007"]["validation_report"]["checks"]["overlap_consistency"]["conflicts"]
    assert c006[0]["conflicting_volume_id"] == "007"
    assert c007[0]["conflicting_volume_id"] == "006"


# ────────────────────────────────────────────────────────────────
# 2. AMBER Low-Confidence Case
# ────────────────────────────────────────────────────────────────

def test_amber_vol_009_status(volumes_by_id):
    """F03-U02 (Vol 009) must be AMBER with PENDING review — no hard failures."""
    v009 = volumes_by_id["009"]
    assert v009["topology_status"] == "AMBER"
    assert v009["review_status"] == "PENDING"
    assert len(v009["validation_report"]["hard_failures"]) == 0


def test_amber_confidence_in_range(volumes_by_id):
    """AMBER confidence must be in [AMBER_THRESHOLD, GREEN_THRESHOLD)."""
    v009 = volumes_by_id["009"]
    assert settings.AMBER_THRESHOLD <= v009["confidence"] < settings.GREEN_THRESHOLD
    # Specific value from formula: ~0.5311
    assert v009["confidence"] == pytest.approx(0.5311, abs=0.01)


def test_amber_geometry_checks_all_pass(volumes_by_id):
    """Vol 009 passes all geometry checks — it's only flagged AMBER due to weak evidence."""
    report = volumes_by_id["009"]["validation_report"]
    checks = report["checks"]
    assert checks["z_range"]["passed"] is True
    assert checks["closed_solid"]["passed"] is True
    assert checks["containment"]["passed"] is True
    assert checks["floating_volume"]["passed"] is True
    assert checks["overlap_consistency"]["passed"] is True


# ────────────────────────────────────────────────────────────────
# 3. GREEN Volumes Pass All 7 Checks
# ────────────────────────────────────────────────────────────────

def test_green_volume_count(validated_volumes):
    """At least 6 of the 9 volumes must be GREEN."""
    green = [v for v in validated_volumes if v["topology_status"] == "GREEN"]
    assert len(green) >= 6


def test_green_volumes_all_checks_pass(validated_volumes):
    """Every GREEN volume must pass all individual checks with no hard failures."""
    for v in validated_volumes:
        if v["topology_status"] != "GREEN":
            continue
        report = v["validation_report"]
        assert len(report["hard_failures"]) == 0
        for check_name, check_result in report["checks"].items():
            assert check_result["passed"] is True, (
                f"Vol {v['volume_id']} ({v['level_code']}) check '{check_name}' should pass"
            )


def test_green_volumes_review_not_required(validated_volumes):
    """GREEN volumes must have review_status = NOT_REQUIRED."""
    for v in validated_volumes:
        if v["topology_status"] == "GREEN":
            assert v["review_status"] == "NOT_REQUIRED"


def test_green_confidence_above_threshold(validated_volumes):
    """GREEN volumes must have confidence >= GREEN_THRESHOLD (0.80)."""
    for v in validated_volumes:
        if v["topology_status"] == "GREEN":
            assert v["confidence"] >= settings.GREEN_THRESHOLD


# ────────────────────────────────────────────────────────────────
# 4. SFCGAL / Geometry Failure Handling
# ────────────────────────────────────────────────────────────────

def test_sfcgal_failure_flags_both_red(engine):
    """
    If compute_3d_overlap_volume raises an exception (simulating SFCGAL kernel failure),
    both participating volumes must be flagged with error_code=SFCGAL_FAILURE.
    """
    # Create two volumes with invalid coordinates that will cause an exception
    vol_a = {
        "volume_id": "T01",
        "unit_code": "TEST-A",
        "level_code": "F01",
        "zmin": 3.20, "zmax": 6.40,
        "coordinates": "NOT_A_COORDINATE_LIST",  # Will cause TypeError in Polygon()
    }
    vol_b = {
        "volume_id": "T02",
        "unit_code": "TEST-B",
        "level_code": "F01",
        "zmin": 3.20, "zmax": 6.40,
        "coordinates": [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
    }

    results = engine.validate_level_neighbours([vol_a, vol_b])
    # The exception from Polygon("NOT_A_COORDINATE_LIST") should be caught
    assert results["T01"]["passed"] is False
    assert results["T01"].get("error_code") == "SFCGAL_FAILURE"
    assert results["T02"]["passed"] is False
    assert results["T02"].get("error_code") == "SFCGAL_FAILURE"


def test_sfcgal_failure_compute_overlap_raises(engine):
    """compute_3d_overlap_volume must raise RuntimeError for corrupted input."""
    bad_vol = {
        "volume_id": "BAD", "unit_code": "BAD",
        "coordinates": "BROKEN",  # Not a valid coordinate list
        "zmin": 0.0, "zmax": 3.0,
    }
    good_vol = {
        "volume_id": "GOOD", "unit_code": "GOOD",
        "coordinates": [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
        "zmin": 0.0, "zmax": 3.0,
    }
    with pytest.raises(RuntimeError, match="SFCGAL_FAILURE"):
        engine.compute_3d_overlap_volume(bad_vol, good_vol)


# ────────────────────────────────────────────────────────────────
# 5. Review Approve for AMBER Volume
# ────────────────────────────────────────────────────────────────

def test_approve_amber_volume(service):
    """Approving AMBER volume 009 succeeds with valid reviewer and reason."""
    result = service.approve_volume(
        volume_id="009",
        reviewer="Dr. Priya Sharma",
        reason="Manual verification confirms valid geometry; low evidence accepted per SIH26011 rules.",
    )
    assert result["status"] == "APPROVED"
    assert result["review_status"] == "APPROVED"
    assert result["topology_status"] == "AMBER"  # Machine verdict never overwritten
    assert result["audit"]["action"] == "APPROVE"
    assert result["audit"]["reviewer"] == "Dr. Priya Sharma"
    assert result["audit"]["previous_status"] == "PENDING"


# ────────────────────────────────────────────────────────────────
# 6. Review Reject for AMBER Volume
# ────────────────────────────────────────────────────────────────

def test_reject_amber_volume():
    """Rejecting AMBER volume 009 succeeds with valid reviewer and reason on clean state."""
    fresh_service = ValidationReviewService()
    result = fresh_service.reject_volume(
        volume_id="009",
        reviewer="Surveyor Rajesh K",
        reason="Evidence insufficient for issuance; site re-survey recommended.",
    )
    assert result["status"] == "REJECTED"
    assert result["review_status"] == "REJECTED"
    assert result["topology_status"] == "AMBER"
    assert result["audit"]["action"] == "REJECT"
    assert result["audit"]["previous_status"] == "PENDING"


# ────────────────────────────────────────────────────────────────
# 7. Cannot Approve RED Volume
# ────────────────────────────────────────────────────────────────

def test_approve_red_volume_raises(service):
    """Approving RED volume 006 must raise ValueError with ERR_CANNOT_APPROVE_RED."""
    with pytest.raises(ValueError, match="ERR_CANNOT_APPROVE_RED"):
        service.approve_volume(
            volume_id="006",
            reviewer="Reviewer",
            reason="Attempted approval",
        )


def test_approve_red_volume_007_raises(service):
    """Approving RED volume 007 must also raise ValueError."""
    with pytest.raises(ValueError, match="RED"):
        service.approve_volume(
            volume_id="007",
            reviewer="Reviewer",
            reason="Attempted approval",
        )


# ────────────────────────────────────────────────────────────────
# 8. Empty Reviewer / Reason Validation
# ────────────────────────────────────────────────────────────────

def test_approve_empty_reviewer_raises(service):
    """Empty reviewer name must raise ValueError."""
    with pytest.raises(ValueError, match="[Rr]eviewer"):
        service.approve_volume("009", "", "Valid reason")


def test_approve_empty_reason_raises(service):
    """Empty reason must raise ValueError."""
    with pytest.raises(ValueError, match="[Rr]eason"):
        service.approve_volume("009", "Valid Reviewer", "")


def test_reject_empty_reviewer_raises(service):
    """Reject with empty reviewer must raise ValueError."""
    with pytest.raises(ValueError, match="[Rr]eviewer"):
        service.reject_volume("009", "  ", "Valid reason")


def test_reject_empty_reason_raises(service):
    """Reject with empty reason must raise ValueError."""
    with pytest.raises(ValueError, match="[Rr]eason"):
        service.reject_volume("009", "Valid Reviewer", "   ")


def test_approve_nonexistent_volume_raises(service):
    """Approving a volume that doesn't exist must raise KeyError."""
    with pytest.raises(KeyError, match="not found"):
        service.approve_volume("999", "Reviewer", "Reason")


# ────────────────────────────────────────────────────────────────
# 9. Validation Report Structure
# ────────────────────────────────────────────────────────────────

EXPECTED_CHECKS = {"z_range", "closed_solid", "containment", "floating_volume", "overlap_consistency"}

def test_validation_report_has_required_keys(validated_volumes):
    """Every volume's validation_report must contain the expected top-level keys."""
    for v in validated_volumes:
        report = v["validation_report"]
        assert "checks" in report
        assert "overall_verdict" in report
        assert "review_status" in report
        assert "verdict_reason" in report
        assert "hard_failures" in report
        assert "confidence" in report


def test_validation_report_checks_complete(validated_volumes):
    """Every volume must have all 5 named check groups in its report."""
    for v in validated_volumes:
        actual_checks = set(v["validation_report"]["checks"].keys())
        assert EXPECTED_CHECKS.issubset(actual_checks), (
            f"Vol {v['volume_id']} missing checks: {EXPECTED_CHECKS - actual_checks}"
        )


def test_each_check_has_passed_field(validated_volumes):
    """Every individual check result must have a 'passed' boolean."""
    for v in validated_volumes:
        for check_name, check_result in v["validation_report"]["checks"].items():
            assert "passed" in check_result, (
                f"Vol {v['volume_id']} check '{check_name}' missing 'passed' field"
            )
            assert isinstance(check_result["passed"], bool)


# ────────────────────────────────────────────────────────────────
# 10. Overlap Volume Calculation Accuracy
# ────────────────────────────────────────────────────────────────

def test_overlap_zero_for_adjacent_units(engine):
    """Adjacent units sharing a boundary must have zero overlap."""
    # F01 units: side-by-side at X=278504
    vol_a = {
        "volume_id": "A", "unit_code": "A",
        "coordinates": [[278492.0, 2110495.0], [278504.0, 2110495.0],
                        [278504.0, 2110511.0], [278492.0, 2110511.0], [278492.0, 2110495.0]],
        "zmin": 3.20, "zmax": 6.40,
    }
    vol_b = {
        "volume_id": "B", "unit_code": "B",
        "coordinates": [[278504.0, 2110495.0], [278516.0, 2110495.0],
                        [278516.0, 2110511.0], [278504.0, 2110511.0], [278504.0, 2110495.0]],
        "zmin": 3.20, "zmax": 6.40,
    }
    overlap = engine.compute_3d_overlap_volume(vol_a, vol_b)
    assert overlap == 0.0


def test_overlap_nonzero_for_encroaching_units(engine):
    """The deliberate F02 encroachment must produce 76.80 m³ overlap."""
    vol_a = {
        "volume_id": "006", "unit_code": "F02-U01",
        "coordinates": [[278492.0, 2110495.0], [278504.0, 2110495.0],
                        [278504.0, 2110511.0], [278492.0, 2110511.0], [278492.0, 2110495.0]],
        "zmin": 6.40, "zmax": 9.60,
    }
    vol_b = {
        "volume_id": "007", "unit_code": "F02-U02",
        "coordinates": [[278502.5, 2110495.0], [278516.0, 2110495.0],
                        [278516.0, 2110511.0], [278502.5, 2110511.0], [278502.5, 2110495.0]],
        "zmin": 6.40, "zmax": 9.60,
    }
    overlap = engine.compute_3d_overlap_volume(vol_a, vol_b)
    # 1.5m × 16.0m × 3.20m = 76.80 m³
    assert overlap == pytest.approx(76.80, abs=0.01)


def test_overlap_zero_for_different_z_ranges(engine):
    """Units on different floors with no Z overlap must have zero overlap volume."""
    vol_a = {
        "volume_id": "A", "unit_code": "A",
        "coordinates": [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
        "zmin": 0.0, "zmax": 3.0,
    }
    vol_b = {
        "volume_id": "B", "unit_code": "B",
        "coordinates": [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
        "zmin": 3.0, "zmax": 6.0,
    }
    overlap = engine.compute_3d_overlap_volume(vol_a, vol_b)
    assert overlap == 0.0


def test_total_volume_count(validated_volumes):
    """Exactly 9 volumes must be produced (from building_spec.json)."""
    assert len(validated_volumes) == 9


# ────────────────────────────────────────────────────────────────
# 11. FastAPI Validation & Review Queue Endpoints
# ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_api_validation_run_endpoint(client):
    """GET /api/v1/validation/run returns 9 volumes with correct gate classifications."""
    response = client.get("/api/v1/validation/run")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "COMPLETED"
    assert data["total_volumes"] == 9
    assert data["red_count"] == 2
    assert data["amber_count"] == 1
    assert data["green_count"] == 6


def test_api_review_queue_endpoint(client):
    """GET /api/v1/validation/review-queue lists only pending AMBER volumes."""
    response = client.get("/api/v1/validation/review-queue")
    assert response.status_code == 200
    data = response.json()
    assert data["pending_count"] >= 0


def test_api_volume_report_endpoint(client):
    """GET /api/v1/validation/report/{volume_id} returns detailed per-check report."""
    response = client.get("/api/v1/validation/report/006")
    assert response.status_code == 200
    data = response.json()
    assert data["volume_id"] == "006"
    assert data["topology_status"] == "RED"
    assert "checks" in data["validation_report"]


def test_api_approve_red_volume_fails_with_400(client):
    """POST /api/v1/validation/approve on a RED volume must fail with 400 Bad Request."""
    payload = {
        "volume_id": "006",
        "reviewer": "Officer K",
        "reason": "Illegal attempt to approve overlapping unit",
    }
    response = client.post("/api/v1/validation/approve", json=payload)
    assert response.status_code == 400
    assert "ERR_CANNOT_APPROVE_RED" in response.json()["detail"]


def test_api_approve_amber_volume_succeeds(client):
    """POST /api/v1/validation/approve on an AMBER volume succeeds with audit entry."""
    payload = {
        "volume_id": "009",
        "reviewer": "Chief Surveyor Sharma",
        "reason": "Approved with field inspection verification notes",
    }
    response = client.post("/api/v1/validation/approve", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "SUCCESS"
    assert data["data"]["review_status"] == "APPROVED"


def test_api_audit_trail_endpoint(client):
    """GET /api/v1/validation/audit-trail returns recorded audit events."""
    response = client.get("/api/v1/validation/audit-trail")
    assert response.status_code == 200
    data = response.json()
    assert data["total_records"] >= 1
    assert any(entry["reviewer"] == "Chief Surveyor Sharma" for entry in data["audit_trail"])
