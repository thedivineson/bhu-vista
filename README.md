# BHU-VISTA 3D (Aayam — आयाम)
**Evidence-Backed 3D Cadastral Property Identity System**
*Smart India Hackathon 2026* | **Problem Statement:** SIH26011 | **Team:** Syndicate (ID: 127351)

---

## 1. What It Is

**BHU-VISTA 3D (Aayam)** extends India's 14-digit 2D Bhu-Aadhaar (ULPIN) into an authoritative, topologically validated, multi-story 3D cadastral registry. It extrudes floor plans, registers LiDAR/drone point clouds, runs a strict 7-point 3D spatial topology validation gate, manages human-in-the-loop reviews for ambiguous geometry, and issues structured 3D ULPIN identifiers streamed into CesiumJS via OGC 3D Tiles 1.1.

---

## 2. System Architecture

```mermaid
flowchart TD
    subgraph S0["Input Data Layer"]
        A1["2D Parcel & Building Spec<br/>(EPSG:32643 UTM 43N)"]
        A2["LiDAR / Drone Point Cloud<br/>(Synthetic LAS 1.4)"]
        A3["Floor Plans & Elevation Offsets<br/>(B01 to F03)"]
    end

    subgraph S1["Reconstruction & Registration Engine"]
        B1["Registration Engine<br/>2D Similarity Transform + Residuals"]
        B2["Solid Extrusion Engine<br/>POLYHEDRALSURFACE Z"]
    end

    subgraph S2["Authoritative Validation Gate"]
        C1{"7-Point Topology Engine<br/>SFCGAL ST_3DIntersection & ST_Volume"}
        C2["Hard Failure (Overlap / Non-Solid)<br/>Status: RED"]
        C3["Low Confidence (&lt; 0.80)<br/>Status: AMBER"]
        C4["Watertight & High Confidence (&ge; 0.80)<br/>Status: GREEN"]
    end

    subgraph S3["Human-in-the-Loop Review Queue"]
        D1["Review Queue API<br/>Reviewer + Reason Mandatory"]
        D2["Append-Only Audit Trail<br/>(REVIEW_AUDIT Row)"]
        D3["Human Approval Decision"]
    end

    subgraph S4["3D ULPIN Identity & OGC Tiles"]
        E1["3D ULPIN Generator<br/>&lt;ParentULPIN&gt;|LV=&lt;Level&gt;|Z=&lt;Zmin&gt;:&lt;Zmax&gt;|V=&lt;VolumeID&gt;"]
        E2["OGC 3D Tiles 1.1 Exporter<br/>Per-Level GLB + ENU&rarr;ECEF Transform"]
    end

    subgraph S5["Interactive Geospatial Viewport"]
        F1["CesiumJS / React Viewer<br/>Floor/Basement Isolation, Click Inspect, Live Review"]
    end

    A1 --> B1
    A2 --> B1
    A3 --> B2
    B1 --> B2
    B2 --> C1

    C1 -->|Hard Conflict / Error| C2
    C1 -->|Confidence &ge; 0.50 &lt; 0.80| C3
    C1 -->|Confidence &ge; 0.80| C4

    C2 -.->|Permanent Block<br/>No 3D ULPIN| E1
    C3 --> D1
    D1 --> D3
    D3 -->|Approved + Reason| D2
    D2 -->|Basis: AMBER_HUMAN_APPROVED| E1
    C4 -->|Basis: GREEN_AUTO| E1

    E1 --> E2
    E2 --> F1
    C2 --> F1
    C3 --> F1
```

---

## 3. How to Run

### Local Execution on Windows
1. **Backend Service (FastAPI):**
   ```powershell
   # Run from project root:
   pip install -r requirements.txt
   uvicorn api.main:app --host 0.0.0.0 --port 8000
   ```
   - API Swagger Documentation: `http://localhost:8000/docs`
   - Provenance Root: `http://localhost:8000/`

2. **Frontend Viewer (CesiumJS + React + Vite):**
   ```powershell
   # Run from viewer directory:
   cd viewer
   npm.cmd install
   npm.cmd run dev
   ```
   - Access viewer at: `http://localhost:5173`

3. **Containerized Execution (if Docker is installed):**
   ```bash
   # Stop local uvicorn and Vite servers first to free ports 8000 & 5173
   docker compose up --build
   ```

4. **Automated Test Suite (92 Tests):**
   ```powershell
   python -m pytest tests/ -v --tb=short
   ```


---

## 4. Authoritative Validation Gate & Status Rules

Every 3D volume undergoes a non-negotiable 7-stage topology audit:
1. **Closed Watertight Solid:** ST_IsClosed / 2-manifold verification.
2. **Self-Intersection:** ST_IsSimple / ST_IsValid check.
3. **Z-Range:** Zmin < Zmax with matching level code vertical bounds.
4. **Parcel Containment:** Horizontal footprint strictly inside parent parcel boundaries.
5. **Floating Volume:** No unsupported overhangs; footprint supported by slab below or ground.
6. **Exclusive Volumetric Overlap:** Authority is 3D intersection volume (`ST_3DIntersection` + `ST_Volume`). Shared touching faces (`volume = 0.000 m³`) are allowed; overlap > 0.001 m³ is an immediate hard failure.
7. **Neighbour Consistency:** Same-floor units partition without internal volumetric overlap.

### Verdict Resolution Formula
$$\text{Status} = \begin{cases} \mathbf{RED} & \text{if any hard failure (overlap, non-solid, SFCGAL error)} \\ \mathbf{GREEN} & \text{if confidence} \ge 0.80 \\ \mathbf{AMBER} & \text{if } 0.50 \le \text{confidence} < 0.80 \\ \mathbf{RED} & \text{if confidence} < 0.50 \end{cases}$$

- **SFCGAL Failure Rule:** Any geometry error or NULL return from SFCGAL registers check `ERROR`, code `SFCGAL_FAILURE`, and sets status to **RED**. It never crashes and never passes.

---

## 5. Human Review Workflow & Audit Trail

| Status | 3D ULPIN Issuance | Review Action Allowed | Behavior |
| :--- | :--- | :--- | :--- |
| **GREEN** | ✅ Auto-Issued (`GREEN_AUTO`) | None needed | Authoritative 3D ULPIN immediately valid. |
| **AMBER** | ⏳ Blocked while `PENDING` | `APPROVE` or `REJECT` | Requires official reviewer identity + mandatory non-empty justification. If approved: review_status = `APPROVED`, topology_status stays `AMBER` (provenance preserved), basis = `AMBER_HUMAN_APPROVED`. |
| **RED** | ⛔ Never Issued | None (Strictly Blocked) | `POST /api/v1/validation/approve` returns HTTP 400 (`PermissionError`). Enforced in code and database trigger. |

---

## 6. Provenance & Versioning (Principle 7)

Re-running the reconstruction pipeline (`POST /api/v1/pipeline/rerun`):
1. Increments `version = version + 1`.
2. Marks all prior volume records `superseded = true`.
3. Preserves stable 3-digit volume IDs (`001` through `009`) ordered by Zmin and unit label.
4. Does **not** carry over previous human review approvals; requires fresh human inspection for AMBER units.

---

## 7. Real vs. Simulated Components

Per SIH Principle 12 (Honest Labelling), every component clearly declares its real vs. simulated boundary:

| Component | Status | Implementation Details |
| :--- | :---: | :--- |
| **3D Topology Engine** | **REAL** | Shapely / PostGIS SFCGAL 7-point volumetric checks, ST_3DIntersection overlap authority. |
| **3D ULPIN Identity Gate** | **REAL** | Authoritative generator, strict basis tagging (`GREEN_AUTO`, `AMBER_HUMAN_APPROVED`), hard RED blockage. |
| **OGC 3D Tiles 1.1 Exporter** | **REAL** | Python trimesh to binary GLB, ENU-to-ECEF pyproj transform, validated via official `npx 3d-tiles-validator` (0 errors). |
| **CesiumJS Interactive Viewer** | **REAL** | Real-time viewport, floor/basement isolation, camera positioning, click-picking live API integration. |
| **OpenDroneMap (ODM)** | **SIMULATED** | Adapter architecture implemented; pipeline returns simulated photogrammetric point cloud with authentic metadata. |
| **LiDAR Point Cloud** | **SYNTHETIC** | Synthetically generated LAS 1.4 dataset (ground points + roof/slab points + noise) with authentic LAS headers. |
| **Floor Plans & Parcel** | **SYNTHETIC** | Synthetic GeoJSON specifications modeled after Kurla, Mumbai Suburban survey parcel 142/3. |
| **Ownership Registry** | **MOCK** | Demo ownership table linking unit codes to mock citizen names and registry deed numbers. |

---

## 8. Known Limitations
1. **Local SFCGAL Backend:** Production deployments utilize PostgreSQL 16 + PostGIS 3.5 with CG_SFCGAL; lightweight testing environments use pure Python/Shapely 3D fallback approximations.
2. **Point Cloud 3D Tiles Streaming:** Point cloud is stored as raw LAS 1.4 in EPSG:32643. Real-time point-cloud viewing in Cesium requires pre-tiling to 3D Tiles `.pnts`, currently flagged as "Point Cloud (Not available)" in the UI.
3. **Single Building Demonstration:** The MVP is benchmarked against `BLD-MUM-001` (Syndicate Heights, 5 levels, 9 units). Multi-building batch processing is managed through Celery task workers.
