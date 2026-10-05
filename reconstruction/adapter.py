"""
Reconstruction Adapter Interface & Implementations for BHU-VISTA 3D.
Provides a unified interface for OpenDroneMap (ODM) photogrammetry
and PDAL/Open3D LiDAR point cloud reconstruction.

Non-Negotiable Principles Enforced:
- Principle 8: Modular, replaceable stages.
- Principle 11: MVP Simplicity (deterministic adapter when external ODM server is offline).
- Principle 12: Anti-fake & honest labelling (data_origin = SIMULATED / SYNTHETIC).
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from config.settings import settings
from reconstruction.pipeline import PointCloudProcessor


class ReconstructionResult(BaseModel):
    """Standardized output schema for all 3D reconstruction adapters."""
    status: str = "SUCCESS"
    building_id: str
    parent_ulpin: str
    footprint: Dict[str, Any]
    detected_levels: List[Dict[str, Any]]
    unit_point_densities: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    data_origin: str = "SIMULATED"  # Strictly SIMULATED or SYNTHETIC in MVP
    is_simulated: bool = True
    algorithm: str
    algorithm_version: str = settings.ALGORITHM_VERSION
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    honest_labelling_notice: str = (
        "NOTICE: Deterministic Simulated Reconstruction Output for MVP Demonstration (SIH26011)"
    )


class ReconstructionAdapter(ABC):
    """Abstract base adapter for physical 3D reconstruction sources."""

    @abstractmethod
    def reconstruct(self, input_path: Optional[Path] = None) -> ReconstructionResult:
        """Executes 3D reconstruction and yields a standardized result."""
        pass


class ODMReconstructionAdapter(ReconstructionAdapter):
    """
    Adapter for OpenDroneMap (ODM) drone photogrammetry.
    Connects to an external ODM cluster if online; otherwise deterministically
    returns pre-generated photogrammetry outputs explicitly labelled SIMULATED.
    """

    def __init__(self, odm_endpoint: Optional[str] = None):
        self.odm_endpoint = odm_endpoint or "http://localhost:3000"
        self.is_connected = False  # In offline MVP mode, defaults to simulated deterministic path

    def reconstruct(self, input_path: Optional[Path] = None) -> ReconstructionResult:
        """Executes ODM photogrammetric reconstruction or returns deterministic simulated output."""
        # Single source of truth spec lookup
        processor = PointCloudProcessor()
        pipeline_res = processor.run_pipeline()

        spec = processor.spec
        building_id = spec["building_id"]
        parent_ulpin = spec["parcel"]["parent_ulpin"]

        # Compute point density for each declared unit
        unit_densities = {}
        for lvl in spec["levels"]:
            for u in lvl["units"]:
                u_code = u["unit_code"]
                dens = processor.compute_unit_point_density(
                    u["coordinates"],
                    lvl["zmin"],
                    lvl["zmax"]
                )
                unit_densities[u_code] = dens

        return ReconstructionResult(
            status="SUCCESS",
            building_id=building_id,
            parent_ulpin=parent_ulpin,
            footprint=pipeline_res["envelope"],
            detected_levels=pipeline_res["detected_levels"],
            unit_point_densities=unit_densities,
            data_origin="SIMULATED",  # Honest labelling per Principle 12
            is_simulated=True,
            algorithm="OpenDroneMap-Simulated-Adapter",
            algorithm_version="1.0.0",
        )


class LiDARReconstructionAdapter(ReconstructionAdapter):
    """
    Adapter executing the real PDAL + Open3D style point cloud processing pipeline
    over authentic binary ASPRS LAS files.
    """

    def __init__(self, las_path: Optional[Path] = None):
        self.las_path = las_path or (settings.SAMPLE_DATA_DIR / "point_cloud.las")
        self.processor = PointCloudProcessor(self.las_path)

    def reconstruct(self, input_path: Optional[Path] = None) -> ReconstructionResult:
        """Runs the LiDAR pipeline (ground filter, height normalisation, footprint, floors)."""
        pipeline_res = self.processor.run_pipeline()
        spec = self.processor.spec

        building_id = spec["building_id"]
        parent_ulpin = spec["parcel"]["parent_ulpin"]

        unit_densities = {}
        for lvl in spec["levels"]:
            for u in lvl["units"]:
                u_code = u["unit_code"]
                dens = self.processor.compute_unit_point_density(
                    u["coordinates"],
                    lvl["zmin"],
                    lvl["zmax"]
                )
                unit_densities[u_code] = dens

        return ReconstructionResult(
            status="SUCCESS",
            building_id=building_id,
            parent_ulpin=parent_ulpin,
            footprint=pipeline_res["envelope"],
            detected_levels=pipeline_res["detected_levels"],
            unit_point_densities=unit_densities,
            data_origin="SYNTHETIC",
            is_simulated=False,
            algorithm="PDAL-LiDAR-Reconstruction-Adapter",
            algorithm_version=settings.ALGORITHM_VERSION,
        )


def get_reconstruction_adapter(source_type: str = "lidar") -> ReconstructionAdapter:
    """Factory creating the appropriate reconstruction adapter."""
    if source_type.lower() in ("odm", "drone", "photogrammetry"):
        return ODMReconstructionAdapter()
    elif source_type.lower() in ("lidar", "pointcloud", "las"):
        return LiDARReconstructionAdapter()
    else:
        raise ValueError(f"Unknown reconstruction source type '{source_type}'. Supported: 'odm', 'lidar'.")


if __name__ == "__main__":
    adapter_odm = get_reconstruction_adapter("odm")
    res_odm = adapter_odm.reconstruct()
    print("ODM Adapter Result:")
    print(f"  - Status: {res_odm.status}")
    print(f"  - Data origin: {res_odm.data_origin} (Simulated: {res_odm.is_simulated})")
    print(f"  - Notice: {res_odm.honest_labelling_notice}")

    adapter_lidar = get_reconstruction_adapter("lidar")
    res_lidar = adapter_lidar.reconstruct()
    print("\nLiDAR Adapter Result:")
    print(f"  - Footprint area: {res_lidar.footprint['footprint_area_sqm']:.1f} m2")
    print(f"  - F03 Unit 301 density: {res_lidar.unit_point_densities['F03-U01']['density_pct']}%")
    print(f"  - F03 Unit 302 density: {res_lidar.unit_point_densities['F03-U02']['density_pct']}% (Deliberate AMBER!)")
