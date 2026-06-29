/**
 * ProjectVersionForm — port of ProjectversionDialogComponent / projectversion-form.html.
 * Used for Create and Edit modes.
 *
 * Props:
 *   projectName     string          — parent project name
 *   projectVersion  object|null     — if set → edit mode
 *   onClose(reload) function
 */
import React, { useState, useEffect } from 'react';
import { createProjectVersion, editProjectVersion } from '../../api/projectversions';
import { rules, fieldClass, fieldError } from '../../lib/validate';
import { apiUrl } from '../../lib/base';

const DEPENDENCY_POLICIES = ['strict', 'distribution', 'any'];

async function fetchBaseMirrors(q = '') {
  const params = new URLSearchParams({ page_size: 200 });
  if (q) params.set('q', q);
  params.set('basemirror', 'true');
  const res = await fetch(apiUrl(`/api/mirrors?${params}`), { credentials: 'same-origin' });
  if (!res.ok) return [];
  const data = await res.json();
  // results have: name, version, architectures
  return (data.results ?? []).map(m => ({
    label: `${m.name}/${m.version}`,
    architectures: m.architectures ?? [],
  }));
}

async function fetchMirrorArchs(mirrorStr) {
  if (!mirrorStr?.includes('/')) return [];
  const [mName, mVer] = mirrorStr.split('/');
  const res = await fetch(apiUrl(`/api/mirrors/${mName}/${mVer}`), { credentials: 'same-origin' });
  if (!res.ok) return [];
  const data = await res.json();
  return data.architectures ?? [];
}

export default function ProjectVersionForm({ projectName, projectVersion, onClose }) {
  const isEdit = !!projectVersion;

  // ── form state ────────────────────────────────────────────────────────────
  const [version,     setVersion]     = useState(projectVersion?.name ?? '');
  const [description, setDescription] = useState(projectVersion?.description ?? '');
  const [basemirror,  setBasemirror]  = useState(projectVersion?.basemirror ?? '');
  const [depPolicy,   setDepPolicy]   = useState(projectVersion?.dependency_policy ?? 'strict');
  const [ciBuilds,    setCiBuilds]    = useState(projectVersion?.ci_builds_enabled ?? false);
  const [selArchs,    setSelArchs]    = useState(projectVersion?.architectures ?? []);

  // retention
  const [retOkEnabled,  setRetOkEnabled]  = useState((projectVersion?.retention_successful_builds ?? 0) > 0);
  const [retFailEnabled, setRetFailEnabled] = useState((projectVersion?.retention_failed_builds ?? 0) > 0);
  const [retOk,   setRetOk]   = useState(projectVersion?.retention_successful_builds ?? 0);
  const [retFail, setRetFail] = useState(projectVersion?.retention_failed_builds ?? 0);

  // data
  const [basemirrors, setBasemirrors] = useState([]);
  const [availArchs,  setAvailArchs]  = useState([]);

  const [busy,  setBusy]  = useState(false);
  const [error, setError] = useState('');

  // ── load base mirrors ─────────────────────────────────────────────────────
  useEffect(() => {
    fetchBaseMirrors().then(setBasemirrors);
  }, []);

  // ── load architectures for selected basemirror ────────────────────────────
  useEffect(() => {
    if (!basemirror) { setAvailArchs([]); return; }
    // try to find from already-loaded list first
    const found = basemirrors.find(m => m.label === basemirror);
    if (found) { setAvailArchs(found.architectures); return; }
    fetchMirrorArchs(basemirror).then(setAvailArchs);
  }, [basemirror, basemirrors]);

  function toggleArch(arch) {
    setSelArchs(prev =>
      prev.includes(arch) ? prev.filter(a => a !== arch) : [...prev, arch]
    );
  }

  // ── validation ────────────────────────────────────────────────────────────────
  const [touched, setTouched] = useState({});
  const touch = f => setTouched(t => ({ ...t, [f]: true }));

  const errors  = { version: isEdit ? '' : rules.version(version) };
  const canSave = isEdit
    ? true
    : (!errors.version && !!basemirror && selArchs.length > 0);

  // ── submit ────────────────────────────────────────────────────────────────
  async function save() {
    setBusy(true); setError('');
    try {
      if (isEdit) {
        await editProjectVersion(projectVersion.project_name, projectVersion.name, {
          description,
          dependency_policy: depPolicy,
          cibuilds: ciBuilds,
          retention_successful_builds: retOkEnabled ? retOk : 0,
          retention_failed_builds: retFailEnabled ? retFail : 0,
        });
      } else {
        await createProjectVersion(projectName, {
          name: version.trim(),
          description: description.trim(),
          basemirror: basemirror || undefined,
          architectures: selArchs,
          dependency_policy: depPolicy,
          cibuilds: ciBuilds,
          retention_successful_builds: retOkEnabled ? retOk : 0,
          retention_failed_builds: retFailEnabled ? retFail : 0,
        });
      }
      onClose(true);
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  // ── render ────────────────────────────────────────────────────────────────
  return (
    <div className="modal fade show d-block" tabIndex="-1"
         style={{ backgroundColor: 'rgba(0,0,0,.4)' }}>
      <div className="modal-dialog modal-dialog-centered modal-lg">
        <div className="modal-content">

          <div className="modal-header">
            <h5 className="modal-title">
              {isEdit ? 'Edit Project Version' : 'Create Project Version'}
            </h5>
            <button className="btn-close" onClick={() => onClose(false)} disabled={busy} />
          </div>

          <div className="modal-body">
            {error && <div className="alert alert-danger py-2">{error}</div>}

            {/* Version name */}
            {!isEdit && (
              <div className="mb-3">
                <label className="form-label fw-semibold">Version</label>
                <input className="form-control" value={version} autoFocus
                       onChange={e => setVersion(e.target.value)}
                       onBlur={() => touch('version')} />
                {touched.version && errors.version && <div className="invalid-feedback">{errors.version}</div>}
              </div>
            )}

            {/* Description */}
            <div className="mb-3">
              <label className="form-label fw-semibold">Description</label>
              <input className="form-control" value={description} maxLength={255}
                     onChange={e => setDescription(e.target.value)} />
            </div>

            {/* Base mirror (create only) */}
            {!isEdit && (
              <div className="mb-3">
                <label className="form-label fw-semibold">Base Mirror</label>
                <select className="form-select" value={basemirror}
                        onChange={e => { setBasemirror(e.target.value); setSelArchs([]); }}>
                  <option value="">— select —</option>
                  {basemirrors.map(m => (
                    <option key={m.label} value={m.label}>{m.label}</option>
                  ))}
                </select>
              </div>
            )}

            {/* Architectures (create only) */}
            {!isEdit && availArchs.length > 0 && (
              <div className="mb-3">
                <label className="form-label fw-semibold">Architectures</label>
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
              </div>
            )}

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
              <input className="form-check-input" type="checkbox"
                     id="cibuilds" checked={ciBuilds}
                     onChange={e => setCiBuilds(e.target.checked)} />
              <label className="form-check-label" htmlFor="cibuilds">Enable CI Builds</label>
            </div>

            {/* Retention — successful */}
            <div className="mb-2 d-flex align-items-center gap-3">
              <div className="form-check mb-0">
                <input className="form-check-input" type="checkbox"
                       id="retOkEnabled" checked={retOkEnabled}
                       onChange={e => { setRetOkEnabled(e.target.checked); if (!e.target.checked) setRetOk(0); }} />
                <label className="form-check-label" htmlFor="retOkEnabled">
                  Retain successful builds
                </label>
              </div>
              {retOkEnabled && (
                <input type="number" className="form-control form-control-sm" style={{ width: 90 }}
                       min={1} value={retOk}
                       onChange={e => setRetOk(Number(e.target.value))} />
              )}
            </div>

            {/* Retention — failed */}
            <div className="mb-3 d-flex align-items-center gap-3">
              <div className="form-check mb-0">
                <input className="form-check-input" type="checkbox"
                       id="retFailEnabled" checked={retFailEnabled}
                       onChange={e => { setRetFailEnabled(e.target.checked); if (!e.target.checked) setRetFail(0); }} />
                <label className="form-check-label" htmlFor="retFailEnabled">
                  Retain failed builds
                </label>
              </div>
              {retFailEnabled && (
                <input type="number" className="form-control form-control-sm" style={{ width: 90 }}
                       min={1} value={retFail}
                       onChange={e => setRetFail(Number(e.target.value))} />
              )}
            </div>
          </div>

          <div className="modal-footer">
            <button className="btn btn-secondary" onClick={() => onClose(false)} disabled={busy}>
              Cancel
            </button>
            <button className="btn btn-primary" onClick={save} disabled={busy || !canSave}>
              {busy && <span className="spinner-border spinner-border-sm me-2" />}
              Ok
            </button>
          </div>

        </div>
      </div>
    </div>
  );
}
