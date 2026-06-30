/**
 * ProjectVersionDetailPage — port of projectversion-info / projectversion-build-list /
 * projectversion-repo-list / projectversion-aptsources / projectversion-dependents.
 *
 * Route: /project/:name/:version/*
 * Tabs:  Info | Builds | Source Repositories | APT Sources | Dependents
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate, NavLink, Routes, Route, Navigate } from 'react-router-dom';
import BuildTable from '../build/BuildTable';
import ConfirmModal from '../build/ConfirmModal';
import ContextMenu from '../common/ContextMenu';
import Pagination from '../common/Pagination';
import ProjectVersionForm from '../project/ProjectVersionForm';
import CopyProjectVersionForm from '../project/CopyProjectVersionForm';
import { rules, fieldClass, fieldError } from '../../lib/validate';
import { wsUrl, apiUrl } from '../../lib/base';
import {
  fetchProjectVersion,
  deleteProjectVersion,
  lockProjectVersion,
  fetchDependencies,
  addDependency,
  removeDependency,
  fetchDependents,
  fetchRepositories,
  addRepository,
  editRepository,
  removeRepository,
  buildRepository,
  triggerBuild,
  recloneRepository,
  fetchAptSources,
  uploadExternalBuild,
  publishS3,
} from '../../api/projectversions';

const PRIMARY  = '#571845';
const TH       = { backgroundColor: PRIMARY, color: 'white' };
const PAGE_SIZE = 20;

// ─── Build Upload modal ──────────────────────────────────────────────────────
function BuildUploadModal({ name, version, onClose }) {
  const [files,  setFiles]  = useState(null);
  const [busy,   setBusy]   = useState(false);
  const [error,  setError]  = useState('');

  async function handleSave() {
    if (!files || files.length === 0) { setError('Please select files to upload.'); return; }
    setBusy(true); setError('');
    try {
      await uploadExternalBuild(name, version, files);
      onClose(true);
    } catch (e) { setError(e.message); setBusy(false); }
  }

  return (
    <div className="modal fade show d-block" tabIndex="-1"
         style={{ backgroundColor: 'rgba(0,0,0,.4)' }}>
      <div className="modal-dialog modal-dialog-centered">
        <div className="modal-content">
          <div className="modal-header">
            <h5 className="modal-title"><i className="bi bi-upload me-2" />Upload external build</h5>
            <button className="btn-close" onClick={() => onClose(false)} disabled={busy} />
          </div>
          <div className="modal-body">
            {error && <div className="alert alert-danger py-2">{error}</div>}
            <p className="mb-2">Select all files produced by the <strong>debuild</strong> command:</p>
            <ul className="mb-3" style={{ fontSize: 13 }}>
              <li><strong>Mandatory:</strong> *.changes, *.buildinfo, *.deb</li>
              <li><strong>Optional:</strong> *.dsc, *.tar.xz, *.tar.gz (source package)</li>
            </ul>
            <input
              className="form-control" type="file" multiple
              accept=".changes,.buildinfo,.deb,.dsc,.tar.xz,.tar.gz"
              onChange={e => setFiles(e.target.files)}
            />
          </div>
          <div className="modal-footer">
            <button className="btn btn-secondary" onClick={() => onClose(false)} disabled={busy}>Cancel</button>
            <button className="btn btn-primary" onClick={handleSave}
                    disabled={busy || !files || files.length === 0}>
              {busy && <span className="spinner-border spinner-border-sm me-2" />}Upload
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── S3 Publish modal ─────────────────────────────────────────────────────────
function S3Modal({ pv, name, version, onClose }) {
  const [publishS3Enabled, setPublishS3Enabled] = useState(pv.publish_s3 ?? false);
  const [s3Endpoint,       setS3Endpoint]       = useState(pv.s3_endpoint ?? '');
  const [s3Path,           setS3Path]           = useState(pv.s3_path ?? '');
  const [busy,             setBusy]             = useState(false);
  const [error,            setError]            = useState('');

  async function handleSave() {
    setBusy(true); setError('');
    try {
      await publishS3(name, version, { publish_s3: publishS3Enabled, s3_endpoint: s3Endpoint, s3_path: s3Path });
      onClose(true);
    } catch (e) { setError(e.message); setBusy(false); }
  }

  return (
    <div className="modal fade show d-block" tabIndex="-1"
         style={{ backgroundColor: 'rgba(0,0,0,.4)' }}>
      <div className="modal-dialog modal-dialog-centered">
        <div className="modal-content">
          <div className="modal-header">
            <h5 className="modal-title"><i className="bi bi-cloud-upload me-2" />Publish to S3</h5>
            <button className="btn-close" onClick={() => onClose(false)} disabled={busy} />
          </div>
          <div className="modal-body">
            {error && <div className="alert alert-danger py-2">{error}</div>}
            <div className="form-check mb-3">
              <input className="form-check-input" type="checkbox" id="publish-s3"
                     checked={publishS3Enabled}
                     onChange={e => setPublishS3Enabled(e.target.checked)} />
              <label className="form-check-label fw-semibold" htmlFor="publish-s3">Publish to S3</label>
            </div>
            <div className="mb-3">
              <label className="form-label fw-semibold">S3 Endpoint</label>
              <input className="form-control" value={s3Endpoint}
                     disabled={!publishS3Enabled}
                     placeholder="e.g. https://s3.example.com"
                     onChange={e => setS3Endpoint(e.target.value)} />
            </div>
            <div className="mb-1">
              <label className="form-label fw-semibold">Publish Path</label>
              <input className="form-control" value={s3Path}
                     disabled={!publishS3Enabled}
                     placeholder="e.g. my-bucket/packages"
                     onChange={e => setS3Path(e.target.value)} />
            </div>
          </div>
          <div className="modal-footer">
            <button className="btn btn-secondary" onClick={() => onClose(false)} disabled={busy}>Cancel</button>
            <button className="btn btn-primary" onClick={handleSave} disabled={busy}>
              {busy && <span className="spinner-border spinner-border-sm me-2" />}Save
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Shared: project version info card + tab bar ──────────────────────────────
function PVHeader({ pv, name, version, onAction }) {
  if (!pv) {
    return (
      <div className="mb-3">
        <h1 className="mb-0" style={{ fontSize: 24, fontWeight: 500 }}>
          <i className="bi bi-collection me-2" />
          Project {name}/{version}
        </h1>
      </div>
    );
  }

  const baseParts = pv.basemirror?.split('/') ?? [];

  return (
    <>
      {/* Heading */}
      <div className="d-flex align-items-center mb-1 gap-2">
        <h1 className="mb-0 d-flex align-items-center gap-2 flex-wrap" style={{ fontSize: 24, fontWeight: 500 }}>
          <i className="bi bi-collection" />
          <NavLink to={`/project/${pv.project_name}`} style={{ color: 'inherit', textDecoration: 'none' }}>
            {pv.project_name}
          </NavLink>
          <span className="text-muted fw-normal">/</span>
          <span>{pv.name}</span>
          {pv.projectversiontype && pv.projectversiontype !== 'regular' && (
            <span className="badge bg-secondary ms-1" style={{ fontSize: 13, fontWeight: 400 }}>
              {pv.projectversiontype}
            </span>
          )}
        </h1>

        {/* Actions menu */}
        <div className="ms-auto dropdown">
          <button className="btn btn-sm btn-outline-secondary" data-bs-toggle="dropdown">
            <i className="bi bi-three-dots-vertical" />
          </button>
          <ul className="dropdown-menu dropdown-menu-end">
            {!pv.is_locked && (
              <li>
                <button className="dropdown-item" onClick={() => onAction('edit')}>
                  <i className="bi bi-pencil me-2" />Edit
                </button>
              </li>
            )}
            <li>
              <button className="dropdown-item" onClick={() => onAction('copy')}>
                <i className="bi bi-copy me-2" />Copy
              </button>
            </li>
            <li>
              <button className="dropdown-item" onClick={() => onAction('overlay')}>
                <i className="bi bi-layers me-2" />Create Overlay
              </button>
            </li>
            <li>
              <button className="dropdown-item" onClick={() => onAction('snapshot')}>
                <i className="bi bi-camera me-2" />Create Release Snapshot
              </button>
            </li>
            {!pv.is_locked && (
              <li>
                <button className="dropdown-item" onClick={() => onAction('lock')}>
                  <i className="bi bi-lock me-2" />Lock
                </button>
              </li>
            )}
            {!pv.is_locked && (
              <li>
                <button className="dropdown-item" onClick={() => onAction('delete')}>
                  <i className="bi bi-trash me-2 text-danger" />
                  <span className="text-danger">Delete</span>
                </button>
              </li>
            )}
            {!pv.is_locked && <li><hr className="dropdown-divider" /></li>}
            {!pv.is_locked && (
              <li>
                <button className="dropdown-item" onClick={() => onAction('upload')}>
                  <i className="bi bi-upload me-2" />Upload external build
                </button>
              </li>
            )}
            {!pv.is_locked && (
              <li>
                <button className="dropdown-item" onClick={() => onAction('s3')}>
                  <i className="bi bi-cloud-upload me-2" />Publish to S3
                </button>
              </li>
            )}
          </ul>
        </div>
      </div>

      {/* Description */}
      {pv.description && (
        <div className="text-muted mb-2" style={{ fontSize: 14 }}>{pv.description}</div>
      )}

      {/* Info card */}
      <div className="card card-body mb-3 py-2 px-3" style={{ fontSize: 13 }}>
        <table style={{ borderCollapse: 'collapse' }}>
          <tbody>
            <tr>
              <td className="pe-4 py-1"><strong>APT Repository</strong></td>
              <td className="pe-5 py-1">
                <a href={pv.apt_url} target="_blank" rel="noreferrer"
                   style={{ color: PRIMARY }}>{pv.apt_url}</a>
              </td>
              <td className="pe-4 py-1"><strong>State</strong></td>
              <td className="py-1">
                <i className={`bi ${pv.is_locked ? 'bi-lock-fill' : 'bi-unlock'} me-1`} />
                {pv.is_locked ? 'Locked' : 'Open'}
              </td>
            </tr>
            <tr>
              <td className="pe-4 py-1"><strong>Base Mirror</strong></td>
              <td className="pe-5 py-1">
                {pv.basemirror ? (
                  <NavLink to={`/mirror/${baseParts[0]}/${baseParts[1]}`}
                           style={{ color: PRIMARY }}>{pv.basemirror}</NavLink>
                ) : '—'}
              </td>
              <td className="pe-4 py-1"><strong>Dependency Policy</strong></td>
              <td className="py-1">{pv.dependency_policy}</td>
            </tr>
            <tr>
              <td className="pe-4 py-1"><strong>Architectures</strong></td>
              <td className="pe-5 py-1">{(pv.architectures ?? []).join(', ')}</td>
              <td className="pe-4 py-1"><strong>CI Builds</strong></td>
              <td className="py-1">
                <i className={`bi ${pv.ci_builds_enabled ? 'bi-check-lg text-success' : 'bi-dash'}`} />
              </td>
            </tr>
            <tr>
              <td className="pe-4 py-1"><strong>Retention Successful</strong></td>
              <td className="pe-5 py-1">
                {pv.retention_successful_builds > 0
                  ? `${pv.retention_successful_builds} build(s)` : '—'}
              </td>
              <td className="pe-4 py-1"><strong>Retention Failed</strong></td>
              <td className="py-1">
                {pv.retention_failed_builds > 0
                  ? `${pv.retention_failed_builds} day(s)` : '—'}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </>
  );
}

// ─── simple one-field text input modal ──────────────────────────────────────
function TextInputModal({ title, label, placeholder, initialValue = '', validate, onConfirm, onClose }) {
  const [value,   setValue]   = useState(initialValue);
  const [touched, setTouched] = useState(false);
  const [busy,    setBusy]    = useState(false);
  const [error,   setError]   = useState('');

  const validationError = validate ? validate(value) : '';
  const canSubmit = !validationError;

  async function handleOk() {
    if (!canSubmit) { setTouched(true); return; }
    setBusy(true); setError('');
    try { await onConfirm(value.trim()); onClose(true); }
    catch (e) { setError(e.message); setBusy(false); }
  }

  return (
    <div className="modal fade show d-block" tabIndex="-1"
         style={{ backgroundColor: 'rgba(0,0,0,.4)' }}>
      <div className="modal-dialog modal-dialog-centered">
        <div className="modal-content">
          <div className="modal-header">
            <h5 className="modal-title">{title}</h5>
            <button className="btn-close" onClick={() => onClose(false)} disabled={busy} />
          </div>
          <div className="modal-body">
            {error && <div className="alert alert-danger py-2">{error}</div>}
            <label className="form-label fw-semibold">{label}</label>
            <input className={fieldClass(touched && validationError)}
                   value={value} autoFocus placeholder={placeholder}
                   onChange={e => setValue(e.target.value)}
                   onBlur={() => setTouched(true)}
                   onKeyDown={e => e.key === 'Enter' && handleOk()} />
            {touched && validationError && <div className="invalid-feedback">{validationError}</div>}
          </div>
          <div className="modal-footer">
            <button className="btn btn-secondary" onClick={() => onClose(false)} disabled={busy}>Cancel</button>
            <button className="btn btn-primary" onClick={handleOk} disabled={busy || !canSubmit}>
              {busy && <span className="spinner-border spinner-border-sm me-2" />}Ok
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Add Dependency modal ─────────────────────────────────────────────────────
function AddDependencyModal({ pv, onClose }) {
  const [query, setQuery]       = useState('');
  const [options, setOptions]   = useState([]);
  const [selected, setSelected] = useState('');
  const [useCi, setUseCi]       = useState(false);
  const [busy, setBusy]         = useState(false);
  const [error, setError]       = useState('');

  useEffect(() => {
    if (!pv) return;
    fetchDependencies(pv.project_name, pv.name, query)
      .then(setOptions)
      .catch(() => {});
  }, [query, pv]);

  async function handleSave() {
    if (!selected) return;
    setBusy(true); setError('');
    try {
      await addDependency(pv.project_name, pv.name, selected, useCi);
      onClose(true);
    } catch (e) { setError(e.message); setBusy(false); }
  }

  return (
    <div className="modal fade show d-block" tabIndex="-1"
         style={{ backgroundColor: 'rgba(0,0,0,.4)' }}>
      <div className="modal-dialog modal-dialog-centered modal-lg">
        <div className="modal-content">
          <div className="modal-header">
            <h5 className="modal-title">Add Project Version Dependency</h5>
            <button className="btn-close" onClick={() => onClose(false)} disabled={busy} />
          </div>
          <div className="modal-body">
            {error && <div className="alert alert-danger py-2">{error}</div>}
            <div className="mb-3">
              <label className="form-label fw-semibold">Dependency</label>
              <input className="form-control mb-2" placeholder="Search…"
                     value={query} autoFocus
                     onChange={e => { setQuery(e.target.value); setSelected(''); }} />
              <select className="form-select" size={6} value={selected}
                      onChange={e => setSelected(e.target.value)}>
                {options.map(o => (
                  <option key={o.id} value={`${o.project_name}/${o.name}`}>
                    {o.is_mirror ? '📁 ' : '📦 '}
                    {o.project_name}/{o.name}
                    {o.dependency_policy !== 'strict' ? `  (${o.basemirror})` : ''}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-check">
              <input className="form-check-input" type="checkbox" id="use_cibuilds"
                     checked={useCi} onChange={e => setUseCi(e.target.checked)} />
              <label className="form-check-label" htmlFor="use_cibuilds">Use CI Builds</label>
            </div>
          </div>
          <div className="modal-footer">
            <button className="btn btn-secondary" onClick={() => onClose(false)} disabled={busy}>Cancel</button>
            <button className="btn btn-primary" onClick={handleSave}
                    disabled={busy || !selected}>
              {busy && <span className="spinner-border spinner-border-sm me-2" />}Ok
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Add/Edit Repository modal ────────────────────────────────────────────────
function RepoFormModal({ pv, repo, onClose }) {
  const isEdit = !!repo;
  const allArchs = ['amd64', 'i386', 'arm64', 'armhf'];
  const pvArchs  = pv?.architectures ?? [];

  const [url,       setUrl]       = useState(repo?.url ?? '');
  const [archs,     setArchs]     = useState(repo?.architectures ?? (pvArchs.length > 0 ? [pvArchs[0]] : []));
  const [lintian,   setLintian]   = useState(repo?.run_lintian ?? false);
  const [urlHints,  setUrlHints]  = useState([]);
  const [touched,   setTouched]   = useState({});
  const touch = f => setTouched(t => ({ ...t, [f]: true }));
  const [busy, setBusy]           = useState(false);
  const [error, setError]         = useState('');

  const urlError = isEdit ? '' : rules.gitUrl(url);

  // autocomplete: search existing repos by URL fragment
  useEffect(() => {
    if (isEdit || !url || url.length < 4) { setUrlHints([]); return; }
    fetch(apiUrl(`/api/repositories?url=${encodeURIComponent(url)}&projectversion_id=${pv?.id ?? ''}&page_size=10`),
          { credentials: 'same-origin' })
      .then(r => r.ok ? r.json() : { results: [] })
      .then(d => setUrlHints((d.results ?? []).map(r => r.url)))
      .catch(() => {});
  }, [url, isEdit, pv]);

  function toggleArch(arch) {
    setArchs(prev => prev.includes(arch) ? prev.filter(a => a !== arch) : [...prev, arch]);
  }

  async function handleSave() {
    setBusy(true); setError('');
    try {
      if (isEdit) {
        await editRepository(pv.project_name, pv.name, repo.id, archs, lintian);
      } else {
        await addRepository(pv.project_name, pv.name, url.trim(), archs, lintian);
      }
      onClose(true);
    } catch (e) { setError(e.message); setBusy(false); }
  }

  const canSave = isEdit
    ? archs.length > 0
    : (!urlError && archs.length > 0);

  return (
    <div className="modal fade show d-block" tabIndex="-1"
         style={{ backgroundColor: 'rgba(0,0,0,.4)' }}>
      <div className="modal-dialog modal-dialog-centered modal-lg">
        <div className="modal-content">
          <div className="modal-header">
            <h5 className="modal-title">{isEdit ? 'Edit git repository' : 'Add git repository'}</h5>
            <button className="btn-close" onClick={() => onClose(false)} disabled={busy} />
          </div>
          <div className="modal-body">
            {error && <div className="alert alert-danger py-2">{error}</div>}

            {/* URL (create only) */}
            {!isEdit ? (
              <div className="mb-3">
                <label className="form-label fw-semibold">Git Repository URL</label>
                <input className={fieldClass(touched.url && urlError)}
                       value={url} autoFocus
                       placeholder="https://github.com/…"
                       onChange={e => setUrl(e.target.value)}
                       onBlur={() => touch('url')} />
                {touched.url && urlError && <div className="invalid-feedback">{urlError}</div>}
                {urlHints.length > 0 && (
                  <ul className="list-group mt-1" style={{ fontSize: 13 }}>
                    {urlHints.map(h => (
                      <li key={h} className="list-group-item list-group-item-action py-1"
                          style={{ cursor: 'pointer' }} onClick={() => { setUrl(h); setUrlHints([]); }}>
                        {h}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ) : (
              <div className="mb-3">
                <label className="form-label fw-semibold">Git Repository URL</label>
                <div className="form-control-plaintext">{repo.url}</div>
              </div>
            )}

            {/* Architectures */}
            <div className="mb-3">
              <label className="form-label fw-semibold">Architectures</label>
              <div className="d-flex gap-3 flex-wrap">
                {allArchs.map(arch => {
                  const enabled = pvArchs.includes(arch);
                  return (
                    <div className="form-check" key={arch}>
                      <input className="form-check-input" type="checkbox"
                             id={`repo-arch-${arch}`}
                             disabled={!enabled}
                             checked={archs.includes(arch)}
                             onChange={() => toggleArch(arch)} />
                      <label className="form-check-label" htmlFor={`repo-arch-${arch}`}>{arch}</label>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Build options */}
            <div className="mb-3 form-check">
              <input className="form-check-input" type="checkbox" id="repo-lintian"
                     checked={lintian} onChange={e => setLintian(e.target.checked)} />
              <label className="form-check-label" htmlFor="repo-lintian">Run lintian</label>
            </div>
          </div>
          <div className="modal-footer">
            <button className="btn btn-secondary" onClick={() => onClose(false)} disabled={busy}>Cancel</button>
            <button className="btn btn-primary" onClick={handleSave} disabled={busy || !canSave}>
              {busy && <span className="spinner-border spinner-border-sm me-2" />}Ok
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Trigger Build modal ──────────────────────────────────────────────────────
function TriggerBuildModal({ pv, repo, onClose }) {
  const [gitref, setGitref] = useState('');
  const [busy, setBusy]     = useState(false);
  const [error, setError]   = useState('');

  async function handleOk() {
    setBusy(true); setError('');
    try {
      await triggerBuild(pv.project_name, pv.name, repo.id, gitref.trim() || undefined);
      onClose(true);
    } catch (e) { setError(e.message); setBusy(false); }
  }

  return (
    <div className="modal fade show d-block" tabIndex="-1"
         style={{ backgroundColor: 'rgba(0,0,0,.4)' }}>
      <div className="modal-dialog modal-dialog-centered">
        <div className="modal-content">
          <div className="modal-header">
            <h5 className="modal-title">Trigger build</h5>
            <button className="btn-close" onClick={() => onClose(false)} disabled={busy} />
          </div>
          <div className="modal-body">
            {error && <div className="alert alert-danger py-2">{error}</div>}
            <div className="text-muted mb-2" style={{ fontSize: 13 }}>{repo?.url}</div>
            <label className="form-label fw-semibold">Git ref (branch / tag / commit, optional)</label>
            <input className="form-control" value={gitref} autoFocus placeholder="e.g. main"
                   onChange={e => setGitref(e.target.value)}
                   onKeyDown={e => e.key === 'Enter' && handleOk()} />
          </div>
          <div className="modal-footer">
            <button className="btn btn-secondary" onClick={() => onClose(false)} disabled={busy}>Cancel</button>
            <button className="btn btn-primary" onClick={handleOk} disabled={busy}>
              {busy && <span className="spinner-border spinner-border-sm me-2" />}Trigger
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Paginated dependency/dependent/repository table ─────────────────────────
function PVTable({ columns, rows, total, page, onPageChange,
                   filterValue, onFilterChange, filterPlaceholder,
                   addButton, loading, error: errMsg }) {
  const totalPages = total > 0 ? Math.ceil(total / PAGE_SIZE) : 1;
  const colSpan    = columns.length;

  return (
    <div>
      <Pagination page={page} totalPages={totalPages} total={loading ? null : total}
                  pageSize={PAGE_SIZE} onPageChange={onPageChange} label="entries" />

      <div>
        <table className="table table-sm table-hover align-middle mb-0" style={{ fontSize: 13 }}>
          <thead>
            <tr>
              {/* First column always has the filter input */}
              <th style={{ ...TH, minWidth: 200 }}>
                <input
                  className="form-control form-control-sm"
                  placeholder={filterPlaceholder}
                  value={filterValue}
                  onChange={e => onFilterChange(e.target.value)}
                  style={{ minWidth: 160 }}
                />
              </th>
              {columns.slice(1).map((col, i) => (
                <th key={i} style={{ ...TH, ...col.thStyle }}>{col.label}</th>
              ))}
              <th style={{ ...TH, textAlign: 'right' }}>{addButton}</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan={colSpan + 1} className="text-center py-3 text-muted">Loading…</td></tr>
            )}
            {!loading && errMsg && (
              <tr><td colSpan={colSpan + 1} className="text-center py-3 text-danger">
                Unable to load data ({errMsg})
              </td></tr>
            )}
            {!loading && !errMsg && total === 0 && (
              <tr><td colSpan={colSpan + 1} className="text-center py-3 text-muted">No entries found</td></tr>
            )}
            {rows}
          </tbody>
        </table>
      </div>

    </div>
  );
}

// ─── Tab: Info (dependencies) ─────────────────────────────────────────────────
function InfoTab({ pv }) {
  const navigate = useNavigate();
  const [items, setItems]   = useState([]);
  const [total, setTotal]   = useState(null);
  const [error, setError]   = useState('');
  const [page, setPage]     = useState(1);
  const [filter, setFilter] = useState('');
  const [modal, setModal]   = useState(null);

  const load = useCallback(async (pg = page) => {
    if (!pv) return;
    setError('');
    try {
      const data = await fetchDependencies(pv.project_name, pv.name, filter, pg, PAGE_SIZE);
      setItems(data.results ?? []);
      setTotal(data.total_result_count ?? 0);
    } catch (e) { setError(e.message); setTotal(-1); }
  }, [pv, page, filter]);

  useEffect(() => { load(page); }, [page, pv]);

  const prevFilter = useRef(filter);
  useEffect(() => {
    if (prevFilter.current !== filter) { prevFilter.current = filter; setPage(1); load(1); }
  }, [filter]);

  function closeModal(reload) { setModal(null); if (reload) load(page); }

  const isExternal = (dep) => !pv?.dependency_ids?.includes(dep.id);

  function depLink(dep) {
    return dep.is_mirror ? `/mirror/${dep.project_name}/${dep.name}` : `/project/${dep.project_name}/${dep.name}`;
  }

  const addBtn = pv && !pv.is_locked ? (
    <button className="btn btn-sm border-0 p-0" style={{ color: 'white', fontSize: 20, lineHeight: 1 }}
      title="Add dependency" onClick={() => setModal({ type: 'add' })}>⊕</button>
  ) : null;

  const rows = items.map(dep => (
    <tr key={dep.id} style={{ cursor: 'pointer' }} onClick={e => { if (!e.target.closest('.dropdown')) navigate(depLink(dep)); }}>
      <td>
        <strong className="d-flex align-items-center gap-1">
          <i className={`bi ${dep.is_mirror ? 'bi-folder2-open' : 'bi-collection'}`} />
          {dep.project_name}/{dep.name}
        </strong>
      </td>
      <td>{(dep.architectures ?? []).join(', ')}</td>
      <td>
        {dep.basemirror && (
          <span style={{ cursor: 'pointer' }} onClick={e => {
            e.stopPropagation();
            const [mn, mv] = dep.basemirror.split('/');
            navigate(`/mirror/${mn}/${mv}`);
          }}>{dep.basemirror}</span>
        )}
      </td>
      <td className="text-center">
        <i className={`bi ${dep.is_locked ? 'bi-lock-fill' : 'bi-dash'}`} />
      </td>
      <td className="text-center">
        <i className={`bi ${dep.ci_builds_enabled ? 'bi-check-lg' : 'bi-dash'}`} />
      </td>
      <td>{dep.dependency_policy}</td>
      <td className="text-muted">{dep.description}</td>
      <td className="text-end">
        <div className="dropdown">
          <button className="btn btn-sm btn-link p-0 text-secondary" data-bs-toggle="dropdown" onClick={e => e.stopPropagation()}>
            <i className="bi bi-three-dots-vertical" />
          </button>
          <ul className="dropdown-menu dropdown-menu-end">
            <li>
              <button className="dropdown-item" onClick={() => navigate(depLink(dep))}>
                <i className="bi bi-list me-2" />Details
              </button>
            </li>
            {!isExternal(dep) && (
              <li>
                <button className="dropdown-item text-danger"
                        onClick={() => setModal({ type: 'removeDep', dep })}>
                  <i className="bi bi-trash me-2" />Remove
                </button>
              </li>
            )}
          </ul>
        </div>
      </td>
    </tr>
  ));

  return (
    <>
      {modal?.type === 'add' && <AddDependencyModal pv={pv} onClose={closeModal} />}
      {modal?.type === 'removeDep' && (
        <ConfirmModal
          title="Remove Dependency"
          body="Remove the dependency from the project version."
          onConfirm={() => removeDependency(pv.project_name, pv.name, modal.dep.project_name, modal.dep.name)}
          onClose={closeModal}
        />
      )}

      <h2 style={{ fontSize: 17, fontWeight: 600 }} className="mb-2">Project Dependencies</h2>
      <PVTable
        columns={[
          { label: 'Dependency' },
          { label: 'Architectures' },
          { label: 'Base Mirror' },
          { label: 'Locked',     thStyle: { textAlign: 'center' } },
          { label: 'CI Builds',  thStyle: { textAlign: 'center' } },
          { label: 'Dep. Policy' },
          { label: 'Description', thStyle: { width: '30%' } },
        ]}
        rows={rows}
        total={total ?? 0}
        page={page}
        onPageChange={setPage}
        filterValue={filter}
        onFilterChange={setFilter}
        filterPlaceholder="Dependency"
        addButton={addBtn}
        loading={total === null}
        error={error || (total === -1 ? 'load error' : null)}
      />
    </>
  );
}

// ─── Tab: Builds ──────────────────────────────────────────────────────────────
function BuildsTab({ pv }) {
  if (!pv) return null;
  return <BuildTable projectversion={pv} />;
}

// ─── Tab: Source Repositories ─────────────────────────────────────────────────
function ReposTab({ pv }) {
  const navigate  = useNavigate();
  const [items, setItems]   = useState([]);
  const [total, setTotal]   = useState(null);
  const [error, setError]   = useState('');
  const [page, setPage]     = useState(1);
  const [filter, setFilter] = useState('');
  const [modal, setModal]   = useState(null);
  const [ctxMenu, setCtxMenu] = useState(null);

  const load = useCallback(async (pg = page) => {
    if (!pv) return;
    setError('');
    try {
      const data = await fetchRepositories(pv.project_name, pv.name, filter, pg, PAGE_SIZE);
      setItems(data.results ?? []);
      setTotal(data.total_result_count ?? 0);
    } catch (e) { setError(e.message); setTotal(-1); }
  }, [pv, page, filter]);

  useEffect(() => { load(page); }, [page, pv]);

  const prevFilter = useRef(filter);
  useEffect(() => {
    if (prevFilter.current !== filter) { prevFilter.current = filter; setPage(1); load(1); }
  }, [filter]);

  function closeModal(reload) { setModal(null); if (reload) load(page); }

  // ── WebSocket: update last_build / last_successful_build on build events ─────────
  useEffect(() => {
    const ws = new WebSocket(wsUrl('/api/websocket'));
    ws.onmessage = (evt) => {
      let msg;
      try { msg = JSON.parse(evt.data); } catch { return; }
      if (msg.subject !== 7) return;                    // only build events
      const d = msg.data;
      if (!d?.sourcerepository_id) return;             // only source builds
      setItems(prev => prev.map(repo => {
        if (repo.id !== d.sourcerepository_id) return repo;
        const updated = { ...repo };
        // always update last_build with whatever we received
        updated.last_build = {
          id: d.id,
          buildstate: d.buildstate,
          version: d.version ?? repo.last_build?.version ?? '',
          sourcename: d.sourcename ?? '',
        };
        // if this build just became successful, update last_successful_build too
        if (d.buildstate === 'successful') {
          updated.last_successful_build = { ...updated.last_build };
        }
        return updated;
      }));
    };
    return () => ws.close();
  }, []);

  const BUILD_STATE_ICON = {
    successful: 'bi-check-circle-fill text-success',
    build_failed: 'bi-x-circle-fill text-danger',
    publish_failed: 'bi-exclamation-circle-fill text-warning',
    building: 'bi-arrow-repeat text-primary',
    publishing: 'bi-arrow-repeat text-primary',
    new: 'bi-circle text-muted',
  };

  function buildStateIcon(state) {
    return BUILD_STATE_ICON[state] ?? 'bi-circle text-muted';
  }

  const addBtn = pv && !pv.is_locked ? (
    <button className="btn btn-sm border-0 p-0" style={{ color: 'white', fontSize: 20, lineHeight: 1 }}
      title="Add repository" onClick={() => setModal({ type: 'add' })}>⊕</button>
  ) : null;

  const rows = items.map(repo => (
    <tr key={repo.id} style={{ cursor: 'pointer' }}
        onClick={e => { if (!e.target.closest('.dropdown')) navigate(`/repo/${repo.id}/info`); }}
        onContextMenu={e => { e.preventDefault(); setCtxMenu({ x: e.clientX, y: e.clientY, repo }); }}>
      <td><strong>{repo.name}</strong></td>
      <td>
        {repo.last_build && (
          <span className="d-flex align-items-center gap-2">
            <i className={`bi ${buildStateIcon(repo.last_build.buildstate)}`}
               title={repo.last_build.buildstate} />
            {repo.last_build.version}
            {repo.last_successful_build && (
              <span className="ms-3 d-flex align-items-center gap-1">
                <i className={`bi ${buildStateIcon(repo.last_successful_build.buildstate)}`}
                   title={repo.last_successful_build.buildstate} />
                {repo.last_successful_build.version}
              </span>
            )}
          </span>
        )}
      </td>
      <td>{(repo.architectures ?? []).join(', ')}</td>
      <td style={{ fontFamily: 'monospace', fontSize: 12, userSelect: 'all' }}
          onClick={e => e.stopPropagation()}>{repo.url}</td>
      <td>{repo.state}</td>
      <td className="text-center">
        <i className={`bi ${repo.run_lintian ? 'bi-check-lg' : 'bi-dash'}`} />
      </td>
      <td className="text-end">
        <div className="dropdown">
          <button className="btn btn-sm btn-link p-0 text-secondary" data-bs-toggle="dropdown" onClick={e => e.stopPropagation()}>
            <i className="bi bi-three-dots-vertical" />
          </button>
          <ul className="dropdown-menu dropdown-menu-end">
            <li>
              <button className="dropdown-item"
                      onClick={() => navigate(`/repo/${repo.id}/info`)}>
                <i className="bi bi-list me-2" />Details
              </button>
            </li>
            <li>
              <button className="dropdown-item" onClick={() => setModal({ type: 'edit', repo })}>
                <i className="bi bi-pencil me-2" />Edit
              </button>
            </li>
            <li>
              <button className="dropdown-item text-danger"
                      onClick={() => setModal({ type: 'remove', repo })}>
                <i className="bi bi-trash me-2" />Remove
              </button>
            </li>
            <li>
              <button className="dropdown-item"
                      onClick={() => { buildRepository(pv.project_name, pv.name, repo.id).catch(() => {}); }}>
                <i className="bi bi-arrow-repeat me-2" />Check for new builds
              </button>
            </li>
            <li>
              <button className="dropdown-item" onClick={() => setModal({ type: 'trigger', repo })}>
                <i className="bi bi-play me-2" />Trigger build
              </button>
            </li>
            <li>
              <button className="dropdown-item" onClick={() => setModal({ type: 'reclone', repo })}>
                <i className="bi bi-arrow-down-up me-2" />Re-clone
              </button>
            </li>
          </ul>
        </div>
      </td>
    </tr>
  ));

  return (
    <>
      {ctxMenu && (
        <ContextMenu x={ctxMenu.x} y={ctxMenu.y} onClose={() => setCtxMenu(null)}>
          <li><button className="dropdown-item" onClick={() => { navigate(`/repo/${ctxMenu.repo.id}/info`); setCtxMenu(null); }}><i className="bi bi-list me-2" />Details</button></li>
          <li><button className="dropdown-item" onClick={() => { setModal({ type: 'edit', repo: ctxMenu.repo }); setCtxMenu(null); }}><i className="bi bi-pencil me-2" />Edit</button></li>
          <li><button className="dropdown-item text-danger" onClick={() => { setModal({ type: 'remove', repo: ctxMenu.repo }); setCtxMenu(null); }}><i className="bi bi-trash me-2" />Remove</button></li>
          <li><button className="dropdown-item" onClick={() => { buildRepository(pv.project_name, pv.name, ctxMenu.repo.id).catch(() => {}); setCtxMenu(null); }}><i className="bi bi-arrow-repeat me-2" />Check for new builds</button></li>
          <li><button className="dropdown-item" onClick={() => { setModal({ type: 'trigger', repo: ctxMenu.repo }); setCtxMenu(null); }}><i className="bi bi-play me-2" />Trigger build</button></li>
          <li><button className="dropdown-item" onClick={() => { setModal({ type: 'reclone', repo: ctxMenu.repo }); setCtxMenu(null); }}><i className="bi bi-arrow-down-up me-2" />Re-clone</button></li>
        </ContextMenu>
      )}
      {modal?.type === 'add'    && <RepoFormModal pv={pv} onClose={closeModal} />}
      {modal?.type === 'edit'   && <RepoFormModal pv={pv} repo={modal.repo} onClose={closeModal} />}
      {modal?.type === 'remove' && (
        <ConfirmModal
          title="Remove Source Repository"
          body={<>Remove <strong>{modal.repo.name}</strong> from this project version?</>}
          onConfirm={() => removeRepository(pv.project_name, pv.name, modal.repo.id)}
          onClose={closeModal}
        />
      )}
      {modal?.type === 'trigger' && (
        <TriggerBuildModal pv={pv} repo={modal.repo} onClose={closeModal} />
      )}
      {modal?.type === 'reclone' && (
        <ConfirmModal
          title="Re-clone Repository"
          body={<>Re-clone <strong>{modal.repo.name}</strong>?</>}
          onConfirm={() => recloneRepository(pv.project_name, pv.name, modal.repo.id)}
          onClose={closeModal}
        />
      )}

      <PVTable
        columns={[
          { label: 'Name', thStyle: { minWidth: 200 } },
          { label: 'Last Build' },
          { label: 'Architectures' },
          { label: 'Git URL', thStyle: { minWidth: 300 } },
          { label: 'State' },
          { label: 'Lintian', thStyle: { textAlign: 'center' } },
        ]}
        rows={rows}
        total={total ?? 0}
        page={page}
        onPageChange={setPage}
        filterValue={filter}
        onFilterChange={setFilter}
        filterPlaceholder="Git URL"
        addButton={addBtn}
        loading={total === null}
        error={error || (total === -1 ? 'load error' : null)}
      />
    </>
  );
}

// ─── Tab: APT Sources ─────────────────────────────────────────────────────────
function AptSourcesTab({ pv }) {
  const [sources,   setSources]   = useState('');
  const [sourcesCI, setSourcesCI] = useState('');
  const [loading,   setLoading]   = useState(true);

  useEffect(() => {
    if (!pv) return;
    setLoading(true);
    Promise.all([
      fetchAptSources(pv.project_name, pv.name, false),
      pv.ci_builds_enabled ? fetchAptSources(pv.project_name, pv.name, true) : Promise.resolve(''),
    ]).then(([s, c]) => { setSources(s); setSourcesCI(c); setLoading(false); })
      .catch(() => setLoading(false));
  }, [pv]);

  function formatSources(raw) {
    const lines = raw.split('\n');
    // drop trailing empty line
    if (lines[lines.length - 1] === '') lines.pop();
    return lines.map((line, i) => {
      if (line.startsWith('#')) {
        return <span key={i} className="text-muted">{line}{'\n'}</span>;
      }
      if (line.startsWith('deb ')) {
        const parts = line.split(' ');
        const components = parts.slice(3).join(' ');
        return (
          <strong key={i} style={{ display: 'block' }}>
            <span>{parts[0]}</span>{' '}
            <span>{parts[1]}</span>{' '}
            <span>{parts[2]}</span>{' '}
            <span>{components}</span>{'\n'}
          </strong>
        );
      }
      return <span key={i}>{line}{'\n'}</span>;
    });
  }

  if (loading) return <div className="text-muted py-3">Loading…</div>;

  return (
    <div>
      <div className="mb-4">
        <h2 style={{ fontSize: 17, fontWeight: 600 }} className="mb-2">APT Sources</h2>
        <pre className="bg-light p-3 rounded" style={{ fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
          {formatSources(sources)}
        </pre>
      </div>
      {pv?.ci_builds_enabled && sourcesCI && (
        <div>
          <h2 style={{ fontSize: 17, fontWeight: 600 }} className="mb-2">APT Sources (CI Builds)</h2>
          <pre className="bg-light p-3 rounded" style={{ fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
            {formatSources(sourcesCI)}
          </pre>
        </div>
      )}
    </div>
  );
}

// ─── Tab: Dependents ──────────────────────────────────────────────────────────
function DependentsTab({ pv }) {
  const navigate  = useNavigate();
  const [items, setItems]   = useState([]);
  const [total, setTotal]   = useState(null);
  const [error, setError]   = useState('');
  const [page, setPage]     = useState(1);
  const [filter, setFilter] = useState('');

  const load = useCallback(async (pg = page) => {
    if (!pv) return;
    setError('');
    try {
      const data = await fetchDependents(pv.project_name, pv.name, filter, pg, PAGE_SIZE);
      setItems(data.results ?? []);
      setTotal(data.total_result_count ?? 0);
    } catch (e) { setError(e.message); setTotal(-1); }
  }, [pv, page, filter]);

  useEffect(() => { load(page); }, [page, pv]);

  const prevFilter = useRef(filter);
  useEffect(() => {
    if (prevFilter.current !== filter) { prevFilter.current = filter; setPage(1); load(1); }
  }, [filter]);

  function depLink(dep) {
    return dep.is_mirror ? `/mirror/${dep.project_name}/${dep.name}` : `/project/${dep.project_name}/${dep.name}`;
  }

  const rows = items.map(dep => (
    <tr key={dep.id} style={{ cursor: 'pointer' }} onClick={e => { if (!e.target.closest('.dropdown')) navigate(depLink(dep)); }}>
      <td>
        <strong className="d-flex align-items-center gap-1">
          <i className={`bi ${dep.is_mirror ? 'bi-folder2-open' : 'bi-collection'}`} />
          {dep.project_name}/{dep.name}
        </strong>
      </td>
      <td>{(dep.architectures ?? []).join(', ')}</td>
      <td>
        {dep.basemirror && (
          <span style={{ cursor: 'pointer' }} onClick={e => {
            e.stopPropagation();
            const [mn, mv] = dep.basemirror.split('/');
            navigate(`/mirror/${mn}/${mv}`);
          }}>{dep.basemirror}</span>
        )}
      </td>
      <td className="text-center">
        <i className={`bi ${dep.is_locked ? 'bi-lock-fill' : 'bi-dash'}`} />
      </td>
      <td className="text-center">
        <i className={`bi ${dep.ci_builds_enabled ? 'bi-check-lg' : 'bi-dash'}`} />
      </td>
      <td className="text-muted">{dep.description}</td>
      <td className="text-end">
        <div className="dropdown">
          <button className="btn btn-sm btn-link p-0 text-secondary" data-bs-toggle="dropdown" onClick={e => e.stopPropagation()}>
            <i className="bi bi-three-dots-vertical" />
          </button>
          <ul className="dropdown-menu dropdown-menu-end">
            <li>
              <button className="dropdown-item" onClick={() => navigate(depLink(dep))}>
                <i className="bi bi-list me-2" />Details
              </button>
            </li>
          </ul>
        </div>
      </td>
    </tr>
  ));

  return (
    <>
      <h2 style={{ fontSize: 17, fontWeight: 600 }} className="mb-2">Project Dependents</h2>
      <PVTable
        columns={[
          { label: 'Dependent' },
          { label: 'Architectures' },
          { label: 'Base Mirror' },
          { label: 'Locked',    thStyle: { textAlign: 'center' } },
          { label: 'CI Builds', thStyle: { textAlign: 'center' } },
          { label: 'Description', thStyle: { width: '30%' } },
        ]}
        rows={rows}
        total={total ?? 0}
        page={page}
        onPageChange={setPage}
        filterValue={filter}
        onFilterChange={setFilter}
        filterPlaceholder="Dependent"
        addButton={null}
        loading={total === null}
        error={error || (total === -1 ? 'load error' : null)}
      />
    </>
  );
}

// ─── Root component ───────────────────────────────────────────────────────────
export default function ProjectVersionDetailPage() {
  const { name, version } = useParams();
  const navigate           = useNavigate();

  const [pv, setPv]       = useState(null);
  const [pvError, setPvError] = useState('');
  const [modal, setModal] = useState(null);

  const base = `/project/${name}/${version}`;

  // Load project version metadata
  useEffect(() => {
    fetchProjectVersion(name, version)
      .then(setPv)
      .catch(e => setPvError(e.message));
  }, [name, version]);

  function closeModal(reload) {
    setModal(null);
    if (reload) {
      fetchProjectVersion(name, version).then(setPv).catch(() => {});
    }
  }

  // ── Action handlers ────────────────────────────────────────────────────────
  async function handleOverlay(overlayName) {
    const res = await fetch(apiUrl(`/api2/project/${name}/${version}/overlay`), {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: overlayName }),
    });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
    const data = await res.json();
    navigate(`/project/${name}/${data.name}/info`);
  }

  async function handleSnapshot(snapName) {
    const res = await fetch(apiUrl(`/api2/project/${name}/${version}/snapshot`), {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: snapName }),
    });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
    const data = await res.json();
    navigate(`/project/${name}/${data.name}/info`);
  }

  function onAction(type) { setModal({ type }); }

  return (
    <div className="p-3">

      {/* ── Modals ── */}
      {modal?.type === 'edit' && pv && (
        <ProjectVersionForm projectName={name} projectVersion={pv} onClose={closeModal} />
      )}
      {modal?.type === 'copy' && pv && (
        <CopyProjectVersionForm
          projectName={name}
          projectVersion={pv}
          onClose={(reload) => { closeModal(); if (reload) navigate(`/project/${name}`); }}
        />
      )}
      {modal?.type === 'overlay' && (
        <TextInputModal
          title="Create Overlay"
          label="Overlay name"
          placeholder="overlay-name"
          validate={rules.version}
          onConfirm={handleOverlay}
          onClose={closeModal}
        />
      )}
      {modal?.type === 'snapshot' && (
        <TextInputModal
          title="Create Release Snapshot"
          label="Snapshot name"
          placeholder="snapshot-name"
          validate={rules.version}
          onConfirm={handleSnapshot}
          onClose={closeModal}
        />
      )}
      {modal?.type === 'lock' && pv && (
        <ConfirmModal
          title="Lock Project Version"
          body={<>Lock project version <strong>{pv.name}</strong>? This cannot be undone.</>}
          onConfirm={() => lockProjectVersion(name, version)}
          onClose={closeModal}
        />
      )}
      {modal?.type === 'delete' && pv && (
        <ConfirmModal
          title="Delete Project Version"
          body={<>Delete project version <strong>{pv.name}</strong>? This cannot be undone.</>}
          onConfirm={() => deleteProjectVersion(name, version)}
          onClose={reload => {
            setModal(null);
            if (reload) navigate(`/project/${name}`);
          }}
        />
      )}
      {modal?.type === 'upload' && pv && (
        <BuildUploadModal name={name} version={version} onClose={closeModal} />
      )}
      {modal?.type === 's3' && pv && (
        <S3Modal pv={pv} name={name} version={version} onClose={closeModal} />
      )}

      {/* ── Header (info card + actions) ── */}
      {pvError && (
        <div className="alert alert-danger py-2">Failed to load: {pvError}</div>
      )}
      <PVHeader pv={pv} name={name} version={version} onAction={onAction} />

      {/* ── Tab bar ── */}
      <ul className="nav nav-tabs mb-3">
        {[
          { label: 'Info',                 path: `${base}/info` },
          { label: 'Builds',              path: `${base}/builds` },
          { label: 'Source Repositories', path: `${base}/repos` },
          { label: 'APT Sources',         path: `${base}/aptsources` },
          { label: 'Dependents',          path: `${base}/dependents` },
        ].map(({ label, path }) => (
          <li className="nav-item" key={path}>
            <NavLink className={({ isActive }) => `nav-link${isActive ? ' active' : ' text-muted'}`}
                     to={path}>{label}</NavLink>
          </li>
        ))}
      </ul>

      {/* ── Routed tab content ── */}
      <Routes>
        <Route path="info"       element={<InfoTab pv={pv} />} />
        <Route path="builds"     element={<BuildsTab pv={pv} />} />
        <Route path="repos"      element={<ReposTab pv={pv} />} />
        <Route path="aptsources" element={<AptSourcesTab pv={pv} />} />
        <Route path="dependents" element={<DependentsTab pv={pv} />} />
        <Route path="*"          element={<Navigate to={`${base}/info`} replace />} />
      </Routes>
    </div>
  );
}
