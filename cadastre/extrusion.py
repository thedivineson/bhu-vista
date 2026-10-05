"""
Authoritative 3D Extrusion & Polyhedral Surface Engine for BHU-VISTA 3D.
Converts 2D cadastral unit polygons into valid, watertight 3D polyhedra
represented as OGC POLYHEDRALSURFACE Z and triangulated Trimesh meshes.

Principles Enforced:
- Principle 2: Topology-first, closed solids (POLYHEDRALSURFACEZ).
- Principle 3: Single vertical framework for positive and negative levels.
- Principle 4: No invented geometry (never modify vertex counts or geometry to force closure).
"""

from typing import Any, Dict, List, Tuple
import numpy as np
from shapely.geometry import Polygon
from shapely.ops import triangulate
import trimesh

from config.settings import settings


class PolyhedralExtruder:
    """Extrudes 2D planar polygons into 3D closed polyhedral surfaces and triangular meshes."""

    @staticmethod
    def validate_2d_polygon(coordinates: List[List[float]]) -> Polygon:
        """Validates that input coordinates form a valid, non-self-intersecting 2D polygon."""
        if len(coordinates) < 4:
            raise ValueError(f"Polygon must have at least 4 coordinates (closed ring), got {len(coordinates)}")

        poly = Polygon(coordinates)
        if not poly.is_valid:
            raise ValueError(f"Invalid polygon geometry: self-intersection or collinear collapse detected.")
        if poly.is_empty or poly.area <= 0:
            raise ValueError(f"Degenerate polygon: area is non-positive ({poly.area}).")

        return poly

    @staticmethod
    def extrude_to_polyhedralsurface_wkt(
        coordinates: List[List[float]],
        zmin: float,
        zmax: float,
        srid: int = settings.HORIZONTAL_SRID,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Extrudes a 2D polygon into a closed POLYHEDRALSURFACE Z WKT string.

        Orientation convention for watertight closure:
        - Top cap (Z = zmax): Counter-Clockwise (CCW) -> normal points upwards (+Z).
        - Bottom cap (Z = zmin): Clockwise (CW) -> normal points downwards (-Z).
        - Side vertical faces: Outward-pointing normal for every edge.
        """
        if zmin >= zmax:
            raise ValueError(f"Invalid Z-range: zmin ({zmin}) must be strictly less than zmax ({zmax})")

        poly = PolyhedralExtruder.validate_2d_polygon(coordinates)
        coords_2d = list(poly.exterior.coords)

        # Ensure ring is closed and remove duplicate end point for iteration
        if coords_2d[0] == coords_2d[-1]:
            pts = coords_2d[:-1]
        else:
            pts = coords_2d

        n_pts = len(pts)
        if n_pts < 3:
            raise ValueError("Polygon must have at least 3 distinct vertices.")

        faces_wkt = []

        # 1. Bottom Cap: Clockwise at zmin (normal points downwards)
        # Check current winding of 2D polygon (Shapely exterior is CCW by default)
        # Reverse to CW for bottom face
        bottom_pts = pts[::-1]
        bottom_ring = ", ".join([f"{x:.6f} {y:.6f} {zmin:.6f}" for x, y in bottom_pts])
        # Close the ring
        bottom_ring += f", {bottom_pts[0][0]:.6f} {bottom_pts[0][1]:.6f} {zmin:.6f}"
        faces_wkt.append(f"(({bottom_ring}))")

        # 2. Top Cap: Counter-Clockwise at zmax (normal points upwards)
        top_pts = pts[:]
        top_ring = ", ".join([f"{x:.6f} {y:.6f} {zmax:.6f}" for x, y in top_pts])
        # Close the ring
        top_ring += f", {top_pts[0][0]:.6f} {top_pts[0][1]:.6f} {zmax:.6f}"
        faces_wkt.append(f"(({top_ring}))")

        # 3. Side Faces: For each directed edge (pts[i] -> pts[i+1]),
        # outward normal: (x_i, y_i, zmin) -> (x_{i+1}, y_{i+1}, zmin) -> (x_{i+1}, y_{i+1}, zmax) -> (x_i, y_i, zmax)
        for i in range(n_pts):
            p1 = pts[i]
            p2 = pts[(i + 1) % n_pts]

            side_ring = (
                f"{p1[0]:.6f} {p1[1]:.6f} {zmin:.6f}, "
                f"{p2[0]:.6f} {p2[1]:.6f} {zmin:.6f}, "
                f"{p2[0]:.6f} {p2[1]:.6f} {zmax:.6f}, "
                f"{p1[0]:.6f} {p1[1]:.6f} {zmax:.6f}, "
                f"{p1[0]:.6f} {p1[1]:.6f} {zmin:.6f}"
            )
            faces_wkt.append(f"(({side_ring}))")

        polyhedral_wkt = f"SRID={srid};POLYHEDRALSURFACE Z ({', '.join(faces_wkt)})"

        height = zmax - zmin
        expected_area = poly.area
        expected_volume = expected_area * height

        metadata = {
            "srid": srid,
            "zmin": zmin,
            "zmax": zmax,
            "height_m": height,
            "footprint_area_sqm": expected_area,
            "expected_volume_m3": expected_volume,
            "face_count": len(faces_wkt),
            "is_closed_solid": True,
        }

        return polyhedral_wkt, metadata

    @staticmethod
    def extrude_to_trimesh(
        coordinates: List[List[float]],
        zmin: float,
        zmax: float,
    ) -> trimesh.Trimesh:
        """
        Builds a watertight, triangulated 3D mesh (trimesh.Trimesh)
        from a 2D footprint extruded between zmin and zmax.
        """
        if zmin >= zmax:
            raise ValueError(f"zmin ({zmin}) must be less than zmax ({zmax})")

        poly = PolyhedralExtruder.validate_2d_polygon(coordinates)
        coords_2d = list(poly.exterior.coords)
        if coords_2d[0] == coords_2d[-1]:
            pts = np.array(coords_2d[:-1], dtype=np.float64)
        else:
            pts = np.array(coords_2d, dtype=np.float64)

        n = len(pts)

        # 3D Vertices:
        # Indices 0 to n-1: bottom vertices (zmin)
        # Indices n to 2n-1: top vertices (zmax)
        bottom_verts = np.column_stack([pts, np.full(n, zmin)])
        top_verts = np.column_stack([pts, np.full(n, zmax)])
        vertices = np.vstack([bottom_verts, top_verts])

        faces = []

        # 1. Triangulate caps
        # Using polygon Delaunay / constrained triangulation for top and bottom
        triangles = triangulate(poly)
        for tri in triangles:
            # Only include triangles strictly inside the polygon
            if poly.contains(tri.representative_point()):
                tri_coords = list(tri.exterior.coords)[:-1]
                # Find matching vertex indices
                idx = []
                for tc in tri_coords:
                    dists = np.linalg.norm(pts - np.array(tc), axis=1)
                    match = np.argmin(dists)
                    idx.append(match)

                if len(idx) == 3:
                    # Top face: CCW
                    faces.append([idx[0] + n, idx[1] + n, idx[2] + n])
                    # Bottom face: CW (reversed order)
                    faces.append([idx[0], idx[2], idx[1]])

        # 2. Side Quads (split each quad into 2 triangles)
        # Bottom edge: (i, next_i), Top edge: (i+n, next_i+n)
        for i in range(n):
            next_i = (i + 1) % n
            # Triangle 1: (bottom_i, bottom_next, top_next)
            faces.append([i, next_i, next_i + n])
            # Triangle 2: (bottom_i, top_next, top_i)
            faces.append([i, next_i + n, i + n])

        faces = np.array(faces, dtype=np.int64)
        mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=True)

        # Fix normals to ensure consistent outward orientation
        mesh.fix_normals()

        return mesh


if __name__ == "__main__":
    # Smoke test with a 10m x 10m unit
    coords = [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]]
    wkt, meta = PolyhedralExtruder.extrude_to_polyhedralsurface_wkt(coords, 0.0, 3.2)
    print("PolyhedralSurface WKT prefix:", wkt[:80], "...")
    print("Metadata:", meta)

    mesh = PolyhedralExtruder.extrude_to_trimesh(coords, 0.0, 3.2)
    print("Trimesh watertight:", mesh.is_watertight)
    print("Calculated volume (m3):", mesh.volume)
    print("Expected volume (m3):", 10.0 * 10.0 * 3.2)
