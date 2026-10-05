# BHU-VISTA 3D (Aayam) — 5–7 Minute Jury Demonstration Script
**Smart India Hackathon 2026** | **Problem Statement:** SIH26011 | **Team:** Syndicate (ID: 127351)

---

## 1. Problem Statement & One-Sentence Pitch (0:00 – 1:00)

### The Problem
> "India's 14-digit Bhu-Aadhaar (ULPIN) has brought revolutionary transparency to land ownership. But in vertical India—where multi-story apartments, commercial complexes, and subsurface utilities stack upwards—a 2D boundary polygon cannot tell where one property ends and another begins. Today, vertical disputes and encroachment cannot be authoritatively resolved on a 2D map."

### The Solution in One Sentence
> **"BHU-VISTA 3D (Aayam) transforms 2D parcel polygons into topologically watertight, evidence-backed 3D volumetric property identifiers (3D ULPINs), governed by a zero-compromise topological validation gate and streamed into an interactive 3D geospatial environment."**

---

## 2. Interactive Live Walkthrough (1:00 – 4:30)

### Step 1: Open the Viewer & Showcase the 3D Cadastral Space (1:00 – 1:45)
- **Action:** Open `http://localhost:5173`.
- **Narration:**
  - *"Here we have Syndicate Heights, Kurla (Parent ULPIN: `12345678901234`), georeferenced in EPSG:32643 UTM 43N and draped over the WGS84 terrain in CesiumJS."*
  - Point to the **yellow outline**: *"This is the original 2D cadastral parcel boundary, converted to WGS84 so it aligns with the 3D building model."*
  - Point to the **color-coded building**:
    - **GREEN:** Topologically validated and auto-issued.
    - **AMBER:** Low-confidence evidence requiring surveyor review.
    - **RED:** Geometric or topological conflict.

### Step 2: Click the RED Encroachment on Floor 2 (1:45 – 2:30)
- **Action:** Click **Vol 006** (F02-U01) or **Vol 007** (F02-U02) or select from the catalogue.
- **Narration:**
  - *"Look at Floor 2 (F02). Units A and B (Volumes 006 and 007) are rendered in bright RED."*
  - Look at the **Inspector Pane**:
    - **3D ID Status:** `⛔ 3D ID: Not issued (Reason: Hard geometric failure RED)`
    - **Validation Report:** Notice `✗ Overlap Conflict: 76.80 m³ (Tolerance: 0.001 m³)`.
    - **Overlapping Volume:** Shows mutual conflict between Volume 006 (`F02-U01`) and Volume 007 (`F02-U02`).
    - **Failed Hard Checks:** `EXCLUSIVE_3D_OVERLAP`.
  - *"In real life, developer floor plan amendments often overlap adjoining flats by 1.5 meters. Our SFCGAL volumetric engine detects this 76.80 m³ overlap conflict immediately. Under Principle 5, a RED volume can NEVER receive a 3D ULPIN. Notice that our UI disables and blocks any approval option—enforced both in API logic and by a PostgreSQL DB trigger."*

### Step 3: Inspect & Approve the AMBER Volume on Floor 3 (2:30 – 3:30)
- **Action:** Click **Vol 009** (F03-U02) in the unit catalogue.
- **Narration:**
  - *"Now observe Floor 3 Unit 2 (AMBER). This unit is geometrically watertight, but its evidence confidence is only 53.1% because it was registered using only 2 control points and higher registration residual."*
  - Show the **Review Queue Panel**:
    - *"Notice that 3D ID is blocked as 'Pending human review (AMBER)'."*
  - Fill the form:
    - **Reviewer:** `Surveyor Priya Sharma`
    - **Reason:** `Field verification confirms physical partition matches registered floor plan; weak LiDAR point density accepted per SIH tolerance.`
  - Click **Approve Volume 009**.
  - Show the live update:
    - **Authoritative 3D ULPIN Issued:** `12345678901234|LV=F03|Z=9.60:12.80|V=009`.
    - **Review Status:** Becomes `APPROVED`.
    - **Topology Status:** Remains `AMBER` (preserving historical provenance).
    - **Audit Log:** An immutable audit record is saved with timestamp, reviewer name, and justification.

### Step 4: Isolate the Subsurface Basement (3:30 – 4:00)
- **Action:** Click **🔍 Isolate Subsurface Basement (B01)**.
- **Narration:**
  - *"Cadastre does not stop at ground level. Click the basement isolation toggle: all above-ground floors hide, revealing Volume 001 from Z = -3.20m to 0.00m."*
  - *"This single vertical datum handles underground parking, metro easements, and multi-tenant basements in the same coordinate frame."*

### Step 5: Transparent Provenance & Honest Labelling (4:00 – 4:30)
- **Action:** Point to the top banner and the Point Cloud button.
- **Narration:**
  - *"Notice our permanent top banner: 'SYNTHETIC / SIMULATED PIPELINE DATA'. In the inspector, every metric carries an explicit `data_origin` tag."*
  - *"Look at the Point Cloud button: it is disabled with the label 'Point Cloud (Not available)'. While we have the raw LAS point cloud file on disk, we have not yet converted it into a 3D Tiles point cloud stream. We never show fake, non-functional UI buttons."*

---

## 3. Unique Selling Proposition (USP) & Closing (4:30 – 5:00)

> **"Our core innovation is that BHU-VISTA 3D is not just a 3D visualization viewer; it is an authoritative legal gateway. We don't invent or repair broken geometries. If the 3D geometry fails topology, publication is blocked. If evidence is weak, a surveyor must audit it. When validated, it generates a standard-compliant, immutable 3D ULPIN that makes vertical property rights tamper-proof."**

---

## 4. Four Likely Jury Questions & Authoritative Answers

### Q1: "Why can't you automatically repair the 1.5m overlap on Floor 2 using geometric snapping?"
**Answer:**
> *"In a legal cadastral registry, automatically snapping or trimming geometries would mean the algorithm is arbitrarily taking square meters away from one property owner and giving them to another without legal authority. Our Principle 2 strictly forbids geometry invention or repair. When units overlap, both become RED, publication is halted, and the conflicting parties must resolve the dispute through official resurvey or adjudication."*

### Q2: "How does your system distinguish between touching shared walls and illegal overlapping units?"
**Answer:**
> *"A simple bounding-box or 2D intersection check would falsely flag shared party walls as overlaps. BHU-VISTA 3D uses PostGIS 3.5 SFCGAL 3D Boolean operations (`ST_3DIntersection` + `ST_Volume`). Two adjoining flats sharing a boundary wall have a 2D surface intersection, but their 3D volumetric intersection is exactly 0.000 m³. We enforce an overlap tolerance of 0.001 m³ (1 liter). Only volumetric intersections exceeding 0.001 m³ trigger an overlap conflict."*

### Q3: "What happens if a building undergoes renovation and unit boundaries change?"
**Answer:**
> *"Our system enforces strict immutable versioning (Principle 7). When a renovation occurs and the pipeline is re-run (`POST /api/v1/pipeline/rerun`), the version increments to version + 1. Prior records are marked `superseded = true`, but their historical records and volume IDs (`001`–`009`) remain permanent for title dispute history. Furthermore, previous human approvals do not carry over—the new geometry must pass the validation gate and receive fresh review approval."*

### Q4: "How does your 3D ULPIN format integrate with existing government land systems like Bhu-Aadhaar?"
**Answer:**
> *"Our 3D ULPIN is backward-compatible with India's 14-digit Bhu-Aadhaar. The format is `<ParentULPIN>|LV=<Level>|Z=<Zmin>:<Zmax>|V=<VolumeID>`, for example `12345678901234|LV=F03|Z=9.60:12.80|V=009`. Any legacy 2D system can parse the first 14 digits to query the base land parcel, while modern 3D systems parse the level code, metric Z-elevation range, and unique 3-digit volume sequence to identify the exact volumetric unit in 3D space."*
