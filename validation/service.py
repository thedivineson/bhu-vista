"""
Validation & Review Queue Service for BHU-VISTA 3D.
Manages topology validation runs, review queue lifecycle,
and immutable audit log recording for Human-in-the-Loop workflows.

Principles Enforced:
- Principle 4: Human-in-the-loop (AMBER review queue).
- Principle 5: Hard publication gate (RED volumes can never be approved).
- Principle 7: Provenance everywhere (immutable append-only audit trail).
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from shapely.geometry import Polygon
from sqlalchemy.orm import Session

from config.settings import settings
from cadastre.volume_builder import VolumeBuilder
from cadastre.db_models import Volume, ReviewAudit, Evidence
from validation.engine import TopologyValidationEngine


class ValidationReviewService:
    """Coordinates validation pipeline execution and human review state transitions."""

    def __init__(self, db_session: Optional[Session] = None):
        self.db = db_session
        self.engine = TopologyValidationEngine()
        self.builder = VolumeBuilder()
        self._in_memory_reviews: Dict[str, str] = {}
        self._audit_log: List[Dict[str, Any]] = []

    def run_full_validation(self) -> List[Dict[str, Any]]:
        """
        Builds all volumes, executes the 7-stage topology validation,
        and applies the publication gate.
        """
        # 1. Build extruded volumes
        raw_volumes = self.builder.build_all_volumes()

        # Ingest coordinates into raw_volumes for exact 2D/3D intersection checks
        for v in raw_volumes:
            lvl = next(l for l in self.builder.spec["levels"] if l["level_code"] == v["level_code"])
            unit_spec = next(u for u in lvl["units"] if u["unit_code"] == v["unit_code"])
            v["coordinates"] = unit_spec["coordinates"]

        # 2. Extract parcel and footprint boundaries
        parcel_poly = Polygon(self.builder.spec["parcel"]["coordinates"])
        footprint_poly = Polygon(self.builder.spec["building_footprint"]["coordinates"])

        # 3. Execute authoritative validation
        validated = self.engine.validate_building(raw_volumes, parcel_poly, footprint_poly)

        # 4. If DB session provided, persist to database
        if self.db:
            for v in validated:
                vol_row = self.db.query(Volume).filter_by(
                    parent_ulpin=v["parent_ulpin"],
                    volume_id=v["volume_id"],
                    version=v["version"],
                ).first()

                if not vol_row:
                    vol_row = Volume(
                        volume_id=v["volume_id"],
                        parent_ulpin=v["parent_ulpin"],
                        level_code=v["level_code"],
                        unit_code=v["unit_code"],
                        zmin=v["zmin"],
                        zmax=v["zmax"],
                        area=v["area_sqm"],
                        volume=v["volume_m3"],
                        confidence=v["confidence"],
                        topology_status=v["topology_status"],
                        review_status=v["review_status"],
                        validation_report=v["validation_report"],
                        geom_wkt=v["geom_wkt"],
                        data_origin=v["data_origin"],
                        algorithm_version=v["algorithm_version"],
                        version=v["version"],
                        superseded=v["superseded"],
                    )
                    self.db.add(vol_row)
                    self.db.flush()

                    # Add Evidence
                    ev = v["evidence"]
                    evidence_row = Evidence(
                        volume_row_id=vol_row.id,
                        source_type=ev["source_type"],
                        control_points_count=ev["control_points_count"],
                        registration_residual_m=ev["registration_residual_m"],
                        point_density_pct=ev["point_density_pct"],
                        edge_alignment_score=ev["edge_alignment_score"],
                        confidence_score=ev["confidence_score"],
                        metadata_json={"observed_points": ev.get("observed_point_count", 0)},
                        data_origin=v["data_origin"],
                    )
                    self.db.add(evidence_row)
                else:
                    vol_row.topology_status = v["topology_status"]
                    vol_row.review_status = v["review_status"]
                    vol_row.validation_report = v["validation_report"]
                    vol_row.confidence = v["confidence"]

            self.db.commit()
        else:
            # Standalone/in-memory mode: apply prior human reviews
            for v in validated:
                vid = v["volume_id"]
                if vid in self._in_memory_reviews:
                    v["review_status"] = self._in_memory_reviews[vid]
                    v["validation_report"]["review_status"] = self._in_memory_reviews[vid]

        return validated

    def get_review_queue(self) -> List[Dict[str, Any]]:
        """Returns all volumes currently pending human review (AMBER with review_status=PENDING)."""
        all_vols = self.run_full_validation()
        return [
            v for v in all_vols
            if v["topology_status"] == "AMBER" and v["review_status"] == "PENDING"
        ]

    def approve_volume(
        self,
        volume_id: str,
        reviewer: str,
        reason: str,
    ) -> Dict[str, Any]:
        """
        Human review approval for AMBER volumes.
        Enforces:
        - Reason must be non-empty.
        - Reviewer must be non-empty.
        - RED volumes can NEVER be approved (raises ValueError).
        - Records immutable entry in review_audit.
        """
        if not reviewer or not reviewer.strip():
            raise ValueError("Reviewer name is required and cannot be empty.")
        if not reason or not reason.strip():
            raise ValueError("Approval reason is mandatory and cannot be empty.")

        all_vols = self.run_full_validation()
        vol = next((v for v in all_vols if v["volume_id"] == volume_id), None)
        if not vol:
            raise KeyError(f"Volume with ID '{volume_id}' not found.")

        # Hard Gate: RED volumes can NEVER be approved
        if vol["topology_status"] == "RED":
            raise ValueError(
                f"ERR_CANNOT_APPROVE_RED: Volume '{volume_id}' is flagged RED due to hard geometric failure "
                f"({vol['validation_report']['verdict_reason']}). RED volumes can NEVER be approved."
            )

        if vol["topology_status"] != "AMBER":
            raise ValueError(
                f"Only AMBER volumes can undergo review approval. Volume '{volume_id}' is '{vol['topology_status']}'."
            )

        prev_status = vol["review_status"]
        vol["review_status"] = "APPROVED"
        self._in_memory_reviews[volume_id] = "APPROVED"

        audit_entry = {
            "volume_id": volume_id,
            "action": "APPROVE",
            "reviewer": reviewer.strip(),
            "reason": reason.strip(),
            "previous_status": prev_status,
            "resulting_review_status": "APPROVED",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._audit_log.append(audit_entry)

        # If DB is active, record in database
        if self.db:
            vol_row = self.db.query(Volume).filter_by(volume_id=volume_id).first()
            if vol_row:
                vol_row.review_status = "APPROVED"
                audit_row = ReviewAudit(
                    volume_row_id=vol_row.id,
                    action="APPROVE",
                    reviewer=reviewer.strip(),
                    reason=reason.strip(),
                    previous_status=prev_status,
                    resulting_review_status="APPROVED",
                )
                self.db.add(audit_row)
                self.db.commit()

        return {
            "status": "APPROVED",
            "volume_id": volume_id,
            "topology_status": vol["topology_status"],  # Original machine verdict never rewritten
            "review_status": "APPROVED",
            "audit": audit_entry,
        }

    def reject_volume(
        self,
        volume_id: str,
        reviewer: str,
        reason: str,
    ) -> Dict[str, Any]:
        """Human review rejection for AMBER volumes."""
        if not reviewer or not reviewer.strip():
            raise ValueError("Reviewer name is required and cannot be empty.")
        if not reason or not reason.strip():
            raise ValueError("Rejection reason is mandatory and cannot be empty.")

        all_vols = self.run_full_validation()
        vol = next((v for v in all_vols if v["volume_id"] == volume_id), None)
        if not vol:
            raise KeyError(f"Volume with ID '{volume_id}' not found.")

        prev_status = vol["review_status"]
        vol["review_status"] = "REJECTED"
        self._in_memory_reviews[volume_id] = "REJECTED"

        audit_entry = {
            "volume_id": volume_id,
            "action": "REJECT",
            "reviewer": reviewer.strip(),
            "reason": reason.strip(),
            "previous_status": prev_status,
            "resulting_review_status": "REJECTED",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._audit_log.append(audit_entry)

        if self.db:
            vol_row = self.db.query(Volume).filter_by(volume_id=volume_id).first()
            if vol_row:
                vol_row.review_status = "REJECTED"
                audit_row = ReviewAudit(
                    volume_row_id=vol_row.id,
                    action="REJECT",
                    reviewer=reviewer.strip(),
                    reason=reason.strip(),
                    previous_status=prev_status,
                    resulting_review_status="REJECTED",
                )
                self.db.add(audit_row)
                self.db.commit()

        return {
            "status": "REJECTED",
            "volume_id": volume_id,
            "topology_status": vol["topology_status"],
            "review_status": "REJECTED",
            "audit": audit_entry,
        }

    def get_audit_trail(self) -> List[Dict[str, Any]]:
        """Returns the append-only audit trail."""
        if self.db:
            rows = self.db.query(ReviewAudit).order_by(ReviewAudit.timestamp.asc()).all()
            return [
                {
                    "audit_id": r.audit_id,
                    "volume_row_id": r.volume_row_id,
                    "action": r.action,
                    "reviewer": r.reviewer,
                    "reason": r.reason,
                    "previous_status": r.previous_status,
                    "resulting_review_status": r.resulting_review_status,
                    "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                }
                for r in rows
            ]
        return list(self._audit_log)
