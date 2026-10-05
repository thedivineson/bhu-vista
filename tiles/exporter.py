"""
Authoritative 3D Tiles 1.1 Exporter for BHU-VISTA 3D.
Converts validated 3D cadastral volumes (POLYHEDRALSURFACE Z) into:
1. Batched binary GLB models per building level (with GREEN/AMBER/RED status styling).
2. OGC 3D Tiles 1.1 compliant tileset.json with ENU -> ECEF georeferenced transform.
3. Automated verification via npx 3d-tiles-validator.

Non-Negotiable Principles Enforced:
- Principle 2: Topology-first, evidence-backed styling.
- Principle 3: Single vertical framework across negative (B01) and positive (F01-F03) levels.
- Principle 7: Provenance everywhere (metadata embedded in batch/GLB).
- Principle 12: Honest labelling (data_origin explicitly stamped on all assets).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pyproj
import trimesh

from config.settings import settings
from cadastre.extrusion import PolyhedralExtruder


# Status color mappings (RGBA: 0-255)
STATUS_COLORS = {
    "GREEN": [34, 197, 94, 204],   # #22c55e emerald, 80% opacity
    "AMBER": [245, 158, 11, 204],  # #f59e0b amber, 80% opacity
    "RED": [239, 68, 68, 204],     # #ef4444 red, 80% opacity
}


class TileExporter:
    """Exports validated 3D cadastral volumes into OGC 3D Tiles 1.1 format."""

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir or (settings.SAMPLE_DATA_DIR / "tileset")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.levels_dir = self.output_dir / "levels"
        self.levels_dir.mkdir(parents=True, exist_ok=True)

        # Coordinate reference center: Syndicate Heights Kurla center (EPSG:32643)
        self.center_utm_x = 278504.0
        self.center_utm_y = 2110503.0
        self.center_utm_z = 0.0

    def compute_enu_to_ecef_transform(self) -> Tuple[List[float], Dict[str, float]]:
        """
        Computes 4x4 column-major affine transform matrix converting local ENU (East-North-Up)
        meters to WGS 84 ECEF coordinates (EPSG:4978).
        """
        # 1. Transform UTM 43N (EPSG:32643) -> WGS 84 Lat/Lon (EPSG:4326)
        to_wgs84 = pyproj.Transformer.from_crs(
            settings.HORIZONTAL_CRS, "EPSG:4326", always_xy=True
        )
        lon_deg, lat_deg = to_wgs84.transform(self.center_utm_x, self.center_utm_y)

        # 2. Transform WGS 84 -> ECEF (EPSG:4978)
        to_ecef = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:4978", always_xy=True)
        ecef_x, ecef_y, ecef_z = to_ecef.transform(lon_deg, lat_deg, self.center_utm_z)

        # 3. Calculate East, North, Up unit vectors in ECEF
        lon_rad = np.radians(lon_deg)
        lat_rad = np.radians(lat_deg)

        east = np.array([-np.sin(lon_rad), np.cos(lon_rad), 0.0])
        north = np.array([
            -np.sin(lat_rad) * np.cos(lon_rad),
            -np.sin(lat_rad) * np.sin(lon_rad),
            np.cos(lat_rad),
        ])
        up = np.array([
            np.cos(lat_rad) * np.cos(lon_rad),
            np.cos(lat_rad) * np.sin(lon_rad),
            np.sin(lat_rad),
        ])

        # 4. 4x4 Column-Major Matrix for 3D Tiles transform
        # Column 0: East, Column 1: North, Column 2: Up, Column 3: Origin
        transform = [
            float(east[0]), float(east[1]), float(east[2]), 0.0,
            float(north[0]), float(north[1]), float(north[2]), 0.0,
            float(up[0]), float(up[1]), float(up[2]), 0.0,
            float(ecef_x), float(ecef_y), float(ecef_z), 1.0,
        ]

        geo_meta = {
            "lon_deg": float(lon_deg),
            "lat_deg": float(lat_deg),
            "ecef_x": float(ecef_x),
            "ecef_y": float(ecef_y),
            "ecef_z": float(ecef_z),
        }

        return transform, geo_meta

    def export_level_glb(self, level_code: str, units: List[Dict[str, Any]]) -> Path:
        """
        Builds a single binary GLB file containing all units for a given building level.
        Each unit is assigned distinct vertex colors reflecting its topology status.
        """
        scene = trimesh.Scene()

        for unit in units:
            coords = unit["coordinates"]
            zmin = float(unit["zmin"])
            zmax = float(unit["zmax"])
            status = unit.get("topology_status", "GREEN")
            vol_id = unit["volume_id"]
            unit_code = unit.get("unit_code", f"U-{vol_id}")

            # Shift to local coordinates relative to building center
            local_coords = [
                [x - self.center_utm_x, y - self.center_utm_y]
                for x, y in coords
            ]

            mesh = PolyhedralExtruder.extrude_to_trimesh(local_coords, zmin, zmax)

            # Assign status color to faces
            color = STATUS_COLORS.get(status, [200, 200, 200, 204])
            mesh.visual.face_colors = np.array([color] * len(mesh.faces), dtype=np.uint8)

            # Embed unit metadata
            mesh.metadata["volume_id"] = vol_id
            mesh.metadata["unit_code"] = unit_code
            mesh.metadata["level_code"] = level_code
            mesh.metadata["topology_status"] = status
            mesh.metadata["review_status"] = unit.get("review_status", "NOT_REQUIRED")
            mesh.metadata["data_origin"] = settings.DATA_ORIGIN

            node_name = f"Volume_{vol_id}_{unit_code}_{status}"
            scene.add_geometry(mesh, node_name=node_name)

        # Export binary GLB
        glb_data = scene.export(file_type="glb")
        glb_path = self.levels_dir / f"{level_code}.glb"
        with open(glb_path, "wb") as f:
            f.write(glb_data)

        return glb_path

    def export_3d_tileset(self, validated_volumes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Exports complete OGC 3D Tiles 1.1 tileset.
        Groups volumes by level, exports individual level GLBs, and writes tileset.json.
        """
        transform, geo_meta = self.compute_enu_to_ecef_transform()

        # Group volumes by level
        levels_map: Dict[str, List[Dict[str, Any]]] = {}
        for v in validated_volumes:
            levels_map.setdefault(v["level_code"], []).append(v)

        # Sort levels bottom-to-top
        sorted_levels = sorted(
            levels_map.keys(),
            key=lambda l: min(v["zmin"] for v in levels_map[l])
        )

        children = []
        # Local horizontal footprint half-extents
        hx = 13.0
        hy = 9.0

        for lvl in sorted_levels:
            lvl_units = levels_map[lvl]
            zmin = min(u["zmin"] for u in lvl_units)
            zmax = max(u["zmax"] for u in lvl_units)

            # Export GLB for this level
            glb_path = self.export_level_glb(lvl, lvl_units)
            rel_uri = f"levels/{lvl}.glb"

            # Level bounding box in local ENU
            cz = (zmin + zmax) / 2.0
            hz = (zmax - zmin) / 2.0 + 0.1
            level_box = [0.0, 0.0, round(cz, 3), hx, 0.0, 0.0, 0.0, hy, 0.0, 0.0, 0.0, round(hz, 3)]

            child_tile = {
                "boundingVolume": {"box": level_box},
                "geometricError": 0.0,
                "content": {"uri": rel_uri},
                "extras": {
                    "level_code": lvl,
                    "zmin": zmin,
                    "zmax": zmax,
                    "unit_count": len(lvl_units),
                    "volume_ids": [u["volume_id"] for u in lvl_units],
                    "data_origin": settings.DATA_ORIGIN,
                },
            }
            children.append(child_tile)

        # Overall building bounding box
        overall_zmin = min(v["zmin"] for v in validated_volumes)
        overall_zmax = max(v["zmax"] for v in validated_volumes)
        overall_cz = (overall_zmin + overall_zmax) / 2.0
        overall_hz = (overall_zmax - overall_zmin) / 2.0 + 0.5
        root_box = [0.0, 0.0, round(overall_cz, 3), hx + 1.0, 0.0, 0.0, 0.0, hy + 1.0, 0.0, 0.0, 0.0, round(overall_hz, 3)]

        tileset = {
            "asset": {
                "version": "1.1",
                "generator": f"{settings.PROJECT_NAME} 3D Tiles Exporter {settings.ALGORITHM_VERSION}",
            },
            "geometricError": 500.0,
            "root": {
                "transform": transform,
                "boundingVolume": {"box": root_box},
                "geometricError": 50.0,
                "refine": "ADD",
                "children": children,
            },
            "extras": {
                "project": settings.PROJECT_NAME,
                "team": f"{settings.TEAM_NAME} (ID: {settings.TEAM_ID})",
                "problem_statement": settings.SIH_PROBLEM_STATEMENT,
                "data_origin": settings.DATA_ORIGIN,
                "crs_horizontal": settings.HORIZONTAL_CRS,
                "vertical_datum": settings.VERTICAL_DATUM,
                "geo_reference": geo_meta,
            },
        }

        tileset_path = self.output_dir / "tileset.json"
        with open(tileset_path, "w", encoding="utf-8") as f:
            json.dump(tileset, f, indent=2)

        return {
            "tileset_file": str(tileset_path),
            "levels_exported": len(children),
            "output_directory": str(self.output_dir),
            "geo_reference": geo_meta,
            "tileset": tileset,
        }

    def validate_tileset(self) -> Dict[str, Any]:
        """
        Runs npx 3d-tiles-validator against the exported tileset.json.
        Returns validator results report.
        """
        tileset_path = self.output_dir / "tileset.json"
        if not tileset_path.exists():
            raise FileNotFoundError(f"Tileset file does not exist: {tileset_path}")

        cmd = f'cmd /c "npx 3d-tiles-validator -t \"{tileset_path}\""'
        try:
            res = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            stdout = res.stdout
            passed = ("numErrors\": 0" in stdout) or ("Validation result:" in stdout and "numErrors: 0" in stdout)
            return {
                "passed": passed,
                "return_code": res.returncode,
                "output": stdout,
                "error": res.stderr if res.returncode != 0 else None,
            }
        except Exception as e:
            return {
                "passed": False,
                "return_code": -1,
                "output": "",
                "error": str(e),
            }


if __name__ == "__main__":
    from validation.service import ValidationReviewService
    vols = ValidationReviewService().run_full_validation()
    exporter = TileExporter()
    res = exporter.export_3d_tileset(vols)
    print(f"Exported tileset to {res['tileset_file']}")
    val = exporter.validate_tileset()
    print("Validator Output:\n", val["output"])
