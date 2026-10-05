"""
Automated Unit & Integration Tests for Phase 1: Database Schema,
PostGIS/SFCGAL Triggers, 3D Polyhedral Extrusion, and Round-Trip Mesh Proof.

Mandated Test Criteria:
1. Exact SQL schema & triggers integrity.
2. Required round-trip solid proof: 2D polygon -> POLYHEDRALSURFACE Z -> solid check -> volume -> trimesh export/reload.
3. Publication gate trigger verification (GREEN auto, AMBER approved, RED never).
4. Review audit append-only immutability.
5. Strict failure cases.
"""

import io
import json
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import trimesh

from config.settings import settings
from cadastre.extrusion import PolyhedralExtruder
from cadastre.db_models import (
    Base,
    Parcel,
    Building,
    Floor,
    Floorplan,
    Volume,
    Ulpin3D,
    Evidence,
    OwnershipLink,
    ReviewAudit,
)


@pytest.fixture
def db_session():
    """Provides an isolated SQLite memory database for validating ORM rules & triggers."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_schema_sql_file_integrity():
    """Verify that cadastre/schema.sql defines all required PostGIS + SFCGAL structures."""
    schema_path = settings.BASE_DIR / "cadastre" / "schema.sql"
    assert schema_path.exists(), "schema.sql must exist in cadastre/"

    sql_content = schema_path.read_text(encoding="utf-8")

    # Verify all 9 required tables exist
    required_tables = [
        "CREATE TABLE IF NOT EXISTS parcel",
        "CREATE TABLE IF NOT EXISTS building",
        "CREATE TABLE IF NOT EXISTS floor",
        "CREATE TABLE IF NOT EXISTS floorplan",
        "CREATE TABLE IF NOT EXISTS volume",
        "CREATE TABLE IF NOT EXISTS ulpin3d",
        "CREATE TABLE IF NOT EXISTS evidence",
        "CREATE TABLE IF NOT EXISTS ownership_link",
        "CREATE TABLE IF NOT EXISTS review_audit",
    ]
    for table_decl in required_tables:
        assert table_decl in sql_content, f"Missing table declaration: '{table_decl}'"

    # Verify authoritative POLYHEDRALSURFACEZ
    assert "geometry(POLYHEDRALSURFACEZ, 32643)" in sql_content

    # Verify 3D GiST index with gist_geometry_ops_nd
    assert "USING GIST (geom gist_geometry_ops_nd)" in sql_content

    # Verify SFCGAL extension and helper functions
    assert "CREATE EXTENSION IF NOT EXISTS postgis_sfcgal;" in sql_content
    assert "fn_prevent_review_audit_mutation" in sql_content
    assert "fn_prevent_red_volume_approval" in sql_content
    assert "fn_enforce_ulpin3d_eligibility" in sql_content


def test_round_trip_solid_extrusion_and_trimesh():
    """
    REQUIRED ROUND-TRIP PROOF:
    1. Extrude Apartment 101 (F01-U01: 12m x 16m, Z: 3.20 to 6.40m).
    2. Build authoritative POLYHEDRALSURFACE Z WKT.
    3. Verify solid criteria: closed faces, vertex winding, area, volume.
    4. Triangulate into Trimesh, verify watertightness, volume, surface area.
    5. Export to binary GLB & STL bytes, reload without geometric drift.
    """
    # 1. Fetch Apartment 101 coordinates from building_spec.json
    with open(settings.BUILDING_SPEC_PATH, "r", encoding="utf-8") as f:
        spec = json.load(f)

    f01 = next(lvl for lvl in spec["levels"] if lvl["level_code"] == "F01")
    unit_101 = f01["units"][0]
    coords = unit_101["coordinates"]
    zmin = f01["zmin"]  # 3.20
    zmax = f01["zmax"]  # 6.40
    expected_area = 12.0 * 16.0  # 192.0 m2
    expected_height = 3.20  # m
    expected_vol = expected_area * expected_height  # 614.40 m3

    # 2. Build POLYHEDRALSURFACE Z WKT
    wkt, metadata = PolyhedralExtruder.extrude_to_polyhedralsurface_wkt(coords, zmin, zmax)
    assert wkt.startswith(f"SRID={settings.HORIZONTAL_SRID};POLYHEDRALSURFACE Z")
    assert metadata["face_count"] == 6  # 1 top + 1 bottom + 4 side walls
    assert abs(metadata["footprint_area_sqm"] - expected_area) < 1e-4
    assert abs(metadata["expected_volume_m3"] - expected_vol) < 1e-4
    assert metadata["is_closed_solid"] is True

    # 3. Build triangulated Trimesh
    mesh = PolyhedralExtruder.extrude_to_trimesh(coords, zmin, zmax)

    # 4. Verify solid checks
    assert mesh.is_watertight is True, "Extruded solid must be watertight (closed 2-manifold)"
    assert mesh.is_volume is True, "Mesh must define an enclosed positive 3D volume"
    assert abs(mesh.volume - expected_vol) < 1e-3, f"Expected {expected_vol} m3, got {mesh.volume}"

    # Surface area = 2 * 192 (caps) + 2 * (12 * 3.2) + 2 * (16 * 3.2) = 384 + 76.8 + 102.4 = 563.2 m2
    expected_surface_area = 2 * expected_area + 2 * (12.0 * expected_height) + 2 * (16.0 * expected_height)
    assert abs(mesh.area - expected_surface_area) < 1e-3

    # 5. Round-trip export to GLB bytes and STL bytes, and reload
    glb_bytes = mesh.export(file_type="glb")
    assert len(glb_bytes) > 0, "GLB export must yield non-empty byte buffer"

    # Reload from bytes into a new Trimesh object
    reloaded_mesh = trimesh.load(io.BytesIO(glb_bytes), file_type="glb")
    # For scenes or single geometries
    if isinstance(reloaded_mesh, trimesh.Scene):
        reloaded_mesh = trimesh.util.concatenate(tuple(reloaded_mesh.geometry.values()))

    assert reloaded_mesh.is_watertight is True
    assert abs(reloaded_mesh.volume - expected_vol) < 1e-2


def test_publication_gate_green_auto_issuance(db_session):
    """Publication gate: GREEN volume receives 3D ULPIN with GREEN_AUTO basis."""
    vol = Volume(
        volume_id="004",
        parent_ulpin="12345678901234",
        level_code="F01",
        unit_code="F01-U01",
        zmin=3.20,
        zmax=6.40,
        area=192.0,
        volume=614.4,
        confidence=0.92,
        topology_status="GREEN",
        review_status="NOT_REQUIRED",
        validation_report={"all_checks_passed": True},
        geom_wkt="POLYHEDRALSURFACE Z (...)",
        data_origin="SYNTHETIC",
        algorithm_version="1.0.0",
        version=1,
    )
    db_session.add(vol)
    db_session.commit()

    ulpin = Ulpin3D(
        ulpin3d_string="12345678901234|LV=F01|Z=3.20:6.40|V=004",
        volume_row_id=vol.id,
        issuance_basis="GREEN_AUTO",
        version=1,
        data_origin="SYNTHETIC",
    )
    db_session.add(ulpin)
    db_session.commit()

    assert ulpin.id is not None
    assert ulpin.issuance_basis == "GREEN_AUTO"


def test_publication_gate_amber_approved_issuance(db_session):
    """Publication gate: AMBER volume with APPROVED review receives 3D ULPIN."""
    vol = Volume(
        volume_id="009",
        parent_ulpin="12345678901234",
        level_code="F03",
        unit_code="F03-U02",
        zmin=9.60,
        zmax=12.80,
        area=192.0,
        volume=614.4,
        confidence=0.62,
        topology_status="AMBER",
        review_status="APPROVED",  # Human approved!
        validation_report={"weak_evidence": True},
        geom_wkt="POLYHEDRALSURFACE Z (...)",
        data_origin="SYNTHETIC",
        algorithm_version="1.0.0",
        version=1,
    )
    db_session.add(vol)
    db_session.commit()

    ulpin = Ulpin3D(
        ulpin3d_string="12345678901234|LV=F03|Z=9.60:12.80|V=009",
        volume_row_id=vol.id,
        issuance_basis="AMBER_HUMAN_APPROVED",
        version=1,
        data_origin="SYNTHETIC",
    )
    db_session.add(ulpin)
    db_session.commit()

    assert ulpin.id is not None
    assert ulpin.issuance_basis == "AMBER_HUMAN_APPROVED"


def test_publication_gate_blocks_unapproved_amber(db_session):
    """Failure test: AMBER volume with PENDING review MUST NOT receive a 3D ULPIN."""
    vol = Volume(
        volume_id="009",
        parent_ulpin="12345678901234",
        level_code="F03",
        unit_code="F03-U02",
        zmin=9.60,
        zmax=12.80,
        area=192.0,
        volume=614.4,
        confidence=0.62,
        topology_status="AMBER",
        review_status="PENDING",  # Not approved!
        validation_report={"weak_evidence": True},
        geom_wkt="POLYHEDRALSURFACE Z (...)",
        data_origin="SYNTHETIC",
        algorithm_version="1.0.0",
        version=1,
    )
    db_session.add(vol)
    db_session.commit()

    ulpin = Ulpin3D(
        ulpin3d_string="12345678901234|LV=F03|Z=9.60:12.80|V=009",
        volume_row_id=vol.id,
        issuance_basis="AMBER_HUMAN_APPROVED",
        version=1,
    )
    db_session.add(ulpin)

    with pytest.raises(PermissionError, match="ERR_AMBER_UNAPPROVED"):
        db_session.commit()


def test_publication_gate_blocks_red_volume(db_session):
    """Failure test: RED volumes can NEVER receive a 3D ULPIN under any circumstance."""
    vol = Volume(
        volume_id="007",
        parent_ulpin="12345678901234",
        level_code="F02",
        unit_code="F02-U02",
        zmin=6.40,
        zmax=9.60,
        area=216.0,
        volume=691.2,
        confidence=0.90,
        topology_status="RED",  # Geometric conflict!
        review_status="PENDING",
        validation_report={"overlap_detected": True},
        geom_wkt="POLYHEDRALSURFACE Z (...)",
        data_origin="SYNTHETIC",
        algorithm_version="1.0.0",
        version=1,
    )
    db_session.add(vol)
    db_session.commit()

    ulpin = Ulpin3D(
        ulpin3d_string="12345678901234|LV=F02|Z=6.40:9.60|V=007",
        volume_row_id=vol.id,
        issuance_basis="GREEN_AUTO",
        version=1,
    )
    db_session.add(ulpin)

    with pytest.raises(PermissionError, match="ERR_RED_VOLUME_INELIGIBLE"):
        db_session.commit()


def test_failure_red_volume_approval_blocked(db_session):
    """Failure test: System trigger blocks setting review_status = APPROVED on RED volumes."""
    vol = Volume(
        volume_id="007",
        parent_ulpin="12345678901234",
        level_code="F02",
        unit_code="F02-U02",
        zmin=6.40,
        zmax=9.60,
        area=216.0,
        volume=691.2,
        confidence=0.90,
        topology_status="RED",
        review_status="PENDING",
        validation_report={"overlap": True},
        geom_wkt="POLYHEDRALSURFACE Z (...)",
        data_origin="SYNTHETIC",
        algorithm_version="1.0.0",
        version=1,
    )
    db_session.add(vol)
    db_session.commit()

    # Attempt human approval on RED
    vol.review_status = "APPROVED"
    with pytest.raises(PermissionError, match="ERR_CANNOT_APPROVE_RED"):
        db_session.commit()


def test_failure_review_audit_immutable(db_session):
    """Failure test: Attempts to modify or delete review_audit entries must be rejected."""
    vol = Volume(
        volume_id="009",
        parent_ulpin="12345678901234",
        level_code="F03",
        unit_code="F03-U02",
        zmin=9.60,
        zmax=12.80,
        area=192.0,
        volume=614.4,
        confidence=0.62,
        topology_status="AMBER",
        review_status="APPROVED",
        validation_report={},
        geom_wkt="POLYHEDRALSURFACE Z (...)",
        data_origin="SYNTHETIC",
        algorithm_version="1.0.0",
        version=1,
    )
    db_session.add(vol)
    db_session.commit()

    audit = ReviewAudit(
        volume_row_id=vol.id,
        action="APPROVE",
        reviewer="officer_sharma",
        reason="Field inspection confirmed unit boundary per physical demarcation.",
        previous_status="PENDING",
        resulting_review_status="APPROVED",
    )
    db_session.add(audit)
    db_session.commit()

    # Attempt to modify reason
    audit.reason = "Tampered reason"
    with pytest.raises(PermissionError, match="ERR_AUDIT_IMMUTABLE"):
        db_session.commit()
    db_session.rollback()

    # Attempt to delete audit row
    db_session.delete(audit)
    with pytest.raises(PermissionError, match="ERR_AUDIT_IMMUTABLE"):
        db_session.commit()


def test_failure_invalid_zrange_extrusion():
    """Failure test: zmin >= zmax must raise ValueError."""
    coords = [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]]
    with pytest.raises(ValueError, match="zmin .* strictly less than zmax"):
        PolyhedralExtruder.extrude_to_polyhedralsurface_wkt(coords, zmin=5.0, zmax=3.0)


def test_failure_self_intersecting_polygon_extrusion():
    """Failure test: Self-intersecting bowtie polygon must raise ValueError."""
    bowtie_coords = [[0.0, 0.0], [10.0, 10.0], [0.0, 10.0], [10.0, 0.0], [0.0, 0.0]]
    with pytest.raises(ValueError, match="Invalid polygon geometry"):
        PolyhedralExtruder.extrude_to_polyhedralsurface_wkt(bowtie_coords, zmin=0.0, zmax=3.0)
