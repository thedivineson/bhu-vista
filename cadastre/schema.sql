-- ============================================================================
-- BHU-VISTA 3D (Aayam – Convert to Higher Dimensions)
-- PostgreSQL 16 + PostGIS 3.4/3.5 + SFCGAL Authoritative Database Schema
--
-- Non-Negotiable Principles Enforced:
-- Principle 2: Topology-first, closed solids (POLYHEDRALSURFACEZ).
-- Principle 3: Single vertical framework for positive and negative space.
-- Principle 5: Hard publication gate (GREEN auto, AMBER approved, RED never).
-- Principle 6: Separation of authoritative ownership from sensor geometry.
-- Principle 7: Provenance everywhere (source, algorithm, timestamp, version).
-- ============================================================================

-- 1. Enable Core Spatial & 3D SFCGAL Extensions
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_sfcgal;

-- Compatibility Helper Functions for PostGIS 3.4 vs 3.5+ SFCGAL Names
-- PostGIS 3.5 introduced CG_ prefix for SFCGAL functions; earlier versions use ST_
CREATE OR REPLACE FUNCTION bv_is_solid(geom geometry) RETURNS boolean AS $$
BEGIN
    RETURN ST_IsSolid(geom);
EXCEPTION WHEN undefined_function THEN
    RETURN CG_IsSolid(geom);
END;
$$ LANGUAGE plpgsql IMMUTABLE;

CREATE OR REPLACE FUNCTION bv_volume(geom geometry) RETURNS double precision AS $$
BEGIN
    RETURN ST_Volume(geom);
EXCEPTION WHEN undefined_function THEN
    RETURN CG_Volume(geom);
END;
$$ LANGUAGE plpgsql IMMUTABLE;

CREATE OR REPLACE FUNCTION bv_3d_intersection(geom1 geometry, geom2 geometry) RETURNS geometry AS $$
BEGIN
    RETURN ST_3DIntersection(geom1, geom2);
EXCEPTION WHEN undefined_function THEN
    RETURN CG_3DIntersection(geom1, geom2);
END;
$$ LANGUAGE plpgsql IMMUTABLE;


-- 2. PARCEL: Authoritative 2D Cadastral Base (Parent ULPIN)
CREATE TABLE IF NOT EXISTS parcel (
    id SERIAL PRIMARY KEY,
    parent_ulpin VARCHAR(14) NOT NULL UNIQUE CHECK (parent_ulpin ~ '^[0-9]{14}$'),
    district VARCHAR(100) NOT NULL,
    taluka VARCHAR(100) NOT NULL,
    village VARCHAR(100) NOT NULL,
    survey_number VARCHAR(100) NOT NULL,
    area_sqm NUMERIC(12, 2) NOT NULL CHECK (area_sqm > 0),
    geom geometry(Polygon, 32643) NOT NULL,
    data_origin VARCHAR(20) NOT NULL DEFAULT 'SYNTHETIC' CHECK (data_origin IN ('SYNTHETIC', 'SIMULATED', 'AUTHORITATIVE')),
    algorithm_version VARCHAR(20) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_parcel_geom ON parcel USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_parcel_ulpin ON parcel (parent_ulpin);


-- 3. BUILDING: 2D Envelope and Tolerance Bounds
CREATE TABLE IF NOT EXISTS building (
    id SERIAL PRIMARY KEY,
    building_id VARCHAR(50) NOT NULL UNIQUE,
    parent_ulpin VARCHAR(14) NOT NULL REFERENCES parcel(parent_ulpin) ON DELETE RESTRICT,
    name VARCHAR(150) NOT NULL,
    footprint_area_sqm NUMERIC(12, 2) NOT NULL CHECK (footprint_area_sqm > 0),
    envelope_tolerance_m NUMERIC(6, 3) NOT NULL DEFAULT 0.150,
    geom geometry(Polygon, 32643) NOT NULL,
    data_origin VARCHAR(20) NOT NULL DEFAULT 'SYNTHETIC' CHECK (data_origin IN ('SYNTHETIC', 'SIMULATED', 'AUTHORITATIVE')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_building_geom ON building USING GIST (geom);


-- 4. FLOOR: Vertical Levels (Negative Subsurface, Ground, Positive Floors)
CREATE TABLE IF NOT EXISTS floor (
    id SERIAL PRIMARY KEY,
    building_id VARCHAR(50) NOT NULL REFERENCES building(building_id) ON DELETE CASCADE,
    level_code VARCHAR(10) NOT NULL, -- e.g., 'B01', 'G00', 'F01'
    level_name VARCHAR(100) NOT NULL,
    zmin NUMERIC(8, 3) NOT NULL,
    zmax NUMERIC(8, 3) NOT NULL,
    height_m NUMERIC(8, 3) NOT NULL,
    is_subsurface BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_zmin_zmax CHECK (zmin < zmax),
    CONSTRAINT uq_building_level UNIQUE (building_id, level_code)
);


-- 5. FLOORPLAN: 2D Subdivided Unit Boundaries per Level
CREATE TABLE IF NOT EXISTS floorplan (
    id SERIAL PRIMARY KEY,
    floor_id INTEGER NOT NULL REFERENCES floor(id) ON DELETE CASCADE,
    unit_code VARCHAR(50) NOT NULL,
    order_index INTEGER NOT NULL,
    use_type VARCHAR(50) NOT NULL,
    geom geometry(Polygon, 32643) NOT NULL,
    data_origin VARCHAR(20) NOT NULL DEFAULT 'SYNTHETIC',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_floor_unit UNIQUE (floor_id, unit_code)
);

CREATE INDEX IF NOT EXISTS idx_floorplan_geom ON floorplan USING GIST (geom);


-- 6. VOLUME: Authoritative 3D Extruded Solids
CREATE TABLE IF NOT EXISTS volume (
    id SERIAL PRIMARY KEY,
    volume_id VARCHAR(10) NOT NULL, -- Deterministic 3-digit padded e.g., '001', '002'
    parent_ulpin VARCHAR(14) NOT NULL REFERENCES parcel(parent_ulpin) ON DELETE RESTRICT,
    level_code VARCHAR(10) NOT NULL,
    unit_code VARCHAR(50) NOT NULL,
    zmin NUMERIC(8, 3) NOT NULL,
    zmax NUMERIC(8, 3) NOT NULL,
    area NUMERIC(12, 3) NOT NULL,
    volume NUMERIC(12, 3) NOT NULL,
    confidence NUMERIC(5, 4) NOT NULL CHECK (confidence >= 0.0000 AND confidence <= 1.0000),
    topology_status VARCHAR(10) NOT NULL CHECK (topology_status IN ('GREEN', 'AMBER', 'RED')),
    review_status VARCHAR(20) NOT NULL DEFAULT 'NOT_REQUIRED' CHECK (review_status IN ('NOT_REQUIRED', 'PENDING', 'APPROVED', 'REJECTED')),
    validation_report JSONB NOT NULL DEFAULT '{}'::jsonb,
    geom geometry(POLYHEDRALSURFACEZ, 32643) NOT NULL,
    data_origin VARCHAR(20) NOT NULL DEFAULT 'SYNTHETIC' CHECK (data_origin IN ('SYNTHETIC', 'SIMULATED', 'AUTHORITATIVE')),
    algorithm_version VARCHAR(20) NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    superseded BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_volume_z CHECK (zmin < zmax)
);

-- 3D GiST Spatial Index (ND = N-Dimensional Indexing across X, Y, and Z)
CREATE INDEX IF NOT EXISTS idx_volume_geom_gist ON volume USING GIST (geom gist_geometry_ops_nd);
CREATE INDEX IF NOT EXISTS idx_volume_lookup ON volume (parent_ulpin, level_code, unit_code, version);
CREATE INDEX IF NOT EXISTS idx_volume_status ON volume (topology_status, review_status);


-- 7. ULPIN3D: Authoritative 3D Cadastral Identity Strings
CREATE TABLE IF NOT EXISTS ulpin3d (
    id SERIAL PRIMARY KEY,
    ulpin3d_string VARCHAR(100) NOT NULL UNIQUE,
    volume_row_id INTEGER NOT NULL REFERENCES volume(id) ON DELETE RESTRICT,
    issuance_basis VARCHAR(30) NOT NULL CHECK (issuance_basis IN ('GREEN_AUTO', 'AMBER_HUMAN_APPROVED')),
    version INTEGER NOT NULL DEFAULT 1,
    data_origin VARCHAR(20) NOT NULL DEFAULT 'SYNTHETIC' CHECK (data_origin IN ('SYNTHETIC', 'SIMULATED', 'AUTHORITATIVE')),
    issued_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ulpin3d_volume ON ulpin3d (volume_row_id);


-- 8. EVIDENCE: Traceable Provenance & Metric Support per Volume
CREATE TABLE IF NOT EXISTS evidence (
    id SERIAL PRIMARY KEY,
    volume_row_id INTEGER NOT NULL REFERENCES volume(id) ON DELETE CASCADE,
    source_type VARCHAR(50) NOT NULL,
    control_points_count INTEGER NOT NULL DEFAULT 0,
    registration_residual_m NUMERIC(6, 4) NOT NULL DEFAULT 0.0000,
    point_density_pct NUMERIC(5, 2) NOT NULL DEFAULT 0.00,
    edge_alignment_score NUMERIC(5, 4) NOT NULL DEFAULT 0.0000,
    confidence_score NUMERIC(5, 4) NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    data_origin VARCHAR(20) NOT NULL DEFAULT 'SYNTHETIC',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_evidence_volume ON evidence (volume_row_id);


-- 9. OWNERSHIP_LINK: Authoritative Ownership Separate from Geometry (Principle 6)
-- Geometry pipeline NEVER queries this table; mock ownership in MVP
CREATE TABLE IF NOT EXISTS ownership_link (
    id SERIAL PRIMARY KEY,
    parent_ulpin VARCHAR(14) NOT NULL REFERENCES parcel(parent_ulpin) ON DELETE RESTRICT,
    unit_code VARCHAR(50) NOT NULL,
    owner_name VARCHAR(150) NOT NULL,
    owner_id_hash VARCHAR(64) NOT NULL,
    share_fraction NUMERIC(5, 4) NOT NULL DEFAULT 1.0000 CHECK (share_fraction > 0 AND share_fraction <= 1.0000),
    deed_reference VARCHAR(100) NOT NULL,
    data_origin VARCHAR(20) NOT NULL DEFAULT 'SYNTHETIC',
    is_authoritative BOOLEAN NOT NULL DEFAULT FALSE, -- Explicitly labelled mock in MVP
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ownership_unit ON ownership_link (parent_ulpin, unit_code);


-- 10. REVIEW_AUDIT: Append-Only Audit Trail for Human-in-the-Loop Reviews
CREATE TABLE IF NOT EXISTS review_audit (
    audit_id SERIAL PRIMARY KEY,
    volume_row_id INTEGER NOT NULL REFERENCES volume(id) ON DELETE RESTRICT,
    action VARCHAR(20) NOT NULL CHECK (action IN ('APPROVE', 'REJECT')),
    reviewer VARCHAR(100) NOT NULL CHECK (LENGTH(TRIM(reviewer)) > 0),
    reason TEXT NOT NULL CHECK (LENGTH(TRIM(reason)) > 0),
    previous_status VARCHAR(20) NOT NULL,
    resulting_review_status VARCHAR(20) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_volume ON review_audit (volume_row_id);


-- ============================================================================
-- DATABASE TRIGGERS ENFORCING HARD PUBLICATION GATES & IMMUTABILITY
-- ============================================================================

-- Trigger 1: Immutable Append-Only Protection on REVIEW_AUDIT
CREATE OR REPLACE FUNCTION fn_prevent_review_audit_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'ERR_AUDIT_IMMUTABLE: review_audit table is append-only. UPDATE and DELETE operations are strictly prohibited.'
        USING ERRCODE = 'BV001';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_prevent_review_audit_mutation ON review_audit;
CREATE TRIGGER trg_prevent_review_audit_mutation
    BEFORE UPDATE OR DELETE ON review_audit
    FOR EACH ROW
    EXECUTE FUNCTION fn_prevent_review_audit_mutation();


-- Trigger 2: Prevent RED Volume Human Approval (RED is NEVER Approving)
CREATE OR REPLACE FUNCTION fn_prevent_red_volume_approval()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.review_status = 'APPROVED' AND (OLD.topology_status = 'RED' OR NEW.topology_status = 'RED') THEN
        RAISE EXCEPTION 'ERR_CANNOT_APPROVE_RED: Volumes with topology_status RED can NEVER be approved or issued a 3D ULPIN.'
            USING ERRCODE = 'BV002';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_prevent_red_volume_approval ON volume;
CREATE TRIGGER trg_prevent_red_volume_approval
    BEFORE UPDATE ON volume
    FOR EACH ROW
    EXECUTE FUNCTION fn_prevent_red_volume_approval();


-- Trigger 3: Hard 3D ULPIN Issuance Gate
-- Allows ONLY: (1) topology_status = 'GREEN', OR (2) topology_status = 'AMBER' AND review_status = 'APPROVED'
CREATE OR REPLACE FUNCTION fn_enforce_ulpin3d_eligibility()
RETURNS TRIGGER AS $$
DECLARE
    target_vol RECORD;
BEGIN
    SELECT id, topology_status, review_status
    INTO target_vol
    FROM volume
    WHERE id = NEW.volume_row_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'ERR_VOLUME_NOT_FOUND: Referenced volume row id % does not exist.', NEW.volume_row_id
            USING ERRCODE = 'BV003';
    END IF;

    -- Hard Rejection for RED
    IF target_vol.topology_status = 'RED' THEN
        RAISE EXCEPTION 'ERR_RED_VOLUME_INELIGIBLE: Cannot issue 3D ULPIN for volume % with topology_status RED.', target_vol.id
            USING ERRCODE = 'BV004';
    END IF;

    -- Hard Rejection for Unapproved AMBER
    IF target_vol.topology_status = 'AMBER' AND target_vol.review_status <> 'APPROVED' THEN
        RAISE EXCEPTION 'ERR_AMBER_UNAPPROVED: Cannot issue 3D ULPIN for AMBER volume % without explicit APPROVED review_status (current: %).',
            target_vol.id, target_vol.review_status
            USING ERRCODE = 'BV005';
    END IF;

    -- Must be either GREEN or APPROVED AMBER
    IF target_vol.topology_status = 'GREEN' THEN
        NEW.issuance_basis := 'GREEN_AUTO';
    ELSIF target_vol.topology_status = 'AMBER' AND target_vol.review_status = 'APPROVED' THEN
        NEW.issuance_basis := 'AMBER_HUMAN_APPROVED';
    ELSE
        RAISE EXCEPTION 'ERR_INELIGIBLE: Volume % does not meet criteria for 3D ULPIN issuance.', target_vol.id
            USING ERRCODE = 'BV006';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_enforce_ulpin3d_eligibility ON ulpin3d;
CREATE TRIGGER trg_enforce_ulpin3d_eligibility
    BEFORE INSERT OR UPDATE ON ulpin3d
    FOR EACH ROW
    EXECUTE FUNCTION fn_enforce_ulpin3d_eligibility();
