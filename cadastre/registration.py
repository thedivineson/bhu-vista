"""
Floor-Plan Registration Engine for BHU-VISTA 3D.
Performs 2D similarity and affine transformation aligning local CAD/GeoJSON
floor plans to the authoritative GIS building footprint in EPSG:32643.

Principles Enforced:
- Principle 2: Evidence-backed, topology-first (records registration residuals).
- Principle 4: No invented geometry (preserves architectural polygons).
- Principle 7: Provenance everywhere (metrics, timestamps, control point counts).
- Principle 8: Rule-based first.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple
import numpy as np
from shapely.geometry import Polygon
from shapely.affinity import affine_transform

from config.settings import settings


class FloorplanRegistrationEngine:
    """Computes coordinate transformations from local architectural floor plans to GIS space."""

    @staticmethod
    def compute_similarity_transform(
        source_pts: np.ndarray,
        target_pts: np.ndarray,
    ) -> Tuple[np.ndarray, float]:
        """
        Solves least-squares 2D similarity transformation:
        [X, Y]^T = [a, -b; b, a] * [x, y]^T + [tx, ty]^T
        
        Args:
            source_pts: (N, 2) array of local coordinates.
            target_pts: (N, 2) array of world GIS coordinates in EPSG:32643.
            
        Returns:
            matrix_params: tuple of (a, b, d, e, xoff, yoff) for Shapely affine_transform
            residual_rmse_m: root mean square error in metres across control points
        """
        n = len(source_pts)
        if n < 2:
            raise ValueError(f"Registration requires at least 2 control points, got {n}")

        # Formulate system: A * [a, b, tx, ty]^T = target
        A = np.zeros((2 * n, 4))
        rhs = np.zeros(2 * n)

        for i in range(n):
            x, y = source_pts[i]
            X, Y = target_pts[i]

            A[2 * i] = [x, -y, 1.0, 0.0]
            rhs[2 * i] = X

            A[2 * i + 1] = [y, x, 0.0, 1.0]
            rhs[2 * i + 1] = Y

        params, residuals, rank, s = np.linalg.lstsq(A, rhs, rcond=None)
        a, b, tx, ty = params

        # Compute RMSE across control points
        pred_x = a * source_pts[:, 0] - b * source_pts[:, 1] + tx
        pred_y = b * source_pts[:, 0] + a * source_pts[:, 1] + ty
        diffs = np.column_stack([pred_x, pred_y]) - target_pts
        rmse = float(np.sqrt(np.mean(np.sum(diffs ** 2, axis=1))))

        # Shapely affine_transform expects matrix:
        # [a, b, d, e, xoff, yoff] representing:
        # x' = a * x + b * y + xoff
        # y' = d * x + e * y + yoff
        # For similarity: a=a, b=-b, d=b, e=a, xoff=tx, yoff=ty
        transform_matrix = [a, -b, b, a, tx, ty]

        return transform_matrix, rmse

    @staticmethod
    def transform_polygon(polygon: Polygon, transform_matrix: List[float]) -> Polygon:
        """Applies affine/similarity transformation matrix to a Shapely Polygon."""
        return affine_transform(polygon, transform_matrix)

    @classmethod
    def register_floorplan(
        cls,
        local_unit_polygons: List[Dict[str, Any]],
        control_points_source: np.ndarray,
        control_points_target: np.ndarray,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Registers local floor plan units to world GIS coordinates.
        Returns:
            registered_units: list of units with coordinates in EPSG:32643
            registration_evidence: dict containing residual RMSE, control points count, etc.
        """
        transform_matrix, residual_rmse = cls.compute_similarity_transform(
            control_points_source,
            control_points_target,
        )

        registered_units = []
        for unit in local_unit_polygons:
            local_poly = Polygon(unit["coordinates"])
            world_poly = cls.transform_polygon(local_poly, transform_matrix)

            unit_copy = dict(unit)
            unit_copy["coordinates"] = [list(pt) for pt in world_poly.exterior.coords]
            unit_copy["area_sqm"] = world_poly.area
            registered_units.append(unit_copy)

        registration_evidence = {
            "control_points_count": len(control_points_source),
            "registration_residual_m": round(residual_rmse, 4),
            "crs": settings.HORIZONTAL_CRS,
            "algorithm": "2D-Similarity-LeastSquares",
            "registered_at": datetime.now(timezone.utc).isoformat(),
        }

        return registered_units, registration_evidence


if __name__ == "__main__":
    # Test registration: local grid (0,0) to (24,16) -> UTM BKC coordinates
    src = np.array([[0.0, 0.0], [24.0, 0.0], [24.0, 16.0], [0.0, 16.0]])
    dst = np.array([
        [278492.0, 2110495.0],
        [278516.0, 2110495.0],
        [278516.0, 2110511.0],
        [278492.0, 2110511.0],
    ])

    matrix, rmse = FloorplanRegistrationEngine.compute_similarity_transform(src, dst)
    print(f"Computed transform matrix: {matrix}")
    print(f"Registration RMSE: {rmse:.4f} m")
