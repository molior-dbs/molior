/**
 * ProjectDetailPage — port of ProjectInfoComponent, ProjectPermissionsComponent,
 * ProjectTokensComponent + their HTML templates.
 *
 * Route: /project/:name/*
 * Tabs (sub-routes):
 *   /project/:name/versions     → VersionsTab  (project version list)
 *   /project/:name/permissions  → PermissionsTab
 *   /project/:name/tokens       → TokensTab
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate, useLocation, NavLink } from 'react-router-dom';
import { rules, fieldClass, fieldError } from '../../lib/validate';
import { apiUrl } from '../../lib/base';
import {
  fetchProject,
  fetchProjectVersions,
  deleteProjectVersion,
  lockProjectVersion,
  exportProjectVersion,
  importProjectVersion,
} from '../../api/projectversions';
import {
  deleteProject,
  fetchProjectPermissions,
  fetchPermissionCandidates,
  addProjectPermission,
  editProjectPermission,
  deleteProjectPermission,
  fetchProjectTokens,
  createProjectToken,
  linkProjectToken,
  deleteProjectToken,
} from '../../api/projects';
import ProjectForm from './ProjectForm';
import ProjectVersionForm from './ProjectVersionForm';
import CopyProjectVersionForm from './CopyProjectVersionForm';
import ConfirmModal from '../build/ConfirmModal';
import ContextMenu from '../common/ContextMenu';

const PRIMARY  = '#571845';
const TH       = { backgroundColor: PRIMARY, color: 'white' };
const PAGE_SIZE = 20;
const ROLES    = ['member', 'manager', 'owner'];

// ─── tiny import helper ───────────────────────────────────────────────────────
function useImportInput(onImport) {
  const ref = useRef(null);
  function trigger() { ref.current?.click(); }
  async function handleChange(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = '';
    await onImport(file);
  }
  const input = (
    <input ref={ref} type="file" accept=".json"
           style={{ display: 'none' }} onChange={handleChange} />
  );
  return { trigger, input };
}

// ─── text input modal ─────────────────────────────────────────────────────────
function TextInputModal({ title, label, placeholder, validate, onConfirm, onClose }) {
  const [value,   setValue]   = useState('');
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

// ─── shared pagination bar ────────────────────────────────────────────────────
function PaginationBar({ page, total, pageSize, onChange }) {
  const totalPages = total > 0 ? Math.ceil(total / pageSize) : 1;
  return (
    <div className="d-flex justify-content-between align-items-center mt-2 px-1" style={{ fontSize: 13 }}>
      <span className="text-muted">
        {total > 0
          ? `${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, total)} of ${total}`
          : ''}
      </span>
      <nav>
        <ul className="pagination pagination-sm mb-0">
          <li className={`page-item ${page <= 1 ? 'disabled' : ''}`}>
            <button className="page-link" onClick={() => onChange(1)}>&laquo;</button>
          </li>
          <li className={`page-item ${page <= 1 ? 'disabled' : ''}`}>
            <button className="page-link" onClick={() => onChange(page - 1)}>&lsaquo;</button>
          </li>
          <li className="page-item disabled">
            <span className="page-link">{page} / {totalPages}</span>
          </li>
          <li className={`page-item ${page >= totalPages ? 'disabled' : ''}`}>
            <button className="page-link" onClick={() => onChange(page + 1)}>&rsaquo;</button>
          </li>
          <li className={`page-item ${page >= totalPages ? 'disabled' : ''}`}>
            <button className="page-link" onClick={() => onChange(totalPages)}>&raquo;</button>
          </li>
        </ul>
      </nav>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Tab: Versions
// ─────────────────────────────────────────────────────────────────────────────
function VersionsTab({ name, project }) {
  const navigate = useNavigate();

  const [versions,    setVersions]    = useState([]);
  const [total,       setTotal]       = useState(null);
  const [error,       setError]       = useState('');
  const [page,        setPage]        = useState(1);
  const [filterName,  setFilterName]  = useState('');
  const [modal,       setModal]       = useState(null);
  const [ctxMenu,     setCtxMenu]     = useState(null);

  const load = useCallback(async (pg = page) => {
    setError(''); setTotal(null);
    try {
      const data = await fetchProjectVersions(name, { q: filterName, page: pg, page_size: PAGE_SIZE });
      setVersions(data.results ?? []);
      setTotal(data.total_result_count ?? 0);
    } catch (e) { setError(e.message); setTotal(-1); }
  }, [name, page, filterName]);

  useEffect(() => { load(page); }, [page]);

  const prevFilterRef = useRef(filterName);
  useEffect(() => {
    if (prevFilterRef.current !== filterName) {
      prevFilterRef.current = filterName;
      setPage(1); load(1);
    }
  }, [filterName]);

  function closeModal(reload) { setModal(null); if (reload) load(page); }

  // export
  async function handleExport(pv) {
    try {
      const data = await exportProjectVersion(pv.project_name, pv.name);
      const blob = new Blob([JSON.stringify(data)], { type: 'application/json' });
      const url  = URL.createObjectURL(blob);
      const a    = Object.assign(document.createElement('a'), {
        href: url, download: `${data.project_name}_${data.name}.projectversion_export.json`,
        style: 'display:none',
      });
      document.body.appendChild(a); a.click();
      document.body.removeChild(a); URL.revokeObjectURL(url);
    } catch (e) { alert(`Export failed: ${e.message}`); }
  }

  const { trigger: triggerImport, input: importInput } = useImportInput(async (file) => {
    try {
      const fd = new FormData();
      fd.append('file', file);
      const result = await importProjectVersion(fd);
      const pv     = result.projectversion;
      for (const repo of (result.sourcerepositories || [])) {
        await fetch(apiUrl(`/api2/project/${pv.project_name}/${pv.name}/repositories`), {
          method: 'POST', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            url: repo.url,
            architectures: repo.architectures?.length ? repo.architectures : pv.architectures,
            run_lintian: repo.run_lintian ? 'true' : 'false',
          }),
        });
      }
      navigate(`/project/${pv.project_name}/${pv.name}`);
    } catch (e) { alert(`Import failed: ${e.message}`); }
  });

  return (
    <>
      {importInput}

      {ctxMenu && (
        <ContextMenu x={ctxMenu.x} y={ctxMenu.y} onClose={() => setCtxMenu(null)}>
          <li><button className="dropdown-item" onClick={() => { navigate(`/project/${name}/${ctxMenu.pv.name}`); setCtxMenu(null); }}><i className="bi bi-list me-2" />Details</button></li>
          <li><button className="dropdown-item" onClick={() => { setModal({ type: 'edit', pv: ctxMenu.pv }); setCtxMenu(null); }}><i className="bi bi-pencil me-2" />Edit</button></li>
          <li><button className="dropdown-item" onClick={() => { setModal({ type: 'copy', pv: ctxMenu.pv }); setCtxMenu(null); }}><i className="bi bi-copy me-2" />Copy</button></li>
          <li><button className="dropdown-item" onClick={() => { setModal({ type: 'overlay', pv: ctxMenu.pv }); setCtxMenu(null); }}><i className="bi bi-layers me-2" />Create Overlay</button></li>
          <li><button className="dropdown-item" onClick={() => { setModal({ type: 'snapshot', pv: ctxMenu.pv }); setCtxMenu(null); }}><i className="bi bi-camera me-2" />Create Release Snapshot</button></li>
          {!ctxMenu.pv.is_locked && <li><button className="dropdown-item" onClick={() => { setModal({ type: 'lock', pv: ctxMenu.pv }); setCtxMenu(null); }}><i className="bi bi-lock me-2" />Lock</button></li>}
          <li><button className="dropdown-item" onClick={() => { handleExport(ctxMenu.pv); setCtxMenu(null); }}><i className="bi bi-download me-2" />Export Project Version</button></li>
          <li><button className="dropdown-item text-danger" onClick={() => { setModal({ type: 'delete', pv: ctxMenu.pv }); setCtxMenu(null); }}><i className="bi bi-trash me-2" />Delete</button></li>
        </ContextMenu>
      )}

      {modal?.type === 'create' && (
        <ProjectVersionForm projectName={name} onClose={closeModal} />
      )}
      {modal?.type === 'edit' && (
        <ProjectVersionForm projectName={name} projectVersion={modal.pv} onClose={closeModal} />
      )}
      {modal?.type === 'copy' && (
        <CopyProjectVersionForm projectName={name} projectVersion={modal.pv} onClose={closeModal} />
      )}
      {modal?.type === 'delete' && (
        <ConfirmModal
          title="Delete Project Version"
          body={<>Delete project version <strong>{modal.pv?.name}</strong>? This cannot be undone.</>}
          onConfirm={() => deleteProjectVersion(modal.pv.project_name, modal.pv.name)}
          onClose={closeModal}
        />
      )}
      {modal?.type === 'lock' && (
        <ConfirmModal
          title="Lock Project Version"
          body={<>Lock project version <strong>{modal.pv?.name}</strong>?</>}
          onConfirm={() => lockProjectVersion(modal.pv.project_name, modal.pv.name)}
          onClose={closeModal}
        />
      )}
      {modal?.type === 'overlay' && (
        <TextInputModal title="Create Overlay" label="Overlay name" placeholder="overlay-name"
          validate={rules.version}
          onConfirm={async (overlayName) => {
            const res = await fetch(apiUrl(`/api2/project/${modal.pv.project_name}/${modal.pv.name}/overlay`), {
              method: 'POST', credentials: 'same-origin',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ name: overlayName }),
            });
            if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
            const data = await res.json();
            navigate(`/project/${name}/${data.name}`);
          }}
          onClose={closeModal}
        />
      )}
      {modal?.type === 'snapshot' && (
        <TextInputModal title="Create Release Snapshot" label="Snapshot name" placeholder="snapshot-name"
          validate={rules.version}
          onConfirm={async (snapName) => {
            const res = await fetch(apiUrl(`/api2/project/${modal.pv.project_name}/${modal.pv.name}/snapshot`), {
              method: 'POST', credentials: 'same-origin',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ name: snapName }),
            });
            if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
            const data = await res.json();
            navigate(`/project/${name}/${data.name}`);
          }}
          onClose={closeModal}
        />
      )}

      <div>
        <table className="table table-sm table-hover align-middle mb-0" style={{ fontSize: 13 }}>
          <thead>
            <tr>
              <th style={{ ...TH, minWidth: 180 }}>
                <input className="form-control form-control-sm bg-transparent border-0 text-white"
                       placeholder="Version" value={filterName}
                       onChange={e => setFilterName(e.target.value)} style={{ minWidth: 140 }} />
              </th>
              <th style={{ ...TH, textAlign: 'center', whiteSpace: 'nowrap' }}># Builds</th>
              <th style={{ ...TH, textAlign: 'center', whiteSpace: 'nowrap' }}># CI Builds</th>
              <th style={{ ...TH, whiteSpace: 'nowrap' }}>Architectures</th>
              <th style={{ ...TH, whiteSpace: 'nowrap' }}>Base Mirror</th>
              <th style={{ ...TH, textAlign: 'center', whiteSpace: 'nowrap' }}>Locked</th>
              <th style={{ ...TH, textAlign: 'center', whiteSpace: 'nowrap' }}>CI Builds</th>
              <th style={{ ...TH, width: '40%' }}>Description</th>
              <th style={{ ...TH, textAlign: 'right' }}>
                <div className="dropdown">
                  <button className="btn btn-sm border-0 p-0"
                          style={{ color: 'white', fontSize: 20, lineHeight: 1 }}
                          data-bs-toggle="dropdown" title="Add">⊕</button>
                  <ul className="dropdown-menu dropdown-menu-end">
                    <li>
                      <button className="dropdown-item" onClick={() => setModal({ type: 'create' })}>
                        Create Project Version
                      </button>
                    </li>
                    <li>
                      <button className="dropdown-item" onClick={triggerImport}>
                        Import Project Version
                      </button>
                    </li>
                  </ul>
                </div>
              </th>
            </tr>
          </thead>
          <tbody>
            {total === null && (
              <tr><td colSpan={9} className="text-center py-3 text-muted">Loading…</td></tr>
            )}
            {total === -1 && (
              <tr><td colSpan={9} className="text-center py-3 text-danger">Unable to load data ({error})</td></tr>
            )}
            {total === 0 && (
              <tr><td colSpan={9} className="text-center py-3 text-muted">No entries found</td></tr>
            )}

            {versions.map(pv => (
              <tr key={pv.id} style={{ cursor: 'pointer' }}
                  onClick={e => { if (!e.target.closest('.dropdown')) navigate(`/project/${name}/${pv.name}`); }}
                  onContextMenu={e => { e.preventDefault(); setCtxMenu({ x: e.clientX, y: e.clientY, pv }); }}>
                <td><strong>{pv.name}</strong></td>
                <td className="text-center">{pv.buildCount > 0 ? pv.buildCount : ''}</td>
                <td className="text-center">{pv.cibuildCount > 0 ? pv.cibuildCount : ''}</td>
                <td>{(pv.architectures ?? []).join(', ')}</td>
                <td>
                  {pv.basemirror && (
                    <span style={{ cursor: 'pointer' }} onClick={e => {
                      e.stopPropagation();
                      const [mName, mVer] = pv.basemirror.split('/');
                      navigate(`/mirror/${mName}/${mVer}`);
                    }}>{pv.basemirror}</span>
                  )}
                </td>
                <td className="text-center">
                  <i className={`bi ${pv.is_locked ? 'bi-lock-fill' : 'bi-dash'}`} />
                </td>
                <td className="text-center">
                  <i className={`bi ${pv.ci_builds_enabled ? 'bi-check-lg' : 'bi-dash'}`} />
                </td>
                <td className="text-muted">{pv.description}</td>
                <td className="text-end">
                  <div className="dropdown">
                    <button className="btn btn-sm btn-link p-0 text-secondary" data-bs-toggle="dropdown" onClick={e => e.stopPropagation()}>
                      <i className="bi bi-three-dots-vertical" />
                    </button>
                    <ul className="dropdown-menu dropdown-menu-end">
                      <li><button className="dropdown-item" onClick={() => navigate(`/project/${name}/${pv.name}`)}>
                        <i className="bi bi-list me-2" />Details
                      </button></li>
                      <li><button className="dropdown-item" onClick={() => setModal({ type: 'edit', pv })}>
                        <i className="bi bi-pencil me-2" />Edit
                      </button></li>
                      <li><button className="dropdown-item" onClick={() => setModal({ type: 'copy', pv })}>
                        <i className="bi bi-copy me-2" />Copy
                      </button></li>
                      <li><button className="dropdown-item" onClick={() => setModal({ type: 'overlay', pv })}>
                        <i className="bi bi-layers me-2" />Create Overlay
                      </button></li>
                      <li><button className="dropdown-item" onClick={() => setModal({ type: 'snapshot', pv })}>
                        <i className="bi bi-camera me-2" />Create Release Snapshot
                      </button></li>
                      {!pv.is_locked && (
                        <li><button className="dropdown-item" onClick={() => setModal({ type: 'lock', pv })}>
                          <i className="bi bi-lock me-2" />Lock
                        </button></li>
                      )}
                      <li><button className="dropdown-item" onClick={() => handleExport(pv)}>
                        <i className="bi bi-download me-2" />Export Project Version
                      </button></li>
                      <li><button className="dropdown-item text-danger" onClick={() => setModal({ type: 'delete', pv })}>
                        <i className="bi bi-trash me-2" />Delete
                      </button></li>
                    </ul>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <PaginationBar page={page} total={total ?? 0} pageSize={PAGE_SIZE} onChange={setPage} />
    </>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Tab: Permissions
// ─────────────────────────────────────────────────────────────────────────────

function PermissionModal({ name, permission, onClose }) {
  const isEdit = !!permission;
  const [username,    setUsername]    = useState(permission?.username ?? '');
  const [role,        setRole]        = useState(permission?.role ?? ROLES[0]);
  const [candidates,  setCandidates]  = useState([]);
  const [busy,        setBusy]        = useState(false);
  const [error,       setError]       = useState('');

  // autocomplete candidates (add only)
  useEffect(() => {
    if (isEdit) return;
    fetchPermissionCandidates(name, username)
      .then(data => setCandidates(data.results ?? []))
      .catch(() => {});
  }, [username, isEdit, name]);

  const usernameError = isEdit ? '' : rules.required(username, 2, 'Username');

  async function handleSave() {
    if (usernameError) return;
    setBusy(true); setError('');
    try {
      if (isEdit) {
        await editProjectPermission(name, username, role);
      } else {
        await addProjectPermission(name, username, role);
      }
      onClose(true);
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  return (
    <div className="modal fade show d-block" tabIndex="-1"
         style={{ backgroundColor: 'rgba(0,0,0,.4)' }}>
      <div className="modal-dialog modal-dialog-centered">
        <div className="modal-content">
          <div className="modal-header">
            <h5 className="modal-title">{isEdit ? 'Edit Project Permission' : 'Add Project Permission'}</h5>
            <button className="btn-close" onClick={() => onClose(false)} disabled={busy} />
          </div>
          <div className="modal-body">
            {error && <div className="alert alert-danger py-2">{error}</div>}

            <div className="mb-3">
              <label className="form-label fw-semibold">Username</label>
              {isEdit
                ? <div className="form-control-plaintext fw-semibold">{username}</div>
                : (
                  <>
                    <input className="form-control" value={username} autoFocus
                           placeholder="Search user…"
                           onChange={e => setUsername(e.target.value)} />
                    {candidates.length > 0 && (
                      <ul className="list-group mt-1" style={{ fontSize: 13, maxHeight: 180, overflowY: 'auto' }}>
                        {candidates.map(u => (
                          <li key={u.username}
                              className="list-group-item list-group-item-action py-1"
                              style={{ cursor: 'pointer' }}
                              onClick={() => { setUsername(u.username); setCandidates([]); }}>
                            {u.username}
                          </li>
                        ))}
                      </ul>
                    )}
                  </>
                )}
            </div>

            <div>
              <label className="form-label fw-semibold">Role</label>
              <select className="form-select" value={role} onChange={e => setRole(e.target.value)}>
                {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
              </select>
            </div>
          </div>
          <div className="modal-footer">
            <button className="btn btn-secondary" onClick={() => onClose(false)} disabled={busy}>Cancel</button>
            <button className="btn btn-primary" onClick={handleSave}
                    disabled={busy || !!usernameError}>
              {busy && <span className="spinner-border spinner-border-sm me-2" />}Ok
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function PermissionsTab({ name }) {
  const [items,      setItems]      = useState([]);
  const [total,      setTotal]      = useState(null);
  const [error,      setError]      = useState('');
  const [page,       setPage]       = useState(1);
  const [filterName, setFilterName] = useState('');
  const [filterRole, setFilterRole] = useState('');
  const [modal,      setModal]      = useState(null);

  const load = useCallback(async (pg = page) => {
    setError(''); setTotal(null);
    try {
      const data = await fetchProjectPermissions(name, { q: filterName, role: filterRole, page: pg, page_size: PAGE_SIZE });
      setItems(data.results ?? []);
      setTotal(data.total_result_count ?? 0);
    } catch (e) { setError(e.message); setTotal(-1); }
  }, [name, page, filterName, filterRole]);

  useEffect(() => { load(page); }, [page]);

  const prevRef = useRef({ filterName, filterRole });
  useEffect(() => {
    const p = prevRef.current;
    if (p.filterName !== filterName || p.filterRole !== filterRole) {
      prevRef.current = { filterName, filterRole };
      setPage(1); load(1);
    }
  }, [filterName, filterRole]);

  function closeModal(reload) { setModal(null); if (reload) load(page); }

  return (
    <>
      {modal?.type === 'add' && (
        <PermissionModal name={name} onClose={closeModal} />
      )}
      {modal?.type === 'edit' && (
        <PermissionModal name={name} permission={modal.item} onClose={closeModal} />
      )}
      {modal?.type === 'delete' && (
        <ConfirmModal
          title="Remove Permission"
          body={<>Remove permission for <strong>{modal.item.username}</strong>?</>}
          onConfirm={() => deleteProjectPermission(name, modal.item.username)}
          onClose={closeModal}
        />
      )}

      <div>
        <table className="table table-sm table-hover align-middle mb-0" style={{ fontSize: 13 }}>
          <thead>
            <tr>
              <th style={{ ...TH, minWidth: 200 }}>
                <input className="form-control form-control-sm bg-transparent border-0 text-white"
                       placeholder="Username" value={filterName}
                       onChange={e => setFilterName(e.target.value)} style={{ minWidth: 160 }} />
              </th>
              <th style={{ ...TH, minWidth: 160 }}>
                <input className="form-control form-control-sm bg-transparent border-0 text-white"
                       placeholder="Role" value={filterRole}
                       onChange={e => setFilterRole(e.target.value)} style={{ minWidth: 120 }} />
              </th>
              <th style={{ ...TH, textAlign: 'right' }}>
                <button className="btn btn-sm border-0 p-0"
                        style={{ color: 'white', fontSize: 20, lineHeight: 1 }}
                        title="Add permission" onClick={() => setModal({ type: 'add' })}>⊕</button>
              </th>
            </tr>
          </thead>
          <tbody>
            {total === null && (
              <tr><td colSpan={3} className="text-center py-3 text-muted">Loading…</td></tr>
            )}
            {total === -1 && (
              <tr><td colSpan={3} className="text-center py-3 text-danger">Unable to load data ({error})</td></tr>
            )}
            {total === 0 && (
              <tr><td colSpan={3} className="text-center py-3 text-muted">No entries found</td></tr>
            )}
            {items.map(item => (
              <tr key={item.id ?? item.username}>
                <td><strong>{item.username}</strong></td>
                <td>{item.role}</td>
                <td className="text-end">
                  <div className="dropdown">
                    <button className="btn btn-sm btn-link p-0 text-secondary" data-bs-toggle="dropdown">
                      <i className="bi bi-three-dots-vertical" />
                    </button>
                    <ul className="dropdown-menu dropdown-menu-end">
                      <li><button className="dropdown-item" onClick={() => setModal({ type: 'edit', item })}>
                        <i className="bi bi-pencil me-2" />Edit
                      </button></li>
                      <li><button className="dropdown-item text-danger" onClick={() => setModal({ type: 'delete', item })}>
                        <i className="bi bi-trash me-2" />Delete
                      </button></li>
                    </ul>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <PaginationBar page={page} total={total ?? 0} pageSize={PAGE_SIZE} onChange={setPage} />
    </>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Tab: Tokens
// ─────────────────────────────────────────────────────────────────────────────

function ProjectTokenModal({ name, onClose }) {
  const [tokenType,   setTokenType]   = useState('new');   // 'new' | 'existing'
  const [description, setDescription] = useState('');
  const [token,       setToken]       = useState('');      // revealed token (new flow)
  const [suggestions, setSuggestions] = useState([]);      // existing token autocomplete
  const [busy,        setBusy]        = useState(false);
  const [error,       setError]       = useState('');

  // fetch user tokens for autocomplete (existing flow)
  useEffect(() => {
    if (tokenType !== 'existing' || description.length < 1) { setSuggestions([]); return; }
    fetch(apiUrl(`/api2/tokens?description=${encodeURIComponent(description)}&page_size=10`),
          { credentials: 'same-origin' })
      .then(r => r.ok ? r.json() : { results: [] })
      .then(d => setSuggestions(d.results ?? []))
      .catch(() => {});
  }, [description, tokenType]);

  const descError = rules.required(description, 2, 'Description');

  async function handleCreate() {
    if (descError) return;
    setBusy(true); setError('');
    try {
      const data = await createProjectToken(name, description.trim());
      setToken(data.token ?? '');
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  async function handleSave() {
    if (tokenType === 'new' && token.length === 0) return;
    if (tokenType === 'existing' && !description.trim()) return;
    setBusy(true); setError('');
    try {
      if (tokenType === 'existing') {
        await linkProjectToken(name, description.trim());
      }
      onClose(true);
    } catch (e) { setError(e.message); setBusy(false); }
  }

  const created = token.length > 0;

  return (
    <div className="modal fade show d-block" tabIndex="-1"
         style={{ backgroundColor: 'rgba(0,0,0,.4)' }}>
      <div className="modal-dialog modal-dialog-centered">
        <div className="modal-content">
          <div className="modal-header">
            <h5 className="modal-title">Add Authentication Token</h5>
            <button className="btn-close" onClick={() => onClose(false)} disabled={busy} />
          </div>
          <div className="modal-body">
            {error && <div className="alert alert-danger py-2">{error}</div>}

            {/* Type selector */}
            <div className="d-flex gap-4 mb-3">
              {['new', 'existing'].map(t => (
                <div className="form-check" key={t}>
                  <input className="form-check-input" type="radio" id={`tt-${t}`}
                         checked={tokenType === t} onChange={() => { setTokenType(t); setDescription(''); setToken(''); }} />
                  <label className="form-check-label" htmlFor={`tt-${t}`}>
                    {t === 'new' ? 'Create new token' : 'Use existing token'}
                  </label>
                </div>
              ))}
            </div>

            {/* New token flow */}
            {tokenType === 'new' && (
              <>
                <label className="form-label fw-semibold">Description</label>
                <div className="d-flex gap-2 mb-3">
                  <input className="form-control" value={description} autoFocus readOnly={created}
                         placeholder="e.g. CI pipeline key"
                         onChange={e => setDescription(e.target.value)}
                         onKeyDown={e => e.key === 'Enter' && !created && handleCreate()} />
                  <button className="btn btn-primary" onClick={handleCreate}
                          disabled={busy || created || !!descError}>
                    {busy ? <span className="spinner-border spinner-border-sm" /> : 'Create'}
                  </button>
                </div>
                <label className="form-label fw-semibold">Token</label>
                <input className="form-control font-monospace mb-1" value={token} readOnly
                       placeholder="— generated after clicking Create —" style={{ fontSize: 13 }} />
                {created && (
                  <div className="text-muted" style={{ fontSize: 12 }}>
                    <i className="bi bi-exclamation-triangle me-1 text-warning" />
                    Note: the token cannot be displayed again once this dialog is closed.
                  </div>
                )}
              </>
            )}

            {/* Existing token flow */}
            {tokenType === 'existing' && (
              <>
                <label className="form-label fw-semibold">Description</label>
                <input className="form-control" value={description} autoFocus
                       placeholder="Search existing token description…"
                       onChange={e => setDescription(e.target.value)} />
                {suggestions.length > 0 && (
                  <ul className="list-group mt-1" style={{ fontSize: 13, maxHeight: 160, overflowY: 'auto' }}>
                    {suggestions.map(s => (
                      <li key={s.id} className="list-group-item list-group-item-action py-1"
                          style={{ cursor: 'pointer' }}
                          onClick={() => { setDescription(s.description); setSuggestions([]); }}>
                        {s.description}
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </div>
          <div className="modal-footer">
            <button className="btn btn-secondary" onClick={() => onClose(created || false)} disabled={busy}>
              {created ? 'Close' : 'Cancel'}
            </button>
            {tokenType === 'existing' && (
              <button className="btn btn-primary" onClick={handleSave}
                      disabled={busy || !!descError}>
                {busy && <span className="spinner-border spinner-border-sm me-2" />}Ok
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function TokensTab({ name }) {
  const [items,  setItems]  = useState([]);
  const [total,  setTotal]  = useState(null);
  const [error,  setError]  = useState('');
  const [page,   setPage]   = useState(1);
  const [filter, setFilter] = useState('');
  const [modal,  setModal]  = useState(null);

  const load = useCallback(async (pg = page) => {
    setError(''); setTotal(null);
    try {
      const data = await fetchProjectTokens(name, { q: filter, page: pg, page_size: PAGE_SIZE });
      setItems(data.results ?? []);
      setTotal(data.total_result_count ?? 0);
    } catch (e) { setError(e.message); setTotal(-1); }
  }, [name, page, filter]);

  useEffect(() => { load(page); }, [page]);

  const prevFilter = useRef(filter);
  useEffect(() => {
    if (prevFilter.current !== filter) {
      prevFilter.current = filter;
      setPage(1); load(1);
    }
  }, [filter]);

  function closeModal(reload) { setModal(null); if (reload) load(page); }

  return (
    <>
      {modal?.type === 'add' && <ProjectTokenModal name={name} onClose={closeModal} />}
      {modal?.type === 'delete' && (
        <ConfirmModal
          title="Delete Token"
          body="The token will be removed from this project. This operation cannot be undone."
          onConfirm={() => deleteProjectToken(name, modal.item.id)}
          onClose={closeModal}
        />
      )}

      <div>
        <table className="table table-sm table-hover align-middle mb-0" style={{ fontSize: 13 }}>
          <thead>
            <tr>
              <th style={{ ...TH, minWidth: 260 }}>
                <input className="form-control form-control-sm bg-transparent border-0 text-white"
                       placeholder="Description" value={filter}
                       onChange={e => setFilter(e.target.value)} style={{ minWidth: 200 }} />
              </th>
              <th style={{ ...TH, textAlign: 'right' }}>
                <button className="btn btn-sm border-0 p-0"
                        style={{ color: 'white', fontSize: 20, lineHeight: 1 }}
                        title="Add token" onClick={() => setModal({ type: 'add' })}>⊕</button>
              </th>
            </tr>
          </thead>
          <tbody>
            {total === null && (
              <tr><td colSpan={2} className="text-center py-3 text-muted">Loading…</td></tr>
            )}
            {total === -1 && (
              <tr><td colSpan={2} className="text-center py-3 text-danger">Unable to load data ({error})</td></tr>
            )}
            {total === 0 && (
              <tr><td colSpan={2} className="text-center py-3 text-muted">No entries found</td></tr>
            )}
            {items.map(t => (
              <tr key={t.id}>
                <td><strong>{t.description}</strong></td>
                <td className="text-end">
                  <div className="dropdown">
                    <button className="btn btn-sm btn-link p-0 text-secondary" data-bs-toggle="dropdown">
                      <i className="bi bi-three-dots-vertical" />
                    </button>
                    <ul className="dropdown-menu dropdown-menu-end">
                      <li><button className="dropdown-item text-danger"
                                  onClick={() => setModal({ type: 'delete', item: t })}>
                        <i className="bi bi-trash me-2" />Delete
                      </button></li>
                    </ul>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <PaginationBar page={page} total={total ?? 0} pageSize={PAGE_SIZE} onChange={setPage} />
    </>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Root
// ─────────────────────────────────────────────────────────────────────────────
export default function ProjectDetailPage() {
  const { name }   = useParams();
  const navigate   = useNavigate();
  const location   = useLocation();

  const [project, setProject] = useState(null);
  const [error,   setError]   = useState('');
  const [modal,   setModal]   = useState(null);

  useEffect(() => {
    fetchProject(name)
      .then(setProject)
      .catch(e => setError(e.message));
  }, [name]);

  function closeProjectModal(reload) {
    setModal(null);
    if (reload) fetchProject(name).then(setProject).catch(() => {});
  }

  const base = `/project/${name}`;

  return (
    <div className="p-3">

      {/* ── Project-level modals ── */}
      {modal?.type === 'editProject' && (
        <ProjectForm project={project} onClose={closeProjectModal} />
      )}
      {modal?.type === 'deleteProject' && (
        <ConfirmModal
          title="Delete Project"
          body="The project will be deleted if no project versions exist. This operation cannot be undone."
          onConfirm={() => deleteProject(project.name)}
          onClose={reload => { setModal(null); if (reload) navigate('/projects'); }}
        />
      )}

      {/* ── Project header ── */}
      {error && <div className="alert alert-danger py-2">{error}</div>}
      <div className="d-flex align-items-center mb-2 gap-2">
        <h1 className="mb-0 d-flex align-items-center gap-2" style={{ fontSize: 24, fontWeight: 500 }}>
          <i className="bi bi-collection" />
          Project {project?.name ?? name}
        </h1>
        {project?.description && (
          <span className="text-muted ms-2" style={{ fontSize: 14 }}>{project.description}</span>
        )}
        <div className="ms-auto dropdown">
          <button className="btn btn-sm btn-outline-secondary" data-bs-toggle="dropdown">
            <i className="bi bi-three-dots-vertical" />
          </button>
          <ul className="dropdown-menu dropdown-menu-end">
            <li>
              <button className="dropdown-item" onClick={() => setModal({ type: 'editProject' })}>
                <i className="bi bi-pencil me-2" />Edit
              </button>
            </li>
            <li>
              <button className="dropdown-item text-danger" onClick={() => setModal({ type: 'deleteProject' })}>
                <i className="bi bi-trash me-2" />Delete
              </button>
            </li>
          </ul>
        </div>
      </div>

      {/* ── Tab bar ── */}
      <ul className="nav nav-tabs mb-3">
        {[
          { label: 'Versions',     path: `${base}/versions` },
          { label: 'Permissions',  path: `${base}/permissions` },
          { label: 'Tokens',       path: `${base}/tokens` },
        ].map(({ label, path }) => (
          <li className="nav-item" key={path}>
            <NavLink className={({ isActive }) => `nav-link${isActive ? ' active' : ' text-muted'}`}
                     to={path}>{label}</NavLink>
          </li>
        ))}
      </ul>

      {/* ── Tab content driven by URL, no nested Routes needed ── */}
      {location.pathname.endsWith('/permissions') ? <PermissionsTab name={name} /> :
       location.pathname.endsWith('/tokens')      ? <TokensTab      name={name} /> :
       <VersionsTab name={name} project={project} />}
    </div>
  );
}
