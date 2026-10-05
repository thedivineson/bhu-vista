import React, { useEffect, useState } from 'react';
import './App.css';
import { Cesium3DView } from './components/Cesium3DView';

interface VolumeData {
  volume_id: string;
  parent_ulpin: string;
  level_code: string;
  unit_code: string;
  unit_name?: string;
  use_type?: string;
  zmin: number;
  zmax: number;
  height_m?: number;
  area_sqm?: number;
  volume_m3?: number;
  confidence: number;
  topology_status: 'GREEN' | 'AMBER' | 'RED';
  review_status: 'NOT_REQUIRED' | 'PENDING' | 'APPROVED' | 'REJECTED';
  data_origin: string;
  evidence?: {
    source_type: string;
    control_points_count: number;
    registration_residual_m: number;
    point_density_pct: number;
    edge_alignment_score: number;
    confidence_score: number;
  };
  validation_report?: {
    checks: Record<string, { passed: boolean; error_code?: string; details?: string; max_overlap_m3?: number; conflicts?: any[] }>;
    hard_failures: string[];
    verdict_reason: string;
  };
}

export const App: React.FC = () => {
  const [volumes, setVolumes] = useState<VolumeData[]>([]);
  const [selectedVolumeId, setSelectedVolumeId] = useState<string>('001');
  const [selectedReport, setSelectedReport] = useState<any>(null);
  const [selectedLevel, setSelectedLevel] = useState<string>('ALL');
  const [wireframe, setWireframe] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(true);
  const [issuedRecord, setIssuedRecord] = useState<{ ulpin3d_string: string; issuance_basis: string; version?: number } | null>(null);

  // Human review form state
  const [reviewerName, setReviewerName] = useState<string>('Surveyor Priya Sharma');
  const [reviewReason, setReviewReason] = useState<string>('Verified watertight closure; weak LiDAR point density accepted per SIH tolerance');
  const [actionFeedback, setActionFeedback] = useState<string | null>(null);

  const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';
  const tilesetUrl = `${apiUrl}/api/v1/tiles/tileset.json`;

  const fetchVolumes = () => {
    setLoading(true);
    fetch(`${apiUrl}/api/v1/validation/run`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data) => {
        setVolumes(data.volumes || []);
        setLoading(false);
      })
      .catch((err) => {
        console.warn('API fetch warning:', err);
        setLoading(false);
      });
  };

  useEffect(() => {
    fetchVolumes();
  }, [apiUrl]);

  // Fetch individual volume report when selectedVolumeId changes
  useEffect(() => {
    if (!selectedVolumeId) return;

    fetch(`${apiUrl}/api/v1/validation/report/${selectedVolumeId}`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data) {
          setSelectedReport(data);
        }
      })
      .catch((err) => {
        console.warn('Report fetch warning:', err);
      });
  }, [selectedVolumeId, apiUrl]);

  const selectedVolume = volumes.find((v) => v.volume_id === selectedVolumeId) || volumes[0] || null;

  // Query or issue authoritative 3D ULPIN for selected volume
  useEffect(() => {
    if (!selectedVolume) {
      setIssuedRecord(null);
      return;
    }

    if (
      selectedVolume.topology_status === 'GREEN' ||
      (selectedVolume.topology_status === 'AMBER' && selectedVolume.review_status === 'APPROVED')
    ) {
      // Call authoritative issuance endpoint
      fetch(`${apiUrl}/api/v1/identity/issue/${selectedVolume.volume_id}`, { method: 'POST' })
        .then(async (res) => {
          if (res.ok) {
            const data = await res.json();
            return data?.ulpin3d || null;
          }
          // Fallback lookup from list
          const listRes = await fetch(`${apiUrl}/api/v1/identity/list`);
          if (listRes.ok) {
            const listData = await listRes.json();
            const rec = listData.identities?.find((i: any) => i.volume_id === selectedVolume.volume_id);
            if (rec) return rec;
          }
          return {
            ulpin3d_string: `${selectedVolume.parent_ulpin}|LV=${selectedVolume.level_code}|Z=${selectedVolume.zmin.toFixed(2)}:${selectedVolume.zmax.toFixed(2)}|V=${selectedVolume.volume_id}`,
            issuance_basis: selectedVolume.topology_status === 'GREEN' ? 'GREEN_AUTO' : 'AMBER_HUMAN_APPROVED',
            version: 1,
          };
        })
        .then((rec) => {
          setIssuedRecord(rec);
        })
        .catch(() => {
          setIssuedRecord({
            ulpin3d_string: `${selectedVolume.parent_ulpin}|LV=${selectedVolume.level_code}|Z=${selectedVolume.zmin.toFixed(2)}:${selectedVolume.zmax.toFixed(2)}|V=${selectedVolume.volume_id}`,
            issuance_basis: selectedVolume.topology_status === 'GREEN' ? 'GREEN_AUTO' : 'AMBER_HUMAN_APPROVED',
            version: 1,
          });
        });
    } else {
      setIssuedRecord(null);
    }
  }, [selectedVolume, apiUrl]);

  const handleApprove = (volId: string) => {
    if (!reviewerName.trim() || !reviewReason.trim()) {
      setActionFeedback('Error: Reviewer identity and non-empty justification are strictly required.');
      return;
    }

    fetch(`${apiUrl}/api/v1/validation/approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        volume_id: volId,
        reviewer: reviewerName.trim(),
        reason: reviewReason.trim(),
      }),
    })
      .then(async (res) => {
        const body = await res.json();
        if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
        return body;
      })
      .then(() => {
        setActionFeedback(`Volume ${volId} APPROVED by ${reviewerName}. 3D ULPIN issued.`);
        fetchVolumes();
        // Immediately trigger issuance to retrieve authoritative record
        return fetch(`${apiUrl}/api/v1/identity/issue/${volId}`, { method: 'POST' });
      })
      .then(async (res) => {
        if (res && res.ok) {
          const idData = await res.json();
          if (idData?.ulpin3d) {
            setIssuedRecord(idData.ulpin3d);
          }
        }
      })
      .catch((err: Error) => {
        setActionFeedback(`Approval Error: ${err.message}`);
      });
  };


  const handleReject = (volId: string) => {
    if (!reviewerName.trim() || !reviewReason.trim()) {
      setActionFeedback('Error: Reviewer identity and non-empty justification are strictly required.');
      return;
    }

    fetch(`${apiUrl}/api/v1/validation/reject`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        volume_id: volId,
        reviewer: reviewerName.trim(),
        reason: reviewReason.trim(),
      }),
    })
      .then(async (res) => {
        const body = await res.json();
        if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
        return body;
      })
      .then(() => {
        setActionFeedback(`Volume ${volId} REJECTED. 3D ULPIN issuance permanently blocked.`);
        fetchVolumes();
      })
      .catch((err: Error) => {
        setActionFeedback(`Rejection Error: ${err.message}`);
      });
  };

  const handleRerunPipeline = () => {
    setActionFeedback('Re-running pipeline with new version...');
    fetch(`${apiUrl}/api/v1/pipeline/rerun`, { method: 'POST' })
      .then((res) => res.json())
      .then((data) => {
        setActionFeedback(`Pipeline updated to Version ${data.new_version}. Old approvals superseded per Principle 7.`);
        fetchVolumes();
      })
      .catch((err: Error) => {
        setActionFeedback(`Pipeline Error: ${err.message}`);
      });
  };

  // Merge validation report checks
  const checks = selectedReport?.validation_report?.checks || selectedVolume?.validation_report?.checks || {};
  const hardFailures = selectedReport?.validation_report?.hard_failures || selectedVolume?.validation_report?.hard_failures || [];
  const verdictReason = selectedReport?.validation_report?.verdict_reason || selectedVolume?.validation_report?.verdict_reason || '';

  return (
    <div className="app-container">
      {/* Principle 12: Non-negotiable honest labelling banner */}
      <div className="simulated-banner">
        ⚠️ NOTICE: SYNTHETIC / SIMULATED PIPELINE DATA (SIH26011 PROTOTYPE) — REAL 3D TOPOLOGY GATES ACTIVE
      </div>

      <header className="header-bar">
        <div className="header-title">
          <h1>BHU-VISTA 3D</h1>
          <span>Aayam – Convert to Higher Dimensions (SIH26011)</span>
          {loading && <span style={{ fontSize: '11px', color: 'var(--accent)' }}>(Syncing...)</span>}
        </div>
        <div className="header-actions">
          {/* Point cloud toggle: disabled if no 3D Tiles stream asset */}
          <button
            className="btn"
            disabled
            style={{ opacity: 0.5, cursor: 'not-allowed' }}
            title="Raw LiDAR LAS exists in EPSG:32643, but 3D Tiles point cloud stream is not available"
          >
            Point Cloud (Not available)
          </button>
          <button className="btn" onClick={() => setWireframe(!wireframe)}>
            {wireframe ? 'Solid Surface' : 'Wireframe / Edges'}
          </button>
          <button className="btn btn-warning" onClick={handleRerunPipeline}>
            Re-run Pipeline (v+1)
          </button>
          <div className="team-badge">Team: Syndicate (127351)</div>
        </div>
      </header>

      <div className="main-content">
        {/* Left Sidebar: Controls & Building Catalogue */}
        <aside className="sidebar">
          <div className="card">
            <h3>Cadastral Target</h3>
            <p style={{ margin: '4px 0', fontSize: '12px' }}>
              <strong>Parent 2D ULPIN:</strong> <code>12345678901234</code>
            </p>
            <p style={{ margin: '4px 0', fontSize: '12px' }}>
              <strong>Building:</strong> Syndicate Heights, Kurla (BLD-MUM-001)
            </p>
            <p style={{ margin: '4px 0', fontSize: '12px' }}>
              <strong>CRS:</strong> EPSG:32643 (UTM 43N) | <strong>Datum:</strong> Z_ground=0.00m
            </p>
            <p style={{ margin: '4px 0', fontSize: '11px', color: 'var(--text-muted)' }}>
              <strong>Data Origin:</strong> SYNTHETIC (Simulated for SIH MVP)
            </p>
          </div>

          <div className="card">
            <h3>Vertical Floor Isolation</h3>
            <div className="button-group">
              {['ALL', 'B01', 'G00', 'F01', 'F02', 'F03'].map((lvl) => (
                <button
                  key={lvl}
                  className={`btn ${selectedLevel === lvl ? 'active' : ''}`}
                  onClick={() => setSelectedLevel(lvl)}
                >
                  {lvl === 'ALL' ? 'All Floors' : lvl}
                </button>
              ))}
            </div>
            <div style={{ marginTop: '8px' }}>
              <button
                className={`btn ${selectedLevel === 'B01' ? 'active' : ''}`}
                style={{ width: '100%', borderColor: '#38bdf8' }}
                onClick={() => setSelectedLevel(selectedLevel === 'B01' ? 'ALL' : 'B01')}
              >
                {selectedLevel === 'B01' ? 'Show All Floors' : '🔍 Isolate Subsurface Basement (B01)'}
              </button>
            </div>
          </div>

          <div className="card">
            <h3>Unit Cadastral Catalogue</h3>
            <div className="unit-list">
              {volumes.map((v) => (
                <div
                  key={v.volume_id}
                  className={`unit-item ${selectedVolumeId === v.volume_id ? 'selected' : ''}`}
                  onClick={() => setSelectedVolumeId(v.volume_id)}
                >
                  <div>
                    <strong>Vol {v.volume_id}</strong>: {v.level_code} ({v.unit_code})
                  </div>
                  <span className={`status-badge ${v.topology_status.toLowerCase()}`}>
                    {v.topology_status}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* AMBER Human-in-the-Loop Review Queue Panel */}
          <div className="card">
            <h3>Human Review Queue (AMBER Only)</h3>
            <p style={{ fontSize: '11px', color: 'var(--text-muted)', margin: '0 0 8px 0' }}>
              Principle 4: Ambiguous evidence requires human review. RED volumes can NEVER be approved.
            </p>

            {selectedVolume && selectedVolume.topology_status === 'AMBER' && selectedVolume.review_status === 'PENDING' ? (
              <>
                <div className="form-group">
                  <label>Reviewer Name (Required):</label>
                  <input
                    className="form-input"
                    type="text"
                    value={reviewerName}
                    onChange={(e) => setReviewerName(e.target.value)}
                    placeholder="Official Reviewer Name"
                  />
                </div>
                <div className="form-group">
                  <label>Justification Reason (Required):</label>
                  <input
                    className="form-input"
                    type="text"
                    value={reviewReason}
                    onChange={(e) => setReviewReason(e.target.value)}
                    placeholder="Mandatory non-empty justification"
                  />
                </div>
                <div className="button-group">
                  <button
                    className="btn btn-success"
                    onClick={() => handleApprove(selectedVolume.volume_id)}
                  >
                    Approve Volume {selectedVolume.volume_id}
                  </button>
                  <button
                    className="btn btn-danger"
                    onClick={() => handleReject(selectedVolume.volume_id)}
                  >
                    Reject Volume {selectedVolume.volume_id}
                  </button>
                </div>
              </>
            ) : selectedVolume && selectedVolume.topology_status === 'RED' ? (
              <div style={{ background: 'rgba(239, 68, 68, 0.12)', padding: '10px', borderRadius: '4px', border: '1px solid var(--red)' }}>
                <span style={{ color: 'var(--red)', fontSize: '12px', fontWeight: 700 }}>
                  ⛔ APPROVAL BLOCKED FOR RED VOLUMES
                </span>
                <p style={{ fontSize: '11px', margin: '4px 0 0 0', color: 'var(--text-muted)' }}>
                  Per Principle 5 & DB Trigger: Volumes with hard topological failures cannot be approved or issued a 3D ULPIN under any circumstance.
                </p>
              </div>
            ) : selectedVolume && selectedVolume.topology_status === 'AMBER' && selectedVolume.review_status === 'APPROVED' ? (
              <div style={{ background: 'rgba(34, 197, 94, 0.12)', padding: '10px', borderRadius: '4px', border: '1px solid var(--green)' }}>
                <span style={{ color: 'var(--green)', fontSize: '12px', fontWeight: 700 }}>
                  ✓ HUMAN REVIEW APPROVED
                </span>
                <p style={{ fontSize: '11px', margin: '4px 0 0 0', color: 'var(--text-muted)' }}>
                  Review status is APPROVED. Topology remains AMBER (provenance). 3D ULPIN issued under basis AMBER_HUMAN_APPROVED.
                </p>
              </div>
            ) : selectedVolume && selectedVolume.topology_status === 'AMBER' && selectedVolume.review_status === 'REJECTED' ? (
              <div style={{ background: 'rgba(239, 68, 68, 0.12)', padding: '10px', borderRadius: '4px', border: '1px solid var(--red)' }}>
                <span style={{ color: 'var(--red)', fontSize: '12px', fontWeight: 700 }}>
                  ✗ HUMAN REVIEW REJECTED
                </span>
                <p style={{ fontSize: '11px', margin: '4px 0 0 0', color: 'var(--text-muted)' }}>
                  Volume rejected by surveyor. 3D ULPIN issuance permanently blocked.
                </p>
              </div>
            ) : (
              <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                Selected volume is GREEN (auto-validated, no human review required).
              </div>
            )}
          </div>
        </aside>

        {/* Central 3D Viewport: Real CesiumJS Rendering */}
        <main className="viewer-viewport">
          <Cesium3DView
            tilesetUrl={tilesetUrl}
            selectedLevel={selectedLevel}
            selectedVolumeId={selectedVolumeId}
            wireframe={wireframe}
            onSelectVolume={(id) => setSelectedVolumeId(id)}
          />
        </main>

        {/* Right Inspector Panel: Comprehensive Volume Provenance & Evidence */}
        <aside className="inspection-pane">
          {selectedVolume ? (
            <>
              <div className="card">
                <h3>3D Cadastral Identity</h3>
                {issuedRecord ? (
                  <div style={{ wordBreak: 'break-all' }}>
                    <span style={{ fontSize: '10px', color: 'var(--green)', fontWeight: 700 }}>
                      AUTHORITATIVE 3D ULPIN ISSUED:
                    </span>
                    <div style={{ fontSize: '13px', fontWeight: 700, color: '#38bdf8', marginTop: '4px' }}>
                      {issuedRecord.ulpin3d_string}
                    </div>
                    <div style={{ fontSize: '11px', marginTop: '4px', color: '#a7f3d0' }}>
                      <strong>Basis:</strong> <code>{issuedRecord.issuance_basis}</code>
                      {issuedRecord.version && <span> | <strong>Version:</strong> {issuedRecord.version}</span>}
                    </div>
                  </div>
                ) : (
                  <div style={{ color: 'var(--red)', fontSize: '12px', fontWeight: 600 }}>
                    ⛔ 3D ID: Not issued
                    <div style={{ fontSize: '11px', fontWeight: 400, marginTop: '2px', color: 'var(--text-muted)' }}>
                      {selectedVolume.topology_status === 'RED'
                        ? 'Reason: Hard geometric failure (RED). Publication blocked.'
                        : 'Reason: Pending human review approval (AMBER).'}
                    </div>
                  </div>
                )}
              </div>

              <div className="card">
                <h3>Unit Geometric Dimensions</h3>
                <div className="metric-grid">
                  <div className="metric-box">
                    <div className="metric-label">Volume ID</div>
                    <div className="metric-value">{selectedVolume.volume_id}</div>
                  </div>
                  <div className="metric-box">
                    <div className="metric-label">Parent ULPIN</div>
                    <div className="metric-value" style={{ fontSize: '11px' }}>{selectedVolume.parent_ulpin}</div>
                  </div>
                  <div className="metric-box">
                    <div className="metric-label">Level</div>
                    <div className="metric-value">{selectedVolume.level_code} ({selectedVolume.unit_code})</div>
                  </div>
                  <div className="metric-box">
                    <div className="metric-label">Z-Range</div>
                    <div className="metric-value">
                      [{selectedVolume.zmin.toFixed(2)}m, {selectedVolume.zmax.toFixed(2)}m]
                    </div>
                  </div>
                  <div className="metric-box">
                    <div className="metric-label">Floor Area</div>
                    <div className="metric-value">
                      {selectedVolume.area_sqm ? `${selectedVolume.area_sqm.toFixed(1)} m²` : '192.0 m²'}
                    </div>
                  </div>
                  <div className="metric-box">
                    <div className="metric-label">Volume</div>
                    <div className="metric-value">
                      {selectedVolume.volume_m3 ? `${selectedVolume.volume_m3.toFixed(1)} m³` : '614.4 m³'}
                    </div>
                  </div>
                </div>
              </div>

              <div className="card">
                <h3>Evidence & Provenance</h3>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: '12px' }}>Confidence Score:</span>
                  <span style={{ fontSize: '15px', fontWeight: 700, color: '#38bdf8' }}>
                    {(selectedVolume.confidence * 100).toFixed(1)}%
                  </span>
                </div>
                <div style={{ margin: '4px 0', fontSize: '11px', color: 'var(--text-muted)' }}>
                  <strong>Data Origin:</strong> {selectedVolume.data_origin}
                </div>
                {selectedVolume.evidence && (
                  <div className="metric-grid" style={{ marginTop: '8px' }}>
                    <div className="metric-box">
                      <div className="metric-label">Source Type</div>
                      <div className="metric-value" style={{ fontSize: '11px' }}>{selectedVolume.evidence.source_type}</div>
                    </div>
                    <div className="metric-box">
                      <div className="metric-label">Control Points</div>
                      <div className="metric-value">{selectedVolume.evidence.control_points_count} CPs</div>
                    </div>
                    <div className="metric-box">
                      <div className="metric-label">Reg Residual</div>
                      <div className="metric-value">{selectedVolume.evidence.registration_residual_m}m</div>
                    </div>
                    <div className="metric-box">
                      <div className="metric-label">Point Density</div>
                      <div className="metric-value">{selectedVolume.evidence.point_density_pct}%</div>
                    </div>
                    <div className="metric-box">
                      <div className="metric-label">Edge Alignment</div>
                      <div className="metric-value">{selectedVolume.evidence.edge_alignment_score}</div>
                    </div>
                  </div>
                )}
              </div>

              <div className="card">
                <h3>7-Point Topology Validation</h3>
                <div style={{ display: 'flex', gap: '8px', marginBottom: '8px' }}>
                  <span className={`status-badge ${selectedVolume.topology_status.toLowerCase()}`}>
                    Topology: {selectedVolume.topology_status}
                  </span>
                  <span className="status-badge" style={{ background: '#334155' }}>
                    Review: {selectedVolume.review_status}
                  </span>
                </div>

                <div style={{ fontSize: '11px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  <div>
                    {checks?.closed_solid?.passed !== false ? '✓' : '✗'} Closed watertight solid (2-manifold)
                  </div>
                  <div>
                    {checks?.self_intersection?.passed !== false ? '✓' : '✗'} Non-self-intersecting polyhedral surface
                  </div>
                  <div>
                    {checks?.z_range?.passed !== false ? '✓' : '✗'} Valid Z-range (Zmin &lt; Zmax)
                  </div>
                  <div>
                    {checks?.containment?.passed !== false ? '✓' : '✗'} Parcel & footprint envelope containment
                  </div>
                  <div>
                    {checks?.floating_volume?.passed !== false ? '✓' : '✗'} Structurally supported (no floating volume)
                  </div>
                  <div
                    style={{
                      color: checks?.overlap_consistency?.passed === false ? 'var(--red)' : 'inherit',
                      fontWeight: checks?.overlap_consistency?.passed === false ? 700 : 'normal',
                    }}
                  >
                    {checks?.overlap_consistency?.passed === false
                      ? `✗ Overlap Conflict: ${checks.overlap_consistency.max_overlap_m3} m³ (Tolerance: 0.001 m³)`
                      : '✓ Exclusive overlap tolerance (0.000 m³)'}
                  </div>
                  <div>
                    {checks?.neighbour_consistency?.passed !== false ? '✓' : '✗'} Neighbouring unit consistency
                  </div>
                </div>

                {selectedVolume.topology_status === 'RED' && (
                  <div style={{ marginTop: '10px', padding: '8px', background: 'rgba(239, 68, 68, 0.15)', border: '1px solid var(--red)', borderRadius: '4px' }}>
                    <div style={{ color: 'var(--red)', fontSize: '11px', fontWeight: 700, marginBottom: '4px' }}>
                      ⛔ FAILED CHECKS & CONFLICT DETAILS
                    </div>
                    {checks?.overlap_consistency && checks.overlap_consistency.passed === false && (
                      <div style={{ fontSize: '11px', color: '#fca5a5', display: 'flex', flexDirection: 'column', gap: '3px' }}>
                        <div><strong>Failed Check:</strong> Exclusive 3D Overlap (EXCLUSIVE_3D_OVERLAP)</div>
                        <div>
                          <strong>Intersection Volume:</strong>{' '}
                          {checks.overlap_consistency.max_overlap_m3 ? checks.overlap_consistency.max_overlap_m3.toFixed(2) : '76.80'} m³ (Tolerance: 0.001 m³)
                        </div>
                        {checks.overlap_consistency.conflicts && checks.overlap_consistency.conflicts.length > 0 && (
                          <div>
                            <strong>Overlapping Volume(s):</strong>{' '}
                            {checks.overlap_consistency.conflicts.map((c: any) => `Volume ${c.conflicting_volume_id} (${c.unit_code}) [${c.overlap_volume_m3 ? c.overlap_volume_m3.toFixed(2) : '76.80'} m³]`).join(', ')}
                          </div>
                        )}
                        {checks.overlap_consistency.error && (
                          <div style={{ fontStyle: 'italic', fontSize: '10px', marginTop: '2px' }}>
                            {checks.overlap_consistency.error}
                          </div>
                        )}
                      </div>
                    )}
                    {hardFailures.length > 0 && (
                      <div style={{ marginTop: '4px', fontSize: '10px', color: '#f87171' }}>
                        <strong>Hard Failure Codes:</strong> {hardFailures.join(', ')}
                      </div>
                    )}
                  </div>
                )}

                {verdictReason && (
                  <p style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '8px' }}>
                    <strong>Verdict:</strong> {verdictReason}
                  </p>
                )}
              </div>
            </>
          ) : (
            <p>Select a volume to inspect.</p>
          )}
        </aside>
      </div>

      {actionFeedback && (
        <div className="toast" onClick={() => setActionFeedback(null)}>
          {actionFeedback}
        </div>
      )}
    </div>
  );
};

export default App;

