/**
 * CopyProjectVersionForm — port of the 'copy' mode in ProjectversionDialogComponent.
 *
 * Props:
 *   projectName    string  — parent project name
 *   projectVersion object  — the version being copied (source)
 *   onClose(reload) function
 */
import React, { useState, useEffect } from 'react';
import { copyProjectVersion } from '../../api/projectversions';

const DEPENDENCY_POLICIES = ['strict', 'distribution', 'any'];

async function fetchBaseMirrors() {
  const res = await fetch('/api/mirrors?page_size=200&basemirror=true', { credentials: 'same-origin' });
  if (!res.ok) return [];
  const data = await res.json();
  return (data.results ?? []).map(m => ({
    label: `${m.name}/${m.version}`,
    architectures: m.architectures ?? [],
  }));
}

async function fetchBaseProjects() {
  const res = await fetch('/api2/projectversions?page_size=200', { credentials: 'same-origin' });
  if (!res.ok) return [];
  const data = await res.json();
  return (data.results ?? []).map(pv => ({
    label: `${pv.project_name}/${pv.name}`,
    architectures: pv.architectures ?? [],
    basemirror: pv.basemirror ?? '',
  }));
}

export default function CopyProjectVersionForm({ projectName, projectVersion: pv, onClose }) {
  // ── form state ─────────────────────────────────────────────────────────────
  const [version,     setVersion]     = useState(`${pv.name}-copy`);
  const [description, setDescription] = useState(pv.description ?? '');
  const [basetype,    setBasetype]    = useState('mirror');   // 'mirror' | 'project'
  const [basemirror,  setBasemirror]  = useState(pv.basemirror ?? '');
  const [baseproject, setBaseproject] = useState('');
  const [selArchs,    setSelArchs]    = useState(pv.architectures ?? []);
  const [depPolicy,   setDepPolicy]   = useState(pv.dependency_policy ?? 'strict');
  const [ciBuilds,    setCiBuilds]    = useState(pv.ci_builds_enabled ?? false);
  const [buildLatest, setBuildLatest] = useState(false);

  // retention
  const [retOkEnabled,   setRetOkEnabled]   = useState((pv.retention_successful_builds ?? 0) > 0);
  const [retFailEnabled, setRetFailEnabled] = useState((pv.retention_failed_builds ?? 0) > 0);
  const [retOk,   setRetOk]   = useState(pv.retention_successful_builds ?? 0);
  const [retFail, setRetFail] = useState(pv.retention_failed_builds ?? 0);

  // data
  const [basemirrors,   setBasemirrors]   = useState([]);
  const [baseprojects,  setBaseprojects]  = useState([]);
  const [availArchs,    setAvailArchs]    = useState([]);

  const [busy,  setBusy]  = useState(false);
  const [error, setError] = useState('');

  // ── load base mirrors + base projects ──────────────────────────────────────
  useEffect(() => {
    fetchBaseMirrors().then(ms => {
      setBasemirrors(ms);
      // pre-select architectures from the source version's basemirror
      const found = ms.find(m => m.label === (pv.basemirror ?? ''));
      if (found) setAvailArchs(found.architectures);
    });
    fetchBaseProjects().then(setBaseprojects);
  }, []);

  // ── update available archs when basemirror/baseproject changes ─────────────
  useEffect(() => {
    if (basetype === 'mirror') {
      const found = basemirrors.find(m => m.label === basemirror);
      setAvailArchs(found ? found.architectures : []);
    } else {
      const found = baseprojects.find(p => p.label === baseproject);
      setAvailArchs(found ? found.architectures : []);
    }
    setSelArchs([]);
  }, [basemirror, baseproject, basetype]);

  function toggleArch(arch) {
    setSelArchs(prev =>
      prev.includes(arch) ? prev.filter(a => a !== arch) : [...prev, arch]
    );
  }

  // ── validation ─────────────────────────────────────────────────────────────
  const versionValid = /^[a-zA-Z0-9][a-zA-Z0-9._-]*$/.test(version) && version.length >= 2;
  const baseOk       = basetype === 'mirror' ? !!basemirror : !!baseproject;
  const canSave      = versionValid && baseOk && selArchs.length > 0;

  // ── submit ─────────────────────────────────────────────────────────────────
  async function save() {
    setBusy(true); setError('');
    try {
      await copyProjectVersion(pv.project_name, pv.name, {
        name: version.trim(),
        description: description.trim(),
        basemirror:  basetype === 'mirror'  ? basemirror  : undefined,
        baseproject: basetype === 'project' ? baseproject : undefined,
        architectures: selArchs,
        dependency_policy: depPolicy,
        cibuilds: ciBuilds,
        buildlatest: buildLatest,
        retention_successful_builds: retOkEnabled  ? retOk   : 0,
        retention_failed_builds:     retFailEnabled ? retFail : 0,
      });
      onClose(true);
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  // ── render ─────────────────────────────────────────────────────────────────
  return (
    <div className="modal fade show d-block" tabIndex="-1"
         style={{ backgroundColor: 'rgba(0,0,0,.4)' }}>
      <div className="modal-dialog modal-dialog-centered modal-lg">
        <div className="modal-content">

          <div className="modal-header">
            <h5 className="modal-title">Copy Project Version {pv.name}</h5>
            <button className="btn-close" onClick={() => onClose(false)} disabled={busy} />
          </div>

          <div className="modal-body">
            {error && <div className="alert alert-danger py-2">{error}</div>}

            {/* New version name */}
            <div className="mb-3">
              <label className="form-label fw-semibold">New Version Name</label>
              <input className="form-control" value={version} autoFocus
                     onChange={e => setVersion(e.target.value)} />
              {version.length > 0 && !versionValid && (
                <div className="form-text text-danger">
                  Must be ≥2 chars, letters/digits/dots/hyphens/underscores only.
                </div>
              )}
            </div>

            {/* Build latest */}
            <div className="mb-3 form-check">
              <input className="form-check-input" type="checkbox" id="buildlatest"
                     checked={buildLatest} onChange={e => setBuildLatest(e.target.checked)} />
              <label className="form-check-label" htmlFor="buildlatest">
                Build last releases from {pv.name}
              </label>
            </div>

            {/* Description */}
            <div className="mb-3">
              <label className="form-label fw-semibold">Description</label>
              <input className="form-control" value={description} maxLength={255}
                     onChange={e => setDescription(e.target.value)} />
            </div>

            {/* Base Mirror / Project toggle */}
            <div className="mb-2">
              <label className="form-label fw-semibold">Base Mirror / Project</label>
              <div className="text-muted small mb-2">
                Note: only dependencies with matching policy will be copied
              </div>
              <div className="d-flex gap-3 mb-2">
                <div className="form-check">
                  <input className="form-check-input" type="radio" id="bt-mirror"
                         checked={basetype === 'mirror'} onChange={() => setBasetype('mirror')} />
                  <label className="form-check-label" htmlFor="bt-mirror">Mirror</label>
                </div>
                <div className="form-check">
                  <input className="form-check-input" type="radio" id="bt-project"
                         checked={basetype === 'project'} onChange={() => setBasetype('project')} />
                  <label className="form-check-label" htmlFor="bt-project">Project</label>
                </div>
              </div>

              {basetype === 'mirror' && (
                <select className="form-select" value={basemirror}
                        onChange={e => setBasemirror(e.target.value)}>
                  <option value="">— select base mirror —</option>
                  {basemirrors.map(m => (
                    <option key={m.label} value={m.label}>{m.label}</option>
                  ))}
                </select>
              )}

              {basetype === 'project' && (
                <select className="form-select" value={baseproject}
                        onChange={e => setBaseproject(e.target.value)}>
                  <option value="">— select base project —</option>
                  {baseprojects.map(p => (
                    <option key={p.label} value={p.label}>
                      {p.label} ({p.architectures.join(', ')}) — {p.basemirror}
                    </option>
                  ))}
                </select>
              )}
            </div>

            {/* Architectures */}
            <div className="mb-3">
              <label className="form-label fw-semibold">Architectures</label>
              {availArchs.length === 0
                ? <div className="text-muted small">Please select a Base Mirror / Project above</div>
                : (
                  <div className="d-flex flex-wrap gap-3">
                    {availArchs.map(arch => (
                      <div className="form-check" key={arch}>
                        <input className="form-check-input" type="checkbox"
                               id={`arch-${arch}`}
                               checked={selArchs.includes(arch)}
                               onChange={() => toggleArch(arch)} />
                        <label className="form-check-label" htmlFor={`arch-${arch}`}>{arch}</label>
                      </div>
                    ))}
                  </div>
                )
              }
            </div>

            {/* Dependency policy */}
            <div className="mb-3">
              <label className="form-label fw-semibold">Dependency Policy</label>
              <select className="form-select" value={depPolicy}
                      onChange={e => setDepPolicy(e.target.value)}>
                {DEPENDENCY_POLICIES.map(p => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
            </div>

            {/* CI Builds */}
            <div className="mb-3 form-check">
              <input className="form-check-input" type="checkbox" id="cibuilds"
                     checked={ciBuilds} onChange={e => setCiBuilds(e.target.checked)} />
              <label className="form-check-label" htmlFor="cibuilds">Enable CI Builds</label>
            </div>

            {/* Retention — successful */}
            <div className="mb-2 d-flex align-items-center gap-3">
              <div className="form-check mb-0">
                <input className="form-check-input" type="checkbox" id="retOkEnabled"
                       checked={retOkEnabled}
                       onChange={e => { setRetOkEnabled(e.target.checked); if (!e.target.checked) setRetOk(0); }} />
                <label className="form-check-label" htmlFor="retOkEnabled">
                  Retain successful builds
                </label>
              </div>
              {retOkEnabled && (
                <input type="number" className="form-control form-control-sm" style={{ width: 90 }}
                       min={1} value={retOk} onChange={e => setRetOk(Number(e.target.value))} />
              )}
            </div>

            {/* Retention — failed */}
            <div className="mb-3 d-flex align-items-center gap-3">
              <div className="form-check mb-0">
                <input className="form-check-input" type="checkbox" id="retFailEnabled"
                       checked={retFailEnabled}
                       onChange={e => { setRetFailEnabled(e.target.checked); if (!e.target.checked) setRetFail(0); }} />
                <label className="form-check-label" htmlFor="retFailEnabled">
                  Retain failed builds
                </label>
              </div>
              {retFailEnabled && (
                <input type="number" className="form-control form-control-sm" style={{ width: 90 }}
                       min={1} value={retFail} onChange={e => setRetFail(Number(e.target.value))} />
              )}
            </div>
          </div>

          <div className="modal-footer">
            <button className="btn btn-secondary" onClick={() => onClose(false)} disabled={busy}>
              Cancel
            </button>
            <button className="btn btn-primary" onClick={save} disabled={busy || !canSave}>
              {busy && <span className="spinner-border spinner-border-sm me-2" />}
              Copy
            </button>
          </div>

        </div>
      </div>
    </div>
  );
}
