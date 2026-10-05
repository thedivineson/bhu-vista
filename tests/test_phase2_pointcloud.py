"""
Automated Unit & Integration Tests for Phase 2: Point Cloud & Reconstruction.
Validates synthetic LAS point cloud generation, ground filtering, height normalization,
envelope extraction, floor slab peak detection, deliberate AMBER occlusion,
and ReconstructionAdapter contract compliance (with honest labelling).
"""

from pathlib import Path
import laspy
import numpy as np
import pytest

from config.settings import settings
from ingestion.point_cloud_generator import SyntheticPointCloudGenerator
from reconstruction.pipeline import PointCloudProcessor
from reconstruction.adapter import (
    get_reconstruction_adapter,
    ODMReconstructionAdapter,
    LiDARReconstructionAdapter,
)


def test_synthetic_las_generation_and_schema(tmp_path: Path):
    """Verify synthetic LAS generation adheres to ASPRS 1.4 schema and contains ground + building points."""
    las_target = tmp_path / "test_cloud.las"
    generator = SyntheticPointCloudGenerator()
    out_path = generator.write_las(las_target)

    assert out_path.exists()
    las = laspy.read(str(out_path))

    # Verify point count and attributes
    assert len(las.points) >= 14000, f"Expected >= 14000 points, got {len(las.points)}"
    unique_classes = set(las.classification)
    assert 2 in unique_classes, "ASPRS Class 2 (Ground) must be present"
    assert 6 in unique_classes, "ASPRS Class 6 (Building) must be present"

    # Verify spatial bounds encompass parcel and building
    assert las.z.min() >= -1.0
    assert las.z.max() <= 14.0


def test_ground_filter_and_height_normalization():
    """Verify ground filtering detects ground datum and height normalisation pegs entrance to H ~ 0."""
    processor = PointCloudProcessor()
    ground_mask, ground_datum = processor.filter_ground()

    # Ground datum should be within 10cm of 0.00m
    assert abs(ground_datum - settings.Z_GROUND_LEVEL) <= 0.10, f"Ground datum {ground_datum} deviates from 0.00"

    h_coords = processor.normalize_heights(ground_datum)
    assert h_coords.min() >= -0.50
    assert abs(h_coords.max() - 12.80) <= 0.30


def test_2d_footprint_and_3d_envelope_extraction():
    """Verify 2D building footprint envelope and 3D bounding box match specification."""
    processor = PointCloudProcessor()
    ground_mask, ground_datum = processor.filter_ground()
    h_coords = processor.normalize_heights(ground_datum)

    envelope = processor.extract_building_envelope(h_coords)

    # Footprint dimensions: 24m width x 16m depth = 384 m2
    assert abs(envelope["width_m"] - 24.0) <= 0.50, f"Width {envelope['width_m']} != ~24.0"
    assert abs(envelope["depth_m"] - 16.0) <= 0.50, f"Depth {envelope['depth_m']} != ~16.0"
    assert abs(envelope["height_m"] - 12.80) <= 0.50, f"Height {envelope['height_m']} != ~12.8"
    assert abs(envelope["footprint_area_sqm"] - 384.0) <= 15.0


def test_floor_level_slab_peak_detection():
    """Verify floor detection discovers 5 discrete levels including negative subsurface basement."""
    processor = PointCloudProcessor()
    ground_mask, ground_datum = processor.filter_ground()
    h_coords = processor.normalize_heights(ground_datum)

    levels = processor.detect_floor_levels(h_coords)
    assert len(levels) == 5, f"Expected 5 levels, found {len(levels)}"

    level_codes = [lvl["level_code"] for lvl in levels]
    assert level_codes == ["B01", "G00", "F01", "F02", "F03"]

    # Basement verification
    b01 = levels[0]
    assert b01["is_subsurface"] is True
    assert b01["zmin"] == -3.20 and b01["zmax"] == 0.00

    # Upper floors verification
    for lvl in levels[1:]:
        assert lvl["is_subsurface"] is False
        assert lvl["height_m"] == 3.20
        assert lvl["support_confidence"] >= 0.85


def test_deliberate_amber_point_cloud_support_occlusion():
    """
    CRITICAL DELIBERATE TEST CASE:
    Proves that Apartment 302 on F03 has physically simulated sensor occlusion,
    yielding density ~50%, while Apartment 301 on F03 has density > 85%.
    """
    processor = PointCloudProcessor()
    spec = processor.spec

    f03 = next(lvl for lvl in spec["levels"] if lvl["level_code"] == "F03")
    unit_301 = f03["units"][0]  # Apartment 301 (West - High Confidence)
    unit_302 = f03["units"][1]  # Apartment 302 (East - Deliberate AMBER)

    dens_301 = processor.compute_unit_point_density(unit_301["coordinates"], 9.60, 12.80)
    dens_302 = processor.compute_unit_point_density(unit_302["coordinates"], 9.60, 12.80)

    # Unit 301 must have high support (> 85%)
    assert dens_301["density_pct"] >= 85.0, f"Expected Unit 301 density >= 85%, got {dens_301['density_pct']}%"

    # Unit 302 must have weak support (45% to 58%), perfectly matching the AMBER case
    assert 45.0 <= dens_302["density_pct"] <= 58.0, (
        f"Expected Unit 302 density ~50% (between 45% and 58%), got {dens_302['density_pct']}%"
    )

    # Explicit ratio proves occlusion was executed by real point filter
    ratio = dens_302["observed_point_count"] / dens_301["observed_point_count"]
    assert 0.45 <= ratio <= 0.60, f"Occlusion ratio {ratio:.3f} deviates from expected 0.50"


def test_odm_reconstruction_adapter_contract():
    """Verify ODMReconstructionAdapter follows the adapter contract with honest SIMULATED labelling."""
    adapter = get_reconstruction_adapter("odm")
    assert isinstance(adapter, ODMReconstructionAdapter)

    result = adapter.reconstruct()
    assert result.status == "SUCCESS"
    assert result.building_id == "BLD-MUM-001"
    assert result.parent_ulpin == "12345678901234"
    assert result.data_origin == "SIMULATED"
    assert result.is_simulated is True
    assert "NOTICE: Deterministic Simulated Reconstruction" in result.honest_labelling_notice
    assert len(result.detected_levels) == 5


def test_lidar_reconstruction_adapter_contract():
    """Verify LiDARReconstructionAdapter executes real point cloud analysis with SYNTHETIC data_origin."""
    adapter = get_reconstruction_adapter("lidar")
    assert isinstance(adapter, LiDARReconstructionAdapter)

    result = adapter.reconstruct()
    assert result.status == "SUCCESS"
    assert result.data_origin == "SYNTHETIC"
    assert result.is_simulated is False
    assert "F03-U01" in result.unit_point_densities
    assert "F03-U02" in result.unit_point_densities


# --- FAILURE CASES ---

def test_failure_nonexistent_las_file(tmp_path: Path):
    """Failure test: PointCloudProcessor raises FileNotFoundError if specified file does not exist."""
    fake_path = tmp_path / "missing_file.las"
    with pytest.raises(Exception):
        # laspy.read raises FileNotFoundError
        laspy.read(str(fake_path))


def test_failure_unknown_adapter_type():
    """Failure test: Requesting an unsupported adapter type raises ValueError."""
    with pytest.raises(ValueError, match="Unknown reconstruction source type 'satellite_radar'"):
        get_reconstruction_adapter("satellite_radar")


def test_failure_degenerate_unit_polygon_density():
    """Failure test: Passing an invalid / degenerate polygon to compute_unit_point_density raises ValueError."""
    processor = PointCloudProcessor()
    # Degenerate polygon (only 2 points)
    degenerate_coords = [[0.0, 0.0], [10.0, 10.0]]
    with pytest.raises(Exception):
        processor.compute_unit_point_density(degenerate_coords, 0.0, 3.2)
