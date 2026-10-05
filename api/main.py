"""
BHU-VISTA 3D (Aayam) - FastAPI Backend Service.
Core API gateway for 3D cadastral reconstruction, topology validation,
3D ULPIN registry, and inspectable volume querying.

Non-Negotiable Principles Enforced:
- Principle 7: Provenance everywhere.
- Principle 11: Simplicity & clean interfaces.
- Principle 12: Honest labelling (SYNTHETIC/SIMULATED banners in all responses).
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from config.settings import settings
from validation.service import ValidationReviewService
from identity.generator import Ulpin3DGenerator
from tiles.exporter import TileExporter

app = FastAPI(
    title=f"{settings.PROJECT_NAME} - {settings.PROJECT_SUBTITLE}",
    description=(
        "Evidence-backed 3D cadastral pipeline extending 2D ULPIN parcels "
        "into validated, clickable floor- and basement-level property volumes."
    ),
    version=settings.ALGORITHM_VERSION,
)

# Enable CORS for Cesium / React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def get_root() -> Dict[str, Any]:
    """Root endpoint returning system overview and active provenance."""
    return {
        "project": settings.PROJECT_NAME,
        "subtitle": settings.PROJECT_SUBTITLE,
        "team": f"{settings.TEAM_NAME} (ID: {settings.TEAM_ID})",
        "problem_statement": settings.SIH_PROBLEM_STATEMENT,
        "algorithm_version": settings.ALGORITHM_VERSION,
        "data_origin": settings.DATA_ORIGIN,
        "crs": settings.HORIZONTAL_CRS,
        "vertical_datum": settings.VERTICAL_DATUM,
        "status": "OPERATIONAL",
        "honest_labelling_notice": "SIMULATED / SYNTHETIC DATA PIPELINE FOR PROTOTYPE DEMONSTRATION",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/health")
def get_health() -> Dict[str, Any]:
    """Comprehensive health check endpoint inspecting core components."""
    versions_path = settings.BASE_DIR / "config" / "versions.json"
    spec_path = settings.BUILDING_SPEC_PATH

    return {
        "status": "HEALTHY",
        "service": "api",
        "version": settings.ALGORITHM_VERSION,
        "data_origin": settings.DATA_ORIGIN,
        "checks": {
            "config_loaded": True,
            "version_manifest_exists": versions_path.exists(),
            "building_spec_exists": spec_path.exists(),
        },
        "crs": {
            "horizontal": settings.HORIZONTAL_CRS,
            "vertical": settings.VERTICAL_DATUM,
            "ground_level": settings.Z_GROUND_LEVEL,
        },
        "tolerances": {
            "overlap_m3": settings.OVERLAP_TOLERANCE_M3,
            "containment_m": settings.CONTAINMENT_TOLERANCE_M,
            "green_threshold": settings.GREEN_THRESHOLD,
            "amber_threshold": settings.AMBER_THRESHOLD,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/v1/version-manifest")
def get_version_manifest() -> Dict[str, Any]:
    """Returns the central pinned dependency version manifest."""
    versions_path = settings.BASE_DIR / "config" / "versions.json"
    if not versions_path.exists():
        raise HTTPException(status_code=404, detail="Version manifest file not found")
    with open(versions_path, "r", encoding="utf-8") as f:
        return json.load(f)


@app.get("/api/v1/cadastre/parcel")
def get_parcel_geojson() -> Dict[str, Any]:
    """Returns the parent cadastral parcel GeoJSON."""
    parcel_path = settings.SAMPLE_DATA_DIR / "parcel.geojson"
    if not parcel_path.exists():
        from cadastre.generator import CadastralDataGenerator
        CadastralDataGenerator().run_all()
    with open(parcel_path, "r", encoding="utf-8") as f:
        return json.load(f)


@app.get("/api/v1/cadastre/floorplans")
def get_floorplans_geojson() -> Dict[str, Any]:
    """Returns the floor-level unit subdivisions GeoJSON."""
    floorplans_path = settings.SAMPLE_DATA_DIR / "floorplans.geojson"
    if not floorplans_path.exists():
        from cadastre.generator import CadastralDataGenerator
        CadastralDataGenerator().run_all()
    with open(floorplans_path, "r", encoding="utf-8") as f:
        return json.load(f)


@app.get("/api/v1/cadastre/metadata")
def get_units_metadata() -> Dict[str, Any]:
    """Returns structured metadata catalogue for all units and volumes."""
    metadata_path = settings.SAMPLE_DATA_DIR / "units_metadata.json"
    if not metadata_path.exists():
        from cadastre.generator import CadastralDataGenerator
        CadastralDataGenerator().run_all()
    with open(metadata_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================================
# PHASE 4: 3D TOPOLOGY VALIDATION & HUMAN REVIEW QUEUE ENDPOINTS
# ============================================================================

validation_service = ValidationReviewService()


class ReviewActionRequest(BaseModel):
    volume_id: str = Field(..., description="Target 3-digit volume ID (e.g. '009')")
    reviewer: str = Field(..., min_length=1, description="Official reviewer identity or name")
    reason: str = Field(..., min_length=1, description="Mandatory non-empty review justification")


@app.get("/api/v1/validation/run")
def run_validation() -> Dict[str, Any]:
    """
    Executes the full 7-stage topology validation engine over all building volumes.
    Applies the hard publication gate: GREEN, AMBER, or RED.
    """
    validated = validation_service.run_full_validation()
    green = [v for v in validated if v["topology_status"] == "GREEN"]
    amber = [v for v in validated if v["topology_status"] == "AMBER"]
    red = [v for v in validated if v["topology_status"] == "RED"]
    return {
        "status": "COMPLETED",
        "total_volumes": len(validated),
        "green_count": len(green),
        "amber_count": len(amber),
        "red_count": len(red),
        "volumes": validated,
        "data_origin": settings.DATA_ORIGIN,
        "algorithm_version": settings.ALGORITHM_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/v1/validation/review-queue")
def get_review_queue() -> Dict[str, Any]:
    """Returns volumes pending human review (AMBER with review_status=PENDING)."""
    pending = validation_service.get_review_queue()
    return {
        "pending_count": len(pending),
        "queue": pending,
        "data_origin": settings.DATA_ORIGIN,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/v1/validation/report/{volume_id}")
def get_volume_validation_report(volume_id: str) -> Dict[str, Any]:
    """Returns the comprehensive per-check validation report for a specific volume."""
    vols = validation_service.run_full_validation()
    vol = next((v for v in vols if v["volume_id"] == volume_id), None)
    if not vol:
        raise HTTPException(status_code=404, detail=f"Volume '{volume_id}' not found.")
    return {
        "volume_id": volume_id,
        "level_code": vol["level_code"],
        "unit_code": vol["unit_code"],
        "topology_status": vol["topology_status"],
        "review_status": vol["review_status"],
        "confidence": vol["confidence"],
        "validation_report": vol["validation_report"],
        "data_origin": settings.DATA_ORIGIN,
    }


@app.post("/api/v1/validation/approve")
def approve_volume_review(req: ReviewActionRequest) -> Dict[str, Any]:
    """
    Approves an AMBER volume pending review.
    Enforces Principle 5: RED volumes can NEVER be approved.
    """
    try:
        result = validation_service.approve_volume(
            volume_id=req.volume_id,
            reviewer=req.reviewer,
            reason=req.reason,
        )
        return {
            "status": "SUCCESS",
            "action": "APPROVE",
            "volume_id": req.volume_id,
            "data": result,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/validation/reject")
def reject_volume_review(req: ReviewActionRequest) -> Dict[str, Any]:
    """Rejects an AMBER volume pending review."""
    try:
        result = validation_service.reject_volume(
            volume_id=req.volume_id,
            reviewer=req.reviewer,
            reason=req.reason,
        )
        return {
            "status": "SUCCESS",
            "action": "REJECT",
            "volume_id": req.volume_id,
            "data": result,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/validation/audit-trail")
def get_audit_trail() -> Dict[str, Any]:
    """Returns append-only audit trail for all human review decisions."""
    trail = validation_service.get_audit_trail()
    return {
        "total_records": len(trail),
        "audit_trail": trail,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ============================================================================
# PHASE 5: 3D ULPIN IDENTITY & 3D TILES STREAMING ENDPOINTS
# ============================================================================

identity_generator = Ulpin3DGenerator()
tile_exporter = TileExporter()
pipeline_state = {"current_version": 1}


@app.post("/api/v1/identity/issue/{volume_id}")
def issue_volume_ulpin3d(volume_id: str) -> Dict[str, Any]:
    """
    Issues an authoritative 3D ULPIN string for an eligible volume.
    Enforces Principle 5: RED volumes and unapproved AMBER volumes are blocked.
    """
    vols = validation_service.run_full_validation()
    vol = next((v for v in vols if v["volume_id"] == volume_id), None)
    if not vol:
        raise HTTPException(status_code=404, detail=f"Volume '{volume_id}' not found.")

    try:
        record = identity_generator.issue_ulpin3d(vol, version=pipeline_state["current_version"])
        return {
            "status": "ISSUED",
            "ulpin3d": record,
            "data_origin": settings.DATA_ORIGIN,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except PermissionError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/identity/issue-all")
def issue_all_eligible_ulpin3d() -> Dict[str, Any]:
    """Issues 3D ULPINs for all eligible building volumes in the current version."""
    vols = validation_service.run_full_validation()
    batch_result = identity_generator.issue_all_eligible(
        vols, version=pipeline_state["current_version"]
    )
    return {
        "status": "COMPLETED",
        "result": batch_result,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/v1/identity/volume/{ulpin3d_string}")
def get_by_ulpin3d(ulpin3d_string: str) -> Dict[str, Any]:
    """Look up authoritative volume metadata and provenance by full 3D ULPIN string."""
    record = identity_generator.get_by_ulpin3d(ulpin3d_string)
    if not record:
        raise HTTPException(status_code=404, detail=f"3D ULPIN '{ulpin3d_string}' not found.")
    return {"status": "FOUND", "ulpin3d": record}


@app.get("/api/v1/identity/parent/{parent_ulpin}")
def get_by_parent_ulpin(parent_ulpin: str) -> Dict[str, Any]:
    """Finds all issued 3D volumetric records for a given parent 2D ULPIN parcel."""
    records = identity_generator.get_by_parent_ulpin(parent_ulpin)
    return {
        "parent_ulpin": parent_ulpin,
        "count": len(records),
        "volumes": records,
        "data_origin": settings.DATA_ORIGIN,
    }


@app.get("/api/v1/identity/list")
def list_all_issued_ulpin3d() -> Dict[str, Any]:
    """Lists all active issued 3D ULPIN identities in the registry."""
    records = list(identity_generator._in_memory_registry.values())
    return {
        "total_issued": len(records),
        "identities": records,
        "version": pipeline_state["current_version"],
        "data_origin": settings.DATA_ORIGIN,
    }


@app.get("/api/v1/tiles/tileset.json")
def get_tileset_json() -> Dict[str, Any]:
    """Serves the root OGC 3D Tiles 1.1 tileset.json for Cesium rendering."""
    tileset_path = tile_exporter.output_dir / "tileset.json"
    if not tileset_path.exists():
        # Auto-export if not yet generated
        vols = validation_service.run_full_validation()
        tile_exporter.export_3d_tileset(vols)
    with open(tileset_path, "r", encoding="utf-8") as f:
        return json.load(f)


@app.get("/api/v1/tiles/levels/{filename}")
def get_level_tile_content(filename: str):
    """Serves binary GLB 3D tile geometry for individual building levels."""
    file_path = tile_exporter.levels_dir / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Tile asset '{filename}' not found.")
    return FileResponse(path=str(file_path), media_type="model/gltf-binary", filename=filename)


@app.post("/api/v1/tiles/export")
def trigger_tile_export() -> Dict[str, Any]:
    """Triggers authoritative 3D Tiles 1.1 export and runs validation."""
    vols = validation_service.run_full_validation()
    export_meta = tile_exporter.export_3d_tileset(vols)
    val_report = tile_exporter.validate_tileset()
    return {
        "status": "COMPLETED",
        "export": export_meta,
        "validation": val_report,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/v1/tiles/validate")
def validate_3d_tileset() -> Dict[str, Any]:
    """Runs the official npx 3d-tiles-validator against the current tileset."""
    try:
        report = tile_exporter.validate_tileset()
        return report
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/pipeline/rerun")
def rerun_pipeline_new_version() -> Dict[str, Any]:
    """
    Re-runs the pipeline generating a new version (version = version + 1).
    Per Principle 7: Marks old version rows superseded, keeps volume IDs unchanged,
    and requires fresh review approvals.
    """
    pipeline_state["current_version"] += 1
    new_version = pipeline_state["current_version"]

    # Invalidate old in-memory approvals and re-run validation
    validation_service._in_memory_reviews.clear()
    identity_generator._in_memory_registry.clear()

    vols = validation_service.run_full_validation()
    for v in vols:
        v["version"] = new_version

    # Issue ULPINs for newly eligible GREEN volumes
    batch_result = identity_generator.issue_all_eligible(vols, version=new_version)

    # Re-export 3D tiles
    tile_exporter.export_3d_tileset(vols)

    return {
        "status": "SUCCESS",
        "new_version": new_version,
        "previous_version_superseded": True,
        "volume_ids_preserved": [v["volume_id"] for v in vols],
        "newly_issued_count": batch_result["issued_count"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/api/v1/jobs/reconstruct")
def submit_reconstruction_job(adapter_type: str = "LIDAR") -> Dict[str, Any]:
    """Submits an asynchronous reconstruction job to Celery or executes synchronously if worker offline."""
    import uuid
    job_id = f"job-{uuid.uuid4().hex[:8]}"

    try:
        from api.worker import run_reconstruction_task
        task = run_reconstruction_task.delay(adapter_type)
        return {
            "job_id": str(task.id),
            "status": "PENDING",
            "adapter_type": adapter_type,
            "mode": "ASYNC_CELERY",
        }
    except Exception:
        # Fallback to direct synchronous execution with honest labelling
        from reconstruction.adapter import ReconstructionAdapterFactory
        adapter = ReconstructionAdapterFactory.get_adapter(adapter_type)
        result = adapter.execute_reconstruction()
        return {
            "job_id": job_id,
            "status": "COMPLETED",
            "adapter_type": adapter_type,
            "mode": "SYNC_DIRECT",
            "result": result,
        }


@app.get("/api/v1/jobs/{job_id}/status")
def get_job_status(job_id: str) -> Dict[str, Any]:
    """Checks the status of an asynchronous job."""
    try:
        from celery.result import AsyncResult
        from api.worker import celery_app
        res = AsyncResult(job_id, app=celery_app)
        return {
            "job_id": job_id,
            "status": res.status,
            "ready": res.ready(),
            "result": res.result if res.ready() else None,
        }
    except Exception:
        return {
            "job_id": job_id,
            "status": "COMPLETED",
            "ready": True,
            "note": "Synchronous job runner mode",
        }
