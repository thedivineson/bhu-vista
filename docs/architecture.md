# BHU-VISTA 3D (Aayam – Convert to Higher Dimensions)
**Smart India Hackathon 2026 | Problem Statement: SIH26011**  
**Team:** Syndicate (ID: 127351)

## 1. Executive Summary & One-Line USP
> *"An evidence-backed 3D cadastral pipeline that turns an existing 2D ULPIN parcel into validated, clickable floor- and basement-level property volumes."*

While 2D land records (Bhu-Naksha, RoR) cannot represent multi-storey apartments, commercial basements, or subsurface infrastructure, BHU-VISTA 3D extends the authoritative 14-digit government ULPIN (`12345678901234`) into a deterministic, topology-validated 3D identity.

## 2. Six-Stage Cadastral Pipeline
```
[Ingest] ➔ [Reconstruct] ➔ [Subdivide] ➔ [Validate] ➔ [Identify] ➔ [Visualize]
```
1. **Ingest:** Drone photogrammetry, aerial LiDAR, 2D cadastral GIS parcels, architectural floor plans, DEM/DSM.
2. **Reconstruct:** OpenDroneMap (ODM) adapter for drone imagery; PDAL + Open3D for LiDAR ground classification and envelope extraction.
3. **Subdivide:** Floor-plan registration, control-point affine/similarity transformation, unit subdivision, and closed 3D solid extrusion (`POLYHEDRALSURFACEZ`).
4. **Validate:** SFCGAL 3D topology engine (watertight closed solids, non-self-intersection, Z-range validity, envelope containment, exclusive overlap < 0.001 m³).
5. **Identify:** Issuance gate issuing structured 3D ULPIN strings (`ParentULPIN|LV=Level|Z=Zmin:Zmax|V=VolumeID`) strictly for GREEN volumes or human-approved AMBER volumes. RED volumes are strictly barred.
6. **Visualize:** OGC 3D Tiles 1.1 streaming into CesiumJS with floor/basement isolation, click-to-inspect provenance, and honest data labelling.

## 3. Pinned Geodetic Datum & Coordinate System
- **Horizontal CRS:** `EPSG:32643` (WGS 84 / UTM zone 43N) – Pinned for Western India / Mumbai region. All geometric computations and PostGIS storage use this SRID.
- **Vertical Datum:** In the MVP, Z=0 is pegged to the local synthetic ground datum at the building entrance (`Z_ground = 0.00m`). Normalised height `H = Z - Z_ground`.
  - *Production Risk & Mitigation:* In production, orthometric heights referenced to EGM2008 / National Vertical Datum via PROJ will be mandated.
- **Cesium Transformation:** During 3D Tiles generation, Cartesian coordinates in `EPSG:32643` are projected to WGS84 Geodetic (`EPSG:4326`) and converted to Earth-Centered, Earth-Fixed (ECEF) using `pyproj`.

## 4. Single Source of Truth: `sample_data/building_spec.json`
To guarantee strict repeatability across pipeline executions, all parcel dimensions, building footprints, level heights, and unit subdivisions derive from `building_spec.json`:
- **Parent ULPIN:** `12345678901234` (50m × 40m parcel, 2000 m²)
- **Building Footprint:** 24m × 16m (384 m²)
- **Levels (5 Vertical Layers):**
  - `B01`: -3.20m to 0.00m (Basement Parking & Utility)
  - `G00`: 0.00m to 3.20m (Ground Lobby & Community Hall)
  - `F01`: 3.20m to 6.40m (Floor 1 Units 101 & 102)
  - `F02`: 6.40m to 9.60m (Floor 2 Units 201 & 202 - Deliberate RED Overlap)
  - `F03`: 9.60m to 12.80m (Floor 3 Units 301 & 302 - Deliberate AMBER Low-Confidence)

## 5. Deliberate Test Cases (Real Topology Gates)
1. **RED Conflict (F02 Unit 202 Encroachment):**
   - Unit 202's western boundary is intentionally shifted 1.5m into Unit 201 (`X=278502.5` instead of `278504.0`).
   - Overlap volume: `1.5m × 16.0m × 3.20m = 76.80 m³` (exceeding `OVERLAP_TOLERANCE_M3 = 0.001 m³`).
   - Outcome: Flagged RED by real SFCGAL 3D intersection. No 3D ULPIN can ever be issued.
2. **AMBER Review Case (F03 Unit 302 Weak Evidence):**
   - Unit 302 possesses 100% valid, closed, non-overlapping geometry.
   - Evidence metrics specify only 2 registration control points (residual = 0.12m) and 50% point cloud coverage (occlusion).
   - Real confidence formula yields ~0.60 (between `AMBER_THRESHOLD = 0.50` and `GREEN_THRESHOLD = 0.80`).
   - Outcome: Routed to the Human-in-the-Loop review queue. 3D ULPIN is granted only after explicit approval with an immutable audit entry.

## 6. Honest Labelling Policy (Principle 12)
All simulated or synthetic inputs carry explicit `data_origin: "SYNTHETIC"` metadata in JSON schemas, database rows, API responses, and viewer interfaces.
