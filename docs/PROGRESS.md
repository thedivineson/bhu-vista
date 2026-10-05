# BHU-VISTA 3D (Aayam) — MVP Progress Tracker
**Smart India Hackathon 2026** | **Problem Statement:** SIH26011 | **Team:** Syndicate (ID: 127351)

---

## Phase Status Summary

| Phase | Description | Status | Tests | Key Deliverables & Validation Criteria |
| :--- | :--- | :---: | :---: | :--- |
| **Phase 0** | **Skeleton & Single Source of Truth** | ✅ Complete | 10 passed | `building_spec.json`, central settings, tolerances, GeoJSON generators, FastAPI scaffold |
| **Phase 1** | **Database, PostGIS 3.5 & Solid Extrusion** | ✅ Complete | 10 passed | `schema.sql` (9 tables, triggers), `POLYHEDRALSURFACE Z` extrusion, Trimesh volume validation |
| **Phase 2** | **Point Cloud & Reconstruction Pipeline** | ✅ Complete | 10 passed | Synthetic LAS 1.4 generation, ground filtering, slab peak detection, ODM & LiDAR adapters |
| **Phase 3** | **Floor-Plan Registration & Extrusion** | ✅ Complete | 8 passed | 2D similarity transform, least-squares residuals, volume builder, evidence binding |
| **Phase 4** | **Authoritative Topology Validation Engine** | ✅ Complete | 35 passed | 7 geometric checks, SFCGAL error handling, RED conflict (76.80 m³), AMBER queue, Review API |
| **Phase 5** | **Identity, API & 3D Tiles Exporter** | ✅ Complete | 19 passed | Structured 3D ULPIN generator, OGC 3D Tiles 1.1 exporter (GLB per level), npx validator (0 errors), FastAPI endpoints |
| **Phase 6** | **CesiumJS 3D Interactive Viewer** | ✅ Complete | Build passes | Resium/Cesium viewer, click inspection, basement isolation, honest synthetic labelling |
| **Phase 7** | **Integration & Jury Package** | ✅ Complete | Verified | README (arch diagram, run guide, Real vs Simulated), 5-7 min jury demo script |

---

## Phase 6 & Phase 7 Verification & Gate Check Details

### Non-Negotiable Principles Enforced:
1. **API-Served OGC 3D Tiles 1.1 Loading:** Cesium viewport streams `tileset.json` from the FastAPI backend with per-level GLB child tiles (`B01.glb` to `F03.glb`).
2. **Token-Free Cesium Viewport (No Ion Banner):** Cesium initialized with `Cesium.Ion.defaultAccessToken = ''`, token-free OpenStreetMap base layer via `UrlTemplateImageryProvider`, flat `EllipsoidTerrainProvider`, and hidden credit container, completely eliminating the default ion access token banner.
3. **True Level & Basement Isolation:** Selecting any level (`B01`, `G00`, `F01`, `F02`, `F03`) or "Isolate Subsurface Basement" immediately hides all other levels (`tile.content.show = false` across all scene primitives). "All Floors" reveals the full stack. `depthTestAgainstTerrain = false` ensures subterranean basement B01 (`-3.20m : 0.00m`) is never clipped.
4. **Detailed Failed-Check Inspector for RED:** For RED volumes (006, 007), inspector displays `⛔ 3D ID: Not issued`, exact overlap conflict volume (`76.80 m³`), tolerance (`0.001 m³`), mutual conflicting volume (`Volume 006` / `Volume 007`), error string, and hard failure code `EXCLUSIVE_3D_OVERLAP`.
5. **Strict AMBER-Only Review Gate:** Review form with mandatory non-empty reviewer identity and justification reason operates strictly on AMBER volumes pending review (Vol 009). RED volumes (006, 007) display a permanent blocked gate notice with zero approve option. Approval triggers real API endpoints, updates the record with an issued 3D ULPIN with basis `AMBER_HUMAN_APPROVED`, preserves `AMBER` topology status, and writes an immutable audit row.
6. **Honest Provenance & Disabled Point Cloud Toggle:** Permanent top notice `SYNTHETIC / SIMULATED PIPELINE DATA`, provenance tags on all components, and a disabled `Point Cloud (Not available)` toggle with explanatory tooltip acknowledging that raw LiDAR LAS exists on disk in EPSG:32643 but no 3D Tiles point cloud stream is served.
7. **Jury Package & Architecture Documentation:** `README.md` includes Mermaid architecture diagram, quick-start commands, validation formulas, versioning rules, Real vs Simulated breakdown, and known limitations. `docs/DEMO_SCRIPT.md` provides an exact 5-7 minute walkthrough script with 4 jury defense questions and answers.
8. **Production Verification:** `npm run build` cleanly transforms 33 modules in 8.82s with zero TypeScript / Vite errors.

---

## Test Execution Summary
- Total active test suite: **92 tests**
- Current passing rate: **100% (92/92 passed)**



