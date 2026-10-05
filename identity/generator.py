"""
Authoritative 3D ULPIN Identity Generator for BHU-VISTA 3D.
Extends 2D ULPIN parcels into unique, validated 3D volumetric identities.

Principles Enforced:
- Principle 2: Identity issued ONLY after topology validation passes.
- Principle 5: Hard publication gate:
    * GREEN -> GREEN_AUTO
    * AMBER + APPROVED -> AMBER_HUMAN_APPROVED
    * AMBER (PENDING/REJECTED) -> NEVER issued (PermissionError)
    * RED -> NEVER issued under any path (PermissionError)
- Principle 7: Provenance & Versioning (re-runs increment version, mark previous superseded, retain volume IDs).
"""

import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.orm import Session

from config.settings import settings
from cadastre.db_models import Volume, Ulpin3D


class Ulpin3DGenerator:
    """Manages 3D ULPIN generation, issuance eligibility gating, and registry lookup."""

    def __init__(self, db_session: Optional[Session] = None):
        self.db = db_session
        self._in_memory_registry: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def format_ulpin3d_string(parent_ulpin: str, level_code: str, zmin: float, zmax: float, volume_id: str) -> str:
        """
        Formats standard 3D ULPIN string according to SIH26011 specification:
        <ParentULPIN>|LV=<Level>|Z=<Zmin>:<Zmax>|V=<VolumeID>
        Example: 12345678901234|LV=F03|Z=9.60:12.80|V=008
        """
        return f"{parent_ulpin}|LV={level_code}|Z={zmin:.2f}:{zmax:.2f}|V={volume_id}"

    def check_issuance_eligibility(self, volume: Dict[str, Any]) -> str:
        """
        Verifies if a volume is eligible for 3D ULPIN issuance per Principle 5.
        Returns issuance_basis ('GREEN_AUTO' or 'AMBER_HUMAN_APPROVED').
        Raises PermissionError if ineligible.
        """
        top_status = volume.get("topology_status")
        rev_status = volume.get("review_status", "NOT_REQUIRED")
        vol_id = volume.get("volume_id", "UNKNOWN")

        if top_status == "RED":
            raise PermissionError(
                f"ERR_RED_VOLUME_INELIGIBLE: Volume '{vol_id}' is flagged RED due to geometric conflict "
                f"or failure. A 3D ULPIN can NEVER be issued for RED volumes."
            )

        if top_status == "AMBER":
            if rev_status != "APPROVED":
                raise PermissionError(
                    f"ERR_AMBER_UNAPPROVED: Volume '{vol_id}' is AMBER and pending review (review_status='{rev_status}'). "
                    f"A 3D ULPIN can only be issued after formal human review approval."
                )
            return "AMBER_HUMAN_APPROVED"

        if top_status == "GREEN":
            return "GREEN_AUTO"

        raise PermissionError(f"ERR_UNKNOWN_STATUS: Volume '{vol_id}' has unrecognized topology status '{top_status}'.")

    def issue_ulpin3d(self, volume: Dict[str, Any], version: int = 1) -> Dict[str, Any]:
        """
        Issues an authoritative 3D ULPIN for an eligible volume.
        Enforces strict hard-gate criteria.
        """
        basis = self.check_issuance_eligibility(volume)
        parent_ulpin = volume["parent_ulpin"]
        level_code = volume["level_code"]
        zmin = float(volume["zmin"])
        zmax = float(volume["zmax"])
        vol_id = volume["volume_id"]

        ulpin3d_str = self.format_ulpin3d_string(
            parent_ulpin=parent_ulpin,
            level_code=level_code,
            zmin=zmin,
            zmax=zmax,
            volume_id=vol_id,
        )

        record = {
            "ulpin3d_string": ulpin3d_str,
            "volume_id": vol_id,
            "parent_ulpin": parent_ulpin,
            "level_code": level_code,
            "unit_code": volume.get("unit_code"),
            "zmin": zmin,
            "zmax": zmax,
            "issuance_basis": basis,
            "topology_status": volume["topology_status"],
            "review_status": volume.get("review_status"),
            "version": version,
            "data_origin": settings.DATA_ORIGIN,
            "issued_at": datetime.now(timezone.utc).isoformat(),
        }

        # Store in-memory registry
        self._in_memory_registry[ulpin3d_str] = record

        # If DB session active, persist using ORM (which triggers DB-level validation)
        if self.db:
            vol_row = self.db.query(Volume).filter_by(
                parent_ulpin=parent_ulpin, volume_id=vol_id, version=version
            ).first()

            if vol_row:
                ulpin_row = self.db.query(Ulpin3D).filter_by(volume_row_id=vol_row.id).first()
                if not ulpin_row:
                    ulpin_row = Ulpin3D(
                        ulpin3d_string=ulpin3d_str,
                        volume_row_id=vol_row.id,
                        issuance_basis=basis,
                        version=version,
                        data_origin=settings.DATA_ORIGIN,
                    )
                    self.db.add(ulpin_row)
                    self.db.commit()

        return record

    def issue_all_eligible(self, validated_volumes: List[Dict[str, Any]], version: int = 1) -> Dict[str, Any]:
        """
        Processes an entire building validation run and issues 3D ULPINs
        for all volumes that satisfy publication gate criteria.
        """
        issued = []
        blocked = []

        for v in validated_volumes:
            vol_id = v["volume_id"]
            try:
                rec = self.issue_ulpin3d(v, version=version)
                issued.append(rec)
            except PermissionError as e:
                blocked.append({
                    "volume_id": vol_id,
                    "unit_code": v.get("unit_code"),
                    "topology_status": v.get("topology_status"),
                    "review_status": v.get("review_status"),
                    "reason": str(e),
                })

        return {
            "total_volumes": len(validated_volumes),
            "issued_count": len(issued),
            "blocked_count": len(blocked),
            "issued": issued,
            "blocked": blocked,
            "version": version,
            "data_origin": settings.DATA_ORIGIN,
        }

    def get_by_ulpin3d(self, ulpin3d_string: str) -> Optional[Dict[str, Any]]:
        """Look up 3D ULPIN identity record by full string."""
        if ulpin3d_string in self._in_memory_registry:
            return self._in_memory_registry[ulpin3d_string]

        if self.db:
            row = self.db.query(Ulpin3D).filter_by(ulpin3d_string=ulpin3d_string).first()
            if row and row.volume:
                v = row.volume
                return {
                    "ulpin3d_string": row.ulpin3d_string,
                    "volume_id": v.volume_id,
                    "parent_ulpin": v.parent_ulpin,
                    "level_code": v.level_code,
                    "unit_code": v.unit_code,
                    "zmin": float(v.zmin),
                    "zmax": float(v.zmax),
                    "issuance_basis": row.issuance_basis,
                    "topology_status": v.topology_status,
                    "review_status": v.review_status,
                    "version": row.version,
                    "data_origin": row.data_origin,
                    "issued_at": row.issued_at.isoformat() if row.issued_at else None,
                }
        return None

    def get_by_parent_ulpin(self, parent_ulpin: str) -> List[Dict[str, Any]]:
        """Finds all issued 3D ULPINs for a parent 2D cadastral parcel."""
        return [
            rec for rec in self._in_memory_registry.values()
            if rec["parent_ulpin"] == parent_ulpin
        ]

    def get_by_volume_id(self, volume_id: str) -> Optional[Dict[str, Any]]:
        """Finds issued 3D ULPIN for a specific 3-digit volume ID."""
        for rec in self._in_memory_registry.values():
            if rec["volume_id"] == volume_id:
                return rec
        return None
