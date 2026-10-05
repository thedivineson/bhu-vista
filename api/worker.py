"""
Celery asynchronous task worker for heavy geospatial jobs:
- Reconstruction processing
- Point cloud filtering & envelope extraction
- 3D Mesh tiling and Cesium 3D Tiles 1.1 generation
"""

import sys
from pathlib import Path

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from celery import Celery
from config.settings import settings

celery_app = Celery(
    "bhuvista_tasks",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)


@celery_app.task(name="tasks.ping")
def ping_task() -> str:
    """Simple health task for worker verification."""
    return "pong"


@celery_app.task(name="tasks.run_reconstruction")
def run_reconstruction_task(adapter_type: str = "LIDAR") -> dict:
    """Heavy asynchronous reconstruction task using ReconstructionAdapter."""
    from reconstruction.adapter import ReconstructionAdapterFactory
    adapter = ReconstructionAdapterFactory.get_adapter(adapter_type)
    return adapter.execute_reconstruction()


@celery_app.task(name="tasks.export_3d_tiles")
def export_3d_tiles_task() -> dict:
    """Heavy asynchronous 3D tiles export and validation task."""
    from validation.service import ValidationReviewService
    from tiles.exporter import TileExporter

    vols = ValidationReviewService().run_full_validation()
    exporter = TileExporter()
    export_meta = exporter.export_3d_tileset(vols)
    val_report = exporter.validate_tileset()
    return {
        "status": "COMPLETED",
        "export": export_meta,
        "validation": val_report,
    }
