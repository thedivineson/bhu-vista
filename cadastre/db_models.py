"""
SQLAlchemy ORM Data Models for BHU-VISTA 3D.
Mirrors the PostGIS 3.4/3.5 + SFCGAL schema and enforces:
- Principle 5: Hard publication gate (GREEN auto, AMBER approved, RED never).
- Principle 6: Ownership separation from geometry.
- Principle 7: Provenance everywhere.
"""

from datetime import datetime, timezone
from typing import Any, Dict
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    JSON,
    event,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base, relationship

JSON_TYPE = JSON().with_variant(JSONB, "postgresql")
Base = declarative_base()


class Parcel(Base):
    """Authoritative 2D cadastral parcel representation."""
    __tablename__ = "parcel"

    id = Column(Integer, primary_key=True, autoincrement=True)
    parent_ulpin = Column(String(14), unique=True, nullable=False, index=True)
    district = Column(String(100), nullable=False)
    taluka = Column(String(100), nullable=False)
    village = Column(String(100), nullable=False)
    survey_number = Column(String(100), nullable=False)
    area_sqm = Column(Numeric(12, 2), nullable=False)
    geom_wkt = Column(Text, nullable=False)
    data_origin = Column(String(20), nullable=False, default="SYNTHETIC")
    algorithm_version = Column(String(20), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    buildings = relationship("Building", back_populates="parcel")
    volumes = relationship("Volume", back_populates="parcel")


class Building(Base):
    """Building envelope footprint and tolerance bounds."""
    __tablename__ = "building"

    id = Column(Integer, primary_key=True, autoincrement=True)
    building_id = Column(String(50), unique=True, nullable=False, index=True)
    parent_ulpin = Column(String(14), ForeignKey("parcel.parent_ulpin"), nullable=False)
    name = Column(String(150), nullable=False)
    footprint_area_sqm = Column(Numeric(12, 2), nullable=False)
    envelope_tolerance_m = Column(Numeric(6, 3), nullable=False, default=0.150)
    geom_wkt = Column(Text, nullable=False)
    data_origin = Column(String(20), nullable=False, default="SYNTHETIC")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    parcel = relationship("Parcel", back_populates="buildings")
    floors = relationship("Floor", back_populates="building")


class Floor(Base):
    """Vertical levels spanning both negative subsurface and positive above-ground space."""
    __tablename__ = "floor"

    id = Column(Integer, primary_key=True, autoincrement=True)
    building_id = Column(String(50), ForeignKey("building.building_id"), nullable=False)
    level_code = Column(String(10), nullable=False)  # B01, G00, F01, F02, F03
    level_name = Column(String(100), nullable=False)
    zmin = Column(Numeric(8, 3), nullable=False)
    zmax = Column(Numeric(8, 3), nullable=False)
    height_m = Column(Numeric(8, 3), nullable=False)
    is_subsurface = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    building = relationship("Building", back_populates="floors")
    floorplans = relationship("Floorplan", back_populates="floor")


class Floorplan(Base):
    """2D subdivided unit polygons per level."""
    __tablename__ = "floorplan"

    id = Column(Integer, primary_key=True, autoincrement=True)
    floor_id = Column(Integer, ForeignKey("floor.id"), nullable=False)
    unit_code = Column(String(50), nullable=False)
    order_index = Column(Integer, nullable=False)
    use_type = Column(String(50), nullable=False)
    geom_wkt = Column(Text, nullable=False)
    data_origin = Column(String(20), nullable=False, default="SYNTHETIC")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    floor = relationship("Floor", back_populates="floorplans")


class Volume(Base):
    """Authoritative 3D closed volumetric property unit (POLYHEDRALSURFACE Z)."""
    __tablename__ = "volume"

    id = Column(Integer, primary_key=True, autoincrement=True)
    volume_id = Column(String(10), nullable=False)  # Zero-padded 3-digit e.g., '001', '002'
    parent_ulpin = Column(String(14), ForeignKey("parcel.parent_ulpin"), nullable=False)
    level_code = Column(String(10), nullable=False)
    unit_code = Column(String(50), nullable=False)
    zmin = Column(Numeric(8, 3), nullable=False)
    zmax = Column(Numeric(8, 3), nullable=False)
    area = Column(Numeric(12, 3), nullable=False)
    volume = Column(Numeric(12, 3), nullable=False)
    confidence = Column(Numeric(5, 4), nullable=False)
    topology_status = Column(String(10), nullable=False)  # GREEN | AMBER | RED
    review_status = Column(String(20), nullable=False, default="NOT_REQUIRED")  # NOT_REQUIRED | PENDING | APPROVED | REJECTED
    validation_report = Column(JSON_TYPE, nullable=False, default=dict)
    geom_wkt = Column(Text, nullable=False)  # POLYHEDRALSURFACE Z WKT
    data_origin = Column(String(20), nullable=False, default="SYNTHETIC")
    algorithm_version = Column(String(20), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    superseded = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    parcel = relationship("Parcel", back_populates="volumes")
    ulpin3d = relationship("Ulpin3D", back_populates="volume", uselist=False)
    evidence = relationship("Evidence", back_populates="volume", uselist=False)
    audits = relationship("ReviewAudit", back_populates="volume")


class Ulpin3D(Base):
    """Authoritative 3D ULPIN string identity."""
    __tablename__ = "ulpin3d"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ulpin3d_string = Column(String(100), unique=True, nullable=False, index=True)
    volume_row_id = Column(Integer, ForeignKey("volume.id"), nullable=False)
    issuance_basis = Column(String(30), nullable=False)  # GREEN_AUTO | AMBER_HUMAN_APPROVED
    version = Column(Integer, nullable=False, default=1)
    data_origin = Column(String(20), nullable=False, default="SYNTHETIC")
    issued_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    volume = relationship("Volume", back_populates="ulpin3d")


class Evidence(Base):
    """Audit evidence metrics backing each 3D volume."""
    __tablename__ = "evidence"

    id = Column(Integer, primary_key=True, autoincrement=True)
    volume_row_id = Column(Integer, ForeignKey("volume.id"), nullable=False)
    source_type = Column(String(50), nullable=False)
    control_points_count = Column(Integer, nullable=False, default=0)
    registration_residual_m = Column(Numeric(6, 4), nullable=False, default=0.0)
    point_density_pct = Column(Numeric(5, 2), nullable=False, default=0.0)
    edge_alignment_score = Column(Numeric(5, 4), nullable=False, default=0.0)
    confidence_score = Column(Numeric(5, 4), nullable=False)
    metadata_json = Column(JSON_TYPE, nullable=False, default=dict)
    data_origin = Column(String(20), nullable=False, default="SYNTHETIC")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    volume = relationship("Volume", back_populates="evidence")


class OwnershipLink(Base):
    """Mock ownership records segregated from geometry generation (Principle 6)."""
    __tablename__ = "ownership_link"

    id = Column(Integer, primary_key=True, autoincrement=True)
    parent_ulpin = Column(String(14), ForeignKey("parcel.parent_ulpin"), nullable=False)
    unit_code = Column(String(50), nullable=False)
    owner_name = Column(String(150), nullable=False)
    owner_id_hash = Column(String(64), nullable=False)
    share_fraction = Column(Numeric(5, 4), nullable=False, default=1.0)
    deed_reference = Column(String(100), nullable=False)
    data_origin = Column(String(20), nullable=False, default="SYNTHETIC")
    is_authoritative = Column(Boolean, nullable=False, default=False)  # Strictly non-authoritative in MVP
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ReviewAudit(Base):
    """Append-only audit trail for human review actions."""
    __tablename__ = "review_audit"

    audit_id = Column(Integer, primary_key=True, autoincrement=True)
    volume_row_id = Column(Integer, ForeignKey("volume.id"), nullable=False)
    action = Column(String(20), nullable=False)  # APPROVE | REJECT
    reviewer = Column(String(100), nullable=False)
    reason = Column(Text, nullable=False)
    previous_status = Column(String(20), nullable=False)
    resulting_review_status = Column(String(20), nullable=False)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    volume = relationship("Volume", back_populates="audits")


# ============================================================================
# ORM LEVEL TRIGGERS (Enforcing Hard Publication Gates & Immutability)
# ============================================================================

def validate_ulpin3d_issuance(mapper, connection, target: Ulpin3D):
    """Enforces Principle 5: Hard publication gate for 3D ULPIN issuance."""
    from sqlalchemy.orm import Session
    session = Session(bind=connection)
    vol = session.query(Volume).filter_by(id=target.volume_row_id).first()

    if not vol:
        raise ValueError(f"ERR_VOLUME_NOT_FOUND: Referenced volume id {target.volume_row_id} does not exist.")

    if vol.topology_status == "RED":
        raise PermissionError(f"ERR_RED_VOLUME_INELIGIBLE: Cannot issue 3D ULPIN for RED volume {vol.id}.")

    if vol.topology_status == "AMBER" and vol.review_status != "APPROVED":
        raise PermissionError(
            f"ERR_AMBER_UNAPPROVED: Cannot issue 3D ULPIN for AMBER volume {vol.id} without APPROVED review_status."
        )

    if vol.topology_status == "GREEN":
        target.issuance_basis = "GREEN_AUTO"
    elif vol.topology_status == "AMBER" and vol.review_status == "APPROVED":
        target.issuance_basis = "AMBER_HUMAN_APPROVED"
    else:
        raise PermissionError(f"ERR_INELIGIBLE: Volume {vol.id} does not meet issuance criteria.")


def validate_volume_update(mapper, connection, target: Volume):
    """Prevents human approval of RED volumes."""
    if target.review_status == "APPROVED" and target.topology_status == "RED":
        raise PermissionError("ERR_CANNOT_APPROVE_RED: RED volumes can NEVER be approved under any path.")


def prevent_audit_mutation(mapper, connection, target: ReviewAudit):
    """Enforces append-only immutability on ReviewAudit."""
    raise PermissionError("ERR_AUDIT_IMMUTABLE: review_audit table is append-only. Modification and deletion prohibited.")


event.listen(Ulpin3D, "before_insert", validate_ulpin3d_issuance)
event.listen(Volume, "before_update", validate_volume_update)
event.listen(ReviewAudit, "before_update", prevent_audit_mutation)
event.listen(ReviewAudit, "before_delete", prevent_audit_mutation)
