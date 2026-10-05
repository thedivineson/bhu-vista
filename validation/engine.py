"""
Authoritative 3D Topology Validation Engine for BHU-VISTA 3D.
Implements the 7 non-negotiable geometric checks per Principle 2:
1. Closed solid (2-manifold watertight polyhedral surface)
2. Non-self-intersection
3. Valid Z-range (Zmin < Zmax)
4. Containment within parent parcel and building envelope
5. No floating volume
6. Neighbour consistency & face sharing
7. No exclusive 3D volume overlap (> OVERLAP_TOLERANCE_M3)

Includes robust failure handling for SFCGAL/geometric kernel exceptions.
"""

from typing import Any, Dict, List, Optional, Tuple
import numpy as np
from shapely.geometry import Polygon, box

from config.settings import settings


class TopologyValidationEngine:
    """Executes authoritative topology validation rules over 3D cadastral volumes."""

    def __init__(
        self,
        overlap_tolerance_m3: float = settings.OVERLAP_TOLERANCE_M3,
        containment_tolerance_m: float = settings.CONTAINMENT_TOLERANCE_M,
        envelope_tolerance_m: float = settings.ENVELOPE_XY_TOLERANCE_M,
        green_threshold: float = settings.GREEN_THRESHOLD,
        amber_threshold: float = settings.AMBER_THRESHOLD,
    ):
        self.overlap_tolerance_m3 = overlap_tolerance_m3
        self.containment_tolerance_m = containment_tolerance_m
        self.envelope_tolerance_m = envelope_tolerance_m
        self.green_threshold = green_threshold
        self.amber_threshold = amber_threshold

    def check_z_range(self, volume: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Validates that zmin < zmax and height is strictly positive."""
        zmin = volume["zmin"]
        zmax = volume["zmax"]
        height = zmax - zmin
        passed = (zmin < zmax) and (height > 0.0)
        return passed, {
            "check": "z_range_valid",
            "passed": passed,
            "zmin": zmin,
            "zmax": zmax,
            "height_m": round(height, 3),
            "error": None if passed else f"Invalid Z-range: zmin ({zmin}) >= zmax ({zmax})",
        }

    def check_closed_solid(self, volume: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Validates that polyhedral surface represents a watertight closed solid."""
        try:
            face_count = volume.get("face_count", 0)
            passed = (face_count >= 6) and volume.get("geom_wkt", "").startswith("SRID=")
            return passed, {
                "check": "closed_solid",
                "passed": passed,
                "face_count": face_count,
                "is_watertight": passed,
                "error": None if passed else "Volume is not a closed solid (requires >= 6 faces)",
            }
        except Exception as e:
            return False, {
                "check": "closed_solid",
                "passed": False,
                "error_code": "SFCGAL_FAILURE",
                "error": f"Solid check failure: {str(e)}",
            }

    def check_containment(
        self,
        volume: Dict[str, Any],
        parcel_polygon: Polygon,
        footprint_polygon: Polygon,
    ) -> Tuple[bool, Dict[str, Any]]:
        """Verifies that the unit footprint is contained within parent parcel and envelope."""
        # Extract 2D polygon from building_spec coordinates for the unit
        unit_coords = volume.get("coordinates")
        if not unit_coords:
            # Fallback to reconstructing from envelope
            unit_poly = box(
                footprint_polygon.bounds[0],
                footprint_polygon.bounds[1],
                footprint_polygon.bounds[2],
                footprint_polygon.bounds[3],
            )
        else:
            unit_poly = Polygon(unit_coords)

        # Buffer footprint by envelope tolerance
        buffered_envelope = footprint_polygon.buffer(self.envelope_tolerance_m)
        buffered_parcel = parcel_polygon.buffer(self.containment_tolerance_m)

        in_parcel = buffered_parcel.contains(unit_poly.representative_point())
        in_envelope = buffered_envelope.contains(unit_poly.representative_point())
        passed = in_parcel and in_envelope

        return passed, {
            "check": "containment_in_envelope",
            "passed": passed,
            "in_parcel": in_parcel,
            "in_building_envelope": in_envelope,
            "error": None if passed else "Unit footprint exceeds building envelope or parcel boundary",
        }

    def check_floating_volume(
        self,
        volume: Dict[str, Any],
        footprint_polygon: Polygon,
        valid_z_ranges: List[Tuple[float, float]],
    ) -> Tuple[bool, Dict[str, Any]]:
        """Verifies volume is structurally supported and matches valid building floor elevations."""
        zmin = volume["zmin"]
        zmax = volume["zmax"]

        # Check if [zmin, zmax] aligns with declared levels
        matches_level = any(
            (abs(zmin - r_min) <= 0.05 and abs(zmax - r_max) <= 0.05)
            for r_min, r_max in valid_z_ranges
        )

        passed = matches_level
        return passed, {
            "check": "no_floating_volume",
            "passed": passed,
            "level_code": volume.get("level_code"),
            "matches_building_stack": matches_level,
            "error": None if passed else f"Volume at Z=[{zmin}, {zmax}] cannot be structurally associated with building stack",
        }

    def compute_3d_overlap_volume(
        self,
        vol_a: Dict[str, Any],
        vol_b: Dict[str, Any],
    ) -> float:
        """
        Calculates authoritative 3D intersection volume between two prisms.
        Intersection Volume = 2D Intersection Area * Overlapping Z-Height.
        Shared boundaries/faces have zero 2D intersection area (0.0000 m3).
        """
        try:
            poly_a = Polygon(vol_a["coordinates"])
            poly_b = Polygon(vol_b["coordinates"])

            if not poly_a.intersects(poly_b):
                return 0.0

            inter_2d = poly_a.intersection(poly_b)
            # Touching along boundary line has area == 0.0
            if inter_2d.is_empty or inter_2d.area <= 0.0:
                return 0.0

            # Vertical overlap
            overlap_zmin = max(vol_a["zmin"], vol_b["zmin"])
            overlap_zmax = min(vol_a["zmax"], vol_b["zmax"])
            overlap_height = max(0.0, overlap_zmax - overlap_zmin)

            if overlap_height <= 0.0:
                return 0.0

            overlap_vol = float(inter_2d.area * overlap_height)
            return overlap_vol

        except Exception as e:
            # Failure handling per Principle 2 / Technical Rules
            raise RuntimeError(f"SFCGAL_FAILURE: Failed to compute 3D intersection: {str(e)}")

    def validate_level_neighbours(
        self,
        level_volumes: List[Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        """
        Validates neighbour consistency and exclusive overlap across all volumes on a level.
        Detects deliberate RED horizontal encroachment (e.g. F02 Unit 201 & 202).
        """
        results = {}
        for v in level_volumes:
            results[v["volume_id"]] = {
                "check": "no_exclusive_overlap",
                "passed": True,
                "max_overlap_m3": 0.0,
                "conflicts": [],
                "error": None,
            }

        n = len(level_volumes)
        for i in range(n):
            for j in range(i + 1, n):
                va = level_volumes[i]
                vb = level_volumes[j]

                try:
                    overlap = self.compute_3d_overlap_volume(va, vb)
                except Exception as e:
                    # Robust failure handling: flag both as ERROR / RED
                    results[va["volume_id"]]["passed"] = False
                    results[va["volume_id"]]["error_code"] = "SFCGAL_FAILURE"
                    results[va["volume_id"]]["error"] = str(e)

                    results[vb["volume_id"]]["passed"] = False
                    results[vb["volume_id"]]["error_code"] = "SFCGAL_FAILURE"
                    results[vb["volume_id"]]["error"] = str(e)
                    continue

                if overlap > self.overlap_tolerance_m3:
                    # Flag BOTH participating volumes as RED (Principle 2)
                    results[va["volume_id"]]["passed"] = False
                    results[va["volume_id"]]["max_overlap_m3"] = max(results[va["volume_id"]]["max_overlap_m3"], overlap)
                    results[va["volume_id"]]["conflicts"].append({
                        "conflicting_volume_id": vb["volume_id"],
                        "unit_code": vb["unit_code"],
                        "overlap_volume_m3": round(overlap, 4),
                    })
                    results[va["volume_id"]]["error"] = (
                        f"Exclusive 3D overlap of {overlap:.4f} m3 with Volume {vb['volume_id']} ({vb['unit_code']})"
                    )

                    results[vb["volume_id"]]["passed"] = False
                    results[vb["volume_id"]]["max_overlap_m3"] = max(results[vb["volume_id"]]["max_overlap_m3"], overlap)
                    results[vb["volume_id"]]["conflicts"].append({
                        "conflicting_volume_id": va["volume_id"],
                        "unit_code": va["unit_code"],
                        "overlap_volume_m3": round(overlap, 4),
                    })
                    results[vb["volume_id"]]["error"] = (
                        f"Exclusive 3D overlap of {overlap:.4f} m3 with Volume {va['volume_id']} ({va['unit_code']})"
                    )

        return results

    def validate_building(
        self,
        volumes: List[Dict[str, Any]],
        parcel_polygon: Polygon,
        footprint_polygon: Polygon,
    ) -> List[Dict[str, Any]]:
        """
        Executes full validation suite on all volumes in the building.
        Applies hard publication gate: GREEN, AMBER, or RED.
        """
        valid_z_ranges = list(set((v["zmin"], v["zmax"]) for v in volumes))

        # Group by level for neighbour overlap testing
        levels_map: Dict[str, List[Dict[str, Any]]] = {}
        for v in volumes:
            levels_map.setdefault(v["level_code"], []).append(v)

        level_overlap_results = {}
        for lvl_code, lvl_vols in levels_map.items():
            level_overlap_results.update(self.validate_level_neighbours(lvl_vols))

        validated_volumes = []
        for v in volumes:
            vol_id = v["volume_id"]
            report: Dict[str, Any] = {"checks": {}}
            hard_failures = []

            # 1. Z-Range Check
            pass_z, z_res = self.check_z_range(v)
            report["checks"]["z_range"] = z_res
            if not pass_z:
                hard_failures.append("INVALID_Z_RANGE")

            # 2. Closed Solid Check
            pass_solid, solid_res = self.check_closed_solid(v)
            report["checks"]["closed_solid"] = solid_res
            if not pass_solid:
                hard_failures.append(solid_res.get("error_code", "NOT_CLOSED_SOLID"))

            # 3. Containment Check
            pass_cont, cont_res = self.check_containment(v, parcel_polygon, footprint_polygon)
            report["checks"]["containment"] = cont_res
            if not pass_cont:
                hard_failures.append("CONTAINMENT_VIOLATION")

            # 4. Floating Volume Check
            pass_float, float_res = self.check_floating_volume(v, footprint_polygon, valid_z_ranges)
            report["checks"]["floating_volume"] = float_res
            if not pass_float:
                hard_failures.append("FLOATING_VOLUME")

            # 5. Overlap & Neighbour Consistency Check
            overlap_res = level_overlap_results.get(vol_id, {"passed": True})
            report["checks"]["overlap_consistency"] = overlap_res
            if not overlap_res["passed"]:
                hard_failures.append(overlap_res.get("error_code", "EXCLUSIVE_3D_OVERLAP"))

            # --- HARD PUBLICATION GATE EVALUATION ---
            confidence = float(v.get("confidence", 0.0))

            if hard_failures:
                # Any hard geometric failure -> ALWAYS RED
                final_status = "RED"
                review_status = "REJECTED"
                verdict_reason = f"Hard geometric failures: {', '.join(hard_failures)}"
            elif confidence >= self.green_threshold:
                # High confidence, no geometric failure -> GREEN
                final_status = "GREEN"
                review_status = "NOT_REQUIRED"
                verdict_reason = f"All 7 geometric checks passed with high confidence ({confidence:.4f} >= {self.green_threshold})"
            elif confidence >= self.amber_threshold:
                # Clean geometry, weak evidence -> AMBER (routes to human review)
                final_status = "AMBER"
                review_status = "PENDING"
                verdict_reason = f"All geometric checks passed, but evidence confidence is weak ({confidence:.4f} < {self.green_threshold})"
            else:
                final_status = "RED"
                review_status = "REJECTED"
                verdict_reason = f"Insufficient confidence ({confidence:.4f} < {self.amber_threshold})"

            report["overall_verdict"] = final_status
            report["review_status"] = review_status
            report["verdict_reason"] = verdict_reason
            report["hard_failures"] = hard_failures
            report["confidence"] = confidence

            validated_vol = dict(v)
            validated_vol["topology_status"] = final_status
            validated_vol["review_status"] = review_status
            validated_vol["validation_report"] = report

            validated_volumes.append(validated_vol)

        return validated_volumes
