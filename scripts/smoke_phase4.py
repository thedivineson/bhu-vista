"""
Phase 4 Smoke Test — Validation Engine & Review Service.
Verifies RED conflict, AMBER case, and GREEN volumes emerge from real code.
"""
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from validation.service import ValidationReviewService

svc = ValidationReviewService()
validated = svc.run_full_validation()

print(f"\n=== Phase 4 Smoke Test: {len(validated)} volumes validated ===\n")
for v in validated:
    vid = v["volume_id"]
    lc = v["level_code"]
    uc = v["unit_code"]
    ts = v["topology_status"]
    rs = v["review_status"]
    conf = v["confidence"]
    hf = v["validation_report"]["hard_failures"]
    print(f"  Vol {vid} ({lc} {uc}): status={ts}, review={rs}, confidence={conf:.4f}, hard_failures={hf}")

# Verify deliberate RED conflict (volumes 006 and 007)
red_vols = [v for v in validated if v["topology_status"] == "RED"]
red_ids = sorted([v["volume_id"] for v in red_vols])
assert "006" in red_ids, f"Volume 006 should be RED, got: {red_ids}"
assert "007" in red_ids, f"Volume 007 should be RED, got: {red_ids}"

# Verify overlap details
for rv in red_vols:
    if rv["volume_id"] in ("006", "007"):
        overlap_check = rv["validation_report"]["checks"]["overlap_consistency"]
        assert not overlap_check["passed"], f"Volume {rv['volume_id']} overlap check should fail"
        assert len(overlap_check["conflicts"]) > 0, f"Volume {rv['volume_id']} should have conflict entries"
        overlap_m3 = overlap_check["conflicts"][0]["overlap_volume_m3"]
        print(f"\n  >> Vol {rv['volume_id']} overlap: {overlap_m3} m3")
        assert overlap_m3 > 70.0, f"Expected overlap > 70 m3, got {overlap_m3}"

# Verify deliberate AMBER case (volume 009)
amber_vols = [v for v in validated if v["topology_status"] == "AMBER"]
assert len(amber_vols) == 1, f"Expected exactly 1 AMBER volume, got {len(amber_vols)}"
amber_vol = amber_vols[0]
assert amber_vol["volume_id"] == "009", f"AMBER volume should be 009, got {amber_vol['volume_id']}"
assert amber_vol["review_status"] == "PENDING", f"AMBER review_status should be PENDING"
assert 0.50 <= amber_vol["confidence"] < 0.80, f"AMBER confidence {amber_vol['confidence']} not in [0.50, 0.80)"

# Verify GREEN volumes
green_vols = [v for v in validated if v["topology_status"] == "GREEN"]
green_ids = sorted([v["volume_id"] for v in green_vols])
print(f"\n  GREEN volumes: {green_ids}")
assert len(green_vols) >= 6, f"Expected >= 6 GREEN volumes, got {len(green_vols)}"

# Verify review queue
queue = svc.get_review_queue()
print(f"\n  Review queue: {len(queue)} items")
assert len(queue) == 1
assert queue[0]["volume_id"] == "009"

# Test approve AMBER
result = svc.approve_volume("009", "Dr. Priya Sharma", "Manual verification confirms valid geometry; low evidence accepted.")
assert result["review_status"] == "APPROVED"
print(f"  >> AMBER vol 009 approved successfully")

# Test reject RED (must fail)
try:
    svc.approve_volume("006", "Reviewer", "Attempting approval")
    assert False, "Should have raised ValueError for RED volume"
except ValueError as e:
    assert "RED" in str(e)
    print(f"  >> RED vol 006 correctly rejected: {str(e)[:60]}...")

print("\n=== ALL SMOKE TESTS PASSED ===\n")
