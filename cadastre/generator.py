"""
Deterministic Cadastral & Floor Plan Data Generator for BHU-VISTA 3D.
Reads sample_data/building_spec.json as the SINGLE SOURCE OF TRUTH
and outputs standardized GeoJSON and metadata artifacts.

Principles Enforced:
- Principle 7: Provenance everywhere (algorithm_version, data_origin, timestamp).
- Principle 9: Adapter pattern for cadastral sources.
- Principle 12: Honest labelling (data_origin = SYNTHETIC).
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from config.settings import settings


class CadastralDataGenerator:
    """Generates standardized 2D parcel and floor-plan GeoJSONs from the building specification."""

    def __init__(self, spec_path: Path | None = None):
        self.spec_path = spec_path or settings.BUILDING_SPEC_PATH
        self.spec = self._load_spec()

    def _load_spec(self) -> Dict[str, Any]:
        """Loads and verifies the building specification from disk."""
        if not self.spec_path.exists():
            raise FileNotFoundError(f"Building specification not found at: {self.spec_path}")
        with open(self.spec_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Basic schema integrity verification
        required_keys = ["seed", "data_origin", "crs", "parcel", "building_footprint", "levels"]
        for key in required_keys:
            if key not in data:
                raise ValueError(f"Invalid building specification: missing required key '{key}'")
        
        # Verify 14-digit ULPIN format
        parent_ulpin = data["parcel"].get("parent_ulpin", "")
        if not (len(parent_ulpin) == 14 and parent_ulpin.isdigit()):
            raise ValueError(f"Parent ULPIN must be a 14-digit numeric string, got '{parent_ulpin}'")

        return data

    def generate_parcel_geojson(self) -> Dict[str, Any]:
        """Generates GeoJSON FeatureCollection for the parent cadastral parcel."""
        parcel = self.spec["parcel"]
        feature = {
            "type": "Feature",
            "properties": {
                "parent_ulpin": parcel["parent_ulpin"],
                "district": parcel.get("district", "Mumbai Suburban"),
                "taluka": parcel.get("taluka", "Bandra"),
                "village": parcel.get("village", "Kurla"),
                "survey_number": parcel.get("survey_number", "142/3"),
                "area_sqm": parcel["area_sqm"],
                "crs": self.spec["crs"],
                "data_origin": self.spec["data_origin"],
                "algorithm_version": settings.ALGORITHM_VERSION,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [parcel["coordinates"]],
            },
        }
        return {
            "type": "FeatureCollection",
            "name": f"Parcel_{parcel['parent_ulpin']}",
            "crs": {
                "type": "name",
                "properties": {"name": f"urn:ogc:def:crs:{self.spec['crs'].replace(':', '::')}"},
            },
            "features": [feature],
        }

    def generate_footprint_geojson(self) -> Dict[str, Any]:
        """Generates GeoJSON FeatureCollection for the building envelope footprint."""
        footprint = self.spec["building_footprint"]
        feature = {
            "type": "Feature",
            "properties": {
                "building_id": self.spec["building_id"],
                "building_name": self.spec["building_name"],
                "parent_ulpin": self.spec["parcel"]["parent_ulpin"],
                "area_sqm": footprint["area_sqm"],
                "envelope_tolerance_m": self.spec["envelope_tolerance_m"],
                "crs": self.spec["crs"],
                "data_origin": self.spec["data_origin"],
                "algorithm_version": settings.ALGORITHM_VERSION,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [footprint["coordinates"]],
            },
        }
        return {
            "type": "FeatureCollection",
            "name": f"Footprint_{self.spec['building_id']}",
            "crs": {
                "type": "name",
                "properties": {"name": f"urn:ogc:def:crs:{self.spec['crs'].replace(':', '::')}"},
            },
            "features": [feature],
        }

    def generate_floorplans_geojson(self) -> Dict[str, Any]:
        """Generates GeoJSON FeatureCollection containing all individual subdivided unit polygons."""
        features = []
        for level in self.spec["levels"]:
            level_code = level["level_code"]
            zmin = level["zmin"]
            zmax = level["zmax"]
            is_subsurface = level["is_subsurface"]

            for unit in level["units"]:
                props = {
                    "unit_code": unit["unit_code"],
                    "unit_name": unit["unit_name"],
                    "level_code": level_code,
                    "level_name": level["level_name"],
                    "parent_ulpin": self.spec["parcel"]["parent_ulpin"],
                    "building_id": self.spec["building_id"],
                    "order_index": unit["order_index"],
                    "expected_volume_id": unit["expected_volume_id"],
                    "use_type": unit["use_type"],
                    "zmin": zmin,
                    "zmax": zmax,
                    "height_m": level["height_m"],
                    "is_subsurface": is_subsurface,
                    "deliberate_conflict_participant": unit.get("deliberate_conflict_participant", False),
                    "deliberate_conflict_description": unit.get("deliberate_conflict_description"),
                    "deliberate_amber_low_confidence": unit.get("deliberate_amber_low_confidence", False),
                    "deliberate_amber_description": unit.get("deliberate_amber_description"),
                    "evidence_spec": unit.get("evidence_spec", {}),
                    "crs": self.spec["crs"],
                    "data_origin": self.spec["data_origin"],
                    "algorithm_version": settings.ALGORITHM_VERSION,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
                features.append({
                    "type": "Feature",
                    "properties": props,
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [unit["coordinates"]],
                    },
                })

        return {
            "type": "FeatureCollection",
            "name": f"Floorplans_{self.spec['building_id']}",
            "crs": {
                "type": "name",
                "properties": {"name": f"urn:ogc:def:crs:{self.spec['crs'].replace(':', '::')}"},
            },
            "features": features,
        }

    def generate_units_metadata(self) -> Dict[str, Any]:
        """Generates unit catalogue and deterministic volume mapping."""
        units_list = []
        for level in self.spec["levels"]:
            for unit in level["units"]:
                units_list.append({
                    "volume_id": unit["expected_volume_id"],
                    "unit_code": unit["unit_code"],
                    "unit_name": unit["unit_name"],
                    "level_code": level["level_code"],
                    "zmin": level["zmin"],
                    "zmax": level["zmax"],
                    "parent_ulpin": self.spec["parcel"]["parent_ulpin"],
                    "deliberate_conflict": unit.get("deliberate_conflict_participant", False),
                    "deliberate_amber": unit.get("deliberate_amber_low_confidence", False),
                    "evidence": unit.get("evidence_spec", {}),
                    "data_origin": self.spec["data_origin"],
                })

        return {
            "building_id": self.spec["building_id"],
            "parent_ulpin": self.spec["parcel"]["parent_ulpin"],
            "total_units": len(units_list),
            "units": units_list,
            "data_origin": self.spec["data_origin"],
            "algorithm_version": settings.ALGORITHM_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def run_all(self, output_dir: Path | None = None) -> Dict[str, Path]:
        """Executes all generators and persists outputs to the target directory."""
        target_dir = output_dir or settings.SAMPLE_DATA_DIR
        target_dir.mkdir(parents=True, exist_ok=True)

        outputs = {
            "parcel": target_dir / "parcel.geojson",
            "footprint": target_dir / "footprint.geojson",
            "floorplans": target_dir / "floorplans.geojson",
            "metadata": target_dir / "units_metadata.json",
        }

        with open(outputs["parcel"], "w", encoding="utf-8") as f:
            json.dump(self.generate_parcel_geojson(), f, indent=2)

        with open(outputs["footprint"], "w", encoding="utf-8") as f:
            json.dump(self.generate_footprint_geojson(), f, indent=2)

        with open(outputs["floorplans"], "w", encoding="utf-8") as f:
            json.dump(self.generate_floorplans_geojson(), f, indent=2)

        with open(outputs["metadata"], "w", encoding="utf-8") as f:
            json.dump(self.generate_units_metadata(), f, indent=2)

        return outputs


if __name__ == "__main__":
    generator = CadastralDataGenerator()
    generated_files = generator.run_all()
    print("Cadastral data generation complete. Created:")
    for key, path in generated_files.items():
        print(f"  - {key}: {path}")
