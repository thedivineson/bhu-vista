"""
Automated Unit & Integration Tests for Phase 3: Floor-Plan Registration,
Unit Subdivision, 3D Closed Solid Extrusion, and Evidence Binding.

Tests verify:
1. 2D similarity transform accuracy and residual RMSE computation.
2. Deterministic volume ID sequencing (001 to 009).
3. Evidence binding per volume (control points, residual, point cloud density).
4. Deliberate AMBER case natural emergence (confidence ~0.53 in [0.50, 0.80)).
5. Deliberate RED conflict volumes built with 76.80 m3 intersection.
6. Strict failure cases (insufficient control points, invalid vertical bounds).
"""

from pathlib import Path
import numpy as np
import pytest
from shapely.geometry import Polygon

from config.settings import settings
from cadastre.registration import FloorplanRegistrationEngine
from cadastre.volume_builder import VolumeBuilder


def test_registration_least_squares_accuracy():
    """Verify 2D similarity transformation computes exact translation and scale with zero RMSE."""
    src = np.array([[0.0, 0.0], [24.0, 0.0], [24.0, 16.0], [0.0, 16.0]])
    dst = np.array([
        [278492.0, 2110495.0],
        [278516.0, 2110495.0],
        [278516.0, 2110511.0],
        [278492.0, 2110511.0],
    ])

    matrix, rmse = FloorplanRegistrationEngine.compute_similarity_transform(src, dst)
    # Check scale factor a ~ 1.0, b ~ 0.0, translation ~ (278492, 2110495)
    assert abs(matrix[0] - 1.0) < 1e-6
    assert abs(matrix[1] - 0.0) < 1e-6
    assert abs(matrix[4] - 278492.0) < 1e-4
    assert abs(matrix[5] - 2110495.0) < 1e-4
    assert rmse < 1e-4, f"Registration RMSE {rmse} should be near zero for exact points"


def test_registration_transform_polygon():
    """Verify transforming local unit polygon preserves area and maps to expected GIS coordinates."""
    local_poly = Polygon([[0.0, 0.0], [12.0, 0.0], [12.0, 16.0], [0.0, 16.0], [0.0, 0.0]])
    matrix = [1.0, 0.0, 0.0, 1.0, 278492.0, 2110495.0]

    world_poly = FloorplanRegistrationEngine.transform_polygon(local_poly, matrix)
    assert world_poly.is_valid
    assert abs(world_poly.area - 192.0) < 1e-6
    min_x, min_y, max_x, max_y = world_poly.bounds
    assert abs(min_x - 278492.0) < 1e-4
    assert abs(max_x - 278504.0) < 1e-4


def test_volume_builder_deterministic_order():
    """Verify that all 9 volumes are built in strict deterministic order (001 to 009)."""
    builder = VolumeBuilder()
    volumes = builder.build_all_volumes()

    assert len(volumes) == 9, f"Expected 9 volumes, got {len(volumes)}"
    vol_ids = [v["volume_id"] for v in volumes]
    assert vol_ids == ["001", "002", "003", "004", "005", "006", "007", "008", "009"]

    # Verify bottom-to-top Zmin progression
    zmins = [v["zmin"] for v in volumes]
    assert zmins[0] == -3.20  # B01 basement
    assert zmins[1] == 0.00   # G00
    assert zmins[2] == 0.00   # G00
    assert zmins[3] == 3.20   # F01
    assert zmins[4] == 3.20   # F01
    assert zmins[5] == 6.40   # F02
    assert zmins[6] == 6.40   # F02
    assert zmins[7] == 9.60   # F03
    assert zmins[8] == 9.60   # F03


def test_volume_builder_evidence_binding():
    """Verify that every volume includes bound empirical evidence metrics."""
    builder = VolumeBuilder()
    volumes = builder.build_all_volumes()

    for v in volumes:
        ev = v["evidence"]
        assert "control_points_count" in ev
        assert "registration_residual_m" in ev
        assert "point_density_pct" in ev
        assert "confidence_score" in ev
        assert ev["confidence_score"] == v["confidence"]
        assert v["data_origin"] == "SYNTHETIC"
        assert v["version"] == 1
        assert v["superseded"] is False


def test_deliberate_amber_confidence_formula():
    """
    CRITICAL DELIBERATE TEST CASE:
    Proves that Unit 302 on F03 naturally evaluates to AMBER (0.50 <= Conf < 0.80),
    while Unit 301 on F03 evaluates to GREEN (Conf >= 0.80).
    """
    builder = VolumeBuilder()
    volumes = builder.build_all_volumes()

    vol_301 = next(v for v in volumes if v["unit_code"] == "F03-U01")
    vol_302 = next(v for v in volumes if v["unit_code"] == "F03-U02")

    # Unit 301 is GREEN
    assert vol_301["confidence"] >= settings.GREEN_THRESHOLD
    assert vol_301["topology_status"] == "GREEN"
    assert vol_301["review_status"] == "NOT_REQUIRED"

    # Unit 302 is AMBER
    assert settings.AMBER_THRESHOLD <= vol_302["confidence"] < settings.GREEN_THRESHOLD
    assert vol_302["topology_status"] == "AMBER"
    assert vol_302["review_status"] == "PENDING"
    assert vol_302["evidence"]["control_points_count"] == 2
    assert vol_302["evidence"]["registration_residual_m"] >= 0.10


def test_deliberate_red_conflict_volumes_built():
    """
    CRITICAL DELIBERATE TEST CASE:
    Verifies that Level F02 Unit 201 and Unit 202 are both extruded as 3D solids
    and share a 76.80 m3 geometric volume overlap.
    """
    builder = VolumeBuilder()
    volumes = builder.build_all_volumes()

    vol_201 = next(v for v in volumes if v["unit_code"] == "F02-U01")
    vol_202 = next(v for v in volumes if v["unit_code"] == "F02-U02")

    # Both must be closed polyhedra
    assert vol_201["face_count"] == 6
    assert vol_202["face_count"] == 6

    # Unit 202 has larger area (13.5m x 16m = 216 m2) due to 1.5m extension
    assert abs(vol_201["area_sqm"] - 192.0) < 1e-4
    assert abs(vol_202["area_sqm"] - 216.0) < 1e-4

    # Both volumes flagged as conflict participants in spec
    assert vol_201["deliberate_conflict_participant"] is True
    assert vol_202["deliberate_conflict_participant"] is True

    # 3D Overlap volume: 24 m2 * 3.2m height = 76.80 m3
    poly_201 = Polygon(builder.spec["levels"][3]["units"][0]["coordinates"])
    poly_202 = Polygon(builder.spec["levels"][3]["units"][1]["coordinates"])
    intersection_area = poly_201.intersection(poly_202).area
    overlap_vol = intersection_area * 3.20

    assert abs(overlap_vol - 76.80) < 1e-4
    assert overlap_vol > settings.OVERLAP_TOLERANCE_M3


# --- FAILURE CASES ---

def test_failure_registration_insufficient_control_points():
    """Failure test: Registration with fewer than 2 control points raises ValueError."""
    single_src = np.array([[0.0, 0.0]])
    single_dst = np.array([[278492.0, 2110495.0]])

    with pytest.raises(ValueError, match="at least 2 control points"):
        FloorplanRegistrationEngine.compute_similarity_transform(single_src, single_dst)


def test_failure_confidence_calculation_bounds():
    """Test confidence formula handles extreme boundary inputs safely."""
    # Zero support and huge residual
    conf_min = VolumeBuilder.calculate_confidence_score(
        control_points=0,
        residual_m=5.0,
        point_density_pct=0.0,
        edge_alignment=0.0,
    )
    assert conf_min == 0.0

    # Perfect support
    conf_max = VolumeBuilder.calculate_confidence_score(
        control_points=4,
        residual_m=0.0,
        point_density_pct=100.0,
        edge_alignment=1.0,
    )
    assert conf_max == 1.0
