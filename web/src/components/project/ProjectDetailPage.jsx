/**
 * ProjectDetailPage — port of ProjectInfoComponent + project-info.html.
 *
 * Route: /project/:name  (and /project/:name/versions)
 *
 * Shows:
 *  • Project header with Edit / Delete menu
 *  • Tab bar: Versions | Permissions | Tokens  (only Versions implemented here)
 *  • Paginated table of project versions with all columns and actions
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import {
  fetchProject,
  fetchProjectVersions,
  deleteProjectVersion,
  lockProjectVersion,
  exportProjectVersion,
  importProjectVersion,
} from '../../api/projectversions';
import { deleteProject } from '../../api/projects';
import ProjectForm from './ProjectForm';
import ProjectVersionForm from './ProjectVersionForm';
import ConfirmModal from '../build/ConfirmModal';

const PRIMARY  = '#571845';
const TH       = { backgroundColor: PRIMARY, color: 'white' };
const PAGE_SIZE = 25;

// ─── tiny import helper (hidden file input) ──────────────────────────────────
function useImportInput(onImport) {
  const ref = useRef(null);
  function trigger() { ref.current?.click(); }
  function handleChange(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    onImport(file);
    e.target.value = '';       // reset so same file can be picked again
  }
  const input = (
    <input ref={ref} type="file" accept=".json"
           style={{ display: 'none' }} onChange={handleChange} />
  );
  return { trigger, input };
}

// ─── simple one-field text modal ─────────────────────────────────────────────
function TextInputModal({ title, label, placeholder, onConfirm, onClose }) {
  const [value, setValue] = useState('');
  const [busy, setBusy]   = useState(false);
  const [error, setError] = useState('');

  async function handleOk() {
    if (!value.trim()) return;
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
            <input className="form-control" value={value} autoFocus
                   placeholder={placeholder}
                   onChange={e => setValue(e.target.value)}
                   onKeyDown={e => e.key === 'Enter' && handleOk()} />
          </div>
          <div className="modal-footer">
            <button className="btn btn-secondary" onClick={() => onClose(false)} disabled={busy}>Cancel</button>
            <button className="btn btn-primary" onClick={handleOk} disabled={busy || !value.trim()}>
              {busy && <span className="spinner-border spinner-border-sm me-2" />}Ok
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
export default function ProjectDetailPage() {
  const { name } = useParams();
  const navigate  = useNavigate();

  const [project, setProject]   = useState(null);
  const [versions, setVersions] = useState([]);
  const [total, setTotal]       = useState(null);
  const [error, setError]       = useState('');
  const [page, setPage]         = useState(1);
  const [filterName, setFilterName] = useState('');

  // modal: { type, pv? }
  const [modal, setModal] = useState(null);

  // ── load project meta ────────────────────────────────────────────────────
  useEffect(() => {
    fetchProject(name)
      .then(setProject)
      .catch(e => setError(e.message));
  }, [name]);

  // ── load versions ────────────────────────────────────────────────────────
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

  // ── export ───────────────────────────────────────────────────────────────
  async function handleExport(pv) {
    try {
      const data = await exportProjectVersion(pv.project_name, pv.name);
      const filename = `${data.project_name}_${data.name}.projectversion_export.json`;
      const blob = new Blob([JSON.stringify(data)], { type: 'application/json' });
      const url  = URL.createObjectURL(blob);
      const a    = Object.assign(document.createElement('a'), { href: url, download: filename, style: 'display:none' });
      document.body.appendChild(a); a.click();
      document.body.removeChild(a); URL.revokeObjectURL(url);
    } catch (e) { alert(`Export failed: ${e.message}`); }
  }

  // ── import ───────────────────────────────────────────────────────────────
  const { trigger: triggerImport, input: importInput } = useImportInput(async (file) => {
    try {
      const fd = new FormData();
      fd.append('file', file);
      const result = await importProjectVersion(fd);
      const pv     = result.projectversion;
      navigate(`/project/${project.name}/${pv.name}`);
    } catch (e) { alert(`Import failed: ${e.message}`); }
  });

  // ── pagination ────────────────────────────────────────────────────────────
  const totalPages = total > 0 ? Math.ceil(total / PAGE_SIZE) : 1;

  function handleWheel(e) {
    if (e.ctrlKey) return;
    if (e.deltaY > 0 && page < totalPages) setPage(p => p + 1);
    else if (e.deltaY < 0 && page > 1)    setPage(p => p - 1);
  }

  // ── render ────────────────────────────────────────────────────────────────
  return (
    <div className="p-3" onWheel={handleWheel}>

      {importInput}

      {/* ── Modals ── */}
      {modal?.type === 'editProject' && (
        <ProjectForm project={project} onClose={reload => {
          if (reload) fetchProject(name).then(setProject).catch(() => {});
          setModal(null);
        }} />
      )}
      {modal?.type === 'deleteProject' && (
        <ConfirmModal
          title="Delete Project"
          body="The project will be deleted if no project versions exist. This operation cannot be undone."
          onConfirm={() => deleteProject(project.name)}
          onClose={reload => { setModal(null); if (reload) navigate('/projects'); }}
        />
      )}
      {modal?.type === 'create' && (
        <ProjectVersionForm projectName={name} onClose={closeModal} />
      )}
      {modal?.type === 'edit' && (
        <ProjectVersionForm projectName={name} projectVersion={modal.pv} onClose={closeModal} />
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
        <TextInputModal
          title="Create Overlay"
          label="Overlay name"
          placeholder="overlay-name"
          onConfirm={async (overlayName) => {
            const res = await fetch(
              `/api2/project/${modal.pv.project_name}/${modal.pv.name}/overlay`,
              { method: 'POST', credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: overlayName }) }
            );
            if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
            const data = await res.json();
            navigate(`/project/${name}/${data.name}`);
          }}
          onClose={closeModal}
        />
      )}
      {modal?.type === 'snapshot' && (
        <TextInputModal
          title="Create Release Snapshot"
          label="Snapshot name"
          placeholder="snapshot-name"
          onConfirm={async (snapName) => {
            const res = await fetch(
              `/api2/project/${modal.pv.project_name}/${modal.pv.name}/snapshot`,
              { method: 'POST', credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: snapName }) }
            );
            if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
            const data = await res.json();
            navigate(`/project/${name}/${data.name}`);
          }}
          onClose={closeModal}
        />
      )}

      {/* ── Project header ── */}
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
        <li className="nav-item">
          <span className="nav-link active" style={{ cursor: 'default' }}>Versions</span>
        </li>
        <li className="nav-item">
          <Link className="nav-link text-muted" to={`/project/${name}/permissions`}>Permissions</Link>
        </li>
        <li className="nav-item">
          <Link className="nav-link text-muted" to={`/project/${name}/tokens`}>Tokens</Link>
        </li>
      </ul>

      {/* ── Versions table ── */}
      <div>
        <table className="table table-sm table-hover align-middle mb-0" style={{ fontSize: 13 }}>
          <thead>
            <tr>
              {/* Version / filter */}
              <th style={{ ...TH, minWidth: 180 }}>
                <input
                  className="form-control form-control-sm bg-transparent border-0 text-white"
                  placeholder="Version"
                  value={filterName}
                  onChange={e => setFilterName(e.target.value)}
                  style={{ minWidth: 140 }}
                />
              </th>
              <th style={{ ...TH, textAlign: 'center', whiteSpace: 'nowrap' }}># Builds</th>
              <th style={{ ...TH, textAlign: 'center', whiteSpace: 'nowrap' }}># CI Builds</th>
              <th style={{ ...TH, whiteSpace: 'nowrap' }}>Architectures</th>
              <th style={{ ...TH, whiteSpace: 'nowrap' }}>Base Mirror</th>
              <th style={{ ...TH, textAlign: 'center', whiteSpace: 'nowrap' }}>Locked</th>
              <th style={{ ...TH, textAlign: 'center', whiteSpace: 'nowrap' }}>CI Builds</th>
              <th style={{ ...TH, width: '40%' }}>Description</th>
              {/* Create / Import button */}
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
              <tr><td colSpan={9} className="text-center py-3 text-danger">
                Unable to load data ({error})
              </td></tr>
            )}
            {total === 0 && (
              <tr><td colSpan={9} className="text-center py-3 text-muted">No entries found</td></tr>
            )}

            {versions.map(pv => (
              <tr key={pv.id} style={{ cursor: 'pointer' }}
                onClick={() => navigate(`/project/${name}/${pv.name}`)}>

                <td><strong>{pv.name}</strong></td>

                <td className="text-center">{pv.buildCount > 0 ? pv.buildCount : ''}</td>
                <td className="text-center">{pv.cibuildCount > 0 ? pv.cibuildCount : ''}</td>

                <td>{(pv.architectures ?? []).join(', ')}</td>

                <td>
                  {pv.basemirror && (
                    <span
                      style={{ cursor: 'pointer', color: 'inherit' }}
                      onClick={e => {
                        e.stopPropagation();
                        const [mName, mVer] = pv.basemirror.split('/');
                        navigate(`/mirror/${mName}/${mVer}`);
                      }}
                    >
                      {pv.basemirror}
                    </span>
                  )}
                </td>

                <td className="text-center">
                  <i className={`bi ${pv.is_locked ? 'bi-lock-fill' : 'bi-dash'}`} />
                </td>

                <td className="text-center">
                  <i className={`bi ${pv.ci_builds_enabled ? 'bi-check-lg' : 'bi-dash'}`} />
                </td>

                <td className="text-muted">{pv.description}</td>

                {/* Actions */}
                <td className="text-end" onClick={e => e.stopPropagation()}>
                  <div className="dropdown">
                    <button className="btn btn-sm btn-link p-0 text-secondary"
                      data-bs-toggle="dropdown">
                      <i className="bi bi-three-dots-vertical" />
                    </button>
                    <ul className="dropdown-menu dropdown-menu-end">
                      <li>
                        <button className="dropdown-item"
                          onClick={() => navigate(`/project/${name}/${pv.name}`)}>
                          <i className="bi bi-list me-2" />Details
                        </button>
                      </li>
                      <li>
                        <button className="dropdown-item"
                          onClick={() => setModal({ type: 'edit', pv })}>
                          <i className="bi bi-pencil me-2" />Edit
                        </button>
                      </li>
                      <li>
                        <button className="dropdown-item"
                          onClick={() => setModal({ type: 'copy', pv })}>
                          <i className="bi bi-copy me-2" />Copy
                        </button>
                      </li>
                      <li>
                        <button className="dropdown-item"
                          onClick={() => setModal({ type: 'overlay', pv })}>
                          <i className="bi bi-layers me-2" />Create Overlay
                        </button>
                      </li>
                      <li>
                        <button className="dropdown-item"
                          onClick={() => setModal({ type: 'snapshot', pv })}>
                          <i className="bi bi-camera me-2" />Create Release Snapshot
                        </button>
                      </li>
                      {!pv.is_locked && (
                        <li>
                          <button className="dropdown-item"
                            onClick={() => setModal({ type: 'lock', pv })}>
                            <i className="bi bi-lock me-2" />Lock
                          </button>
                        </li>
                      )}
                      <li>
                        <button className="dropdown-item"
                          onClick={() => handleExport(pv)}>
                          <i className="bi bi-download me-2" />Export Project Version
                        </button>
                      </li>
                      <li>
                        <button className="dropdown-item text-danger"
                          onClick={() => setModal({ type: 'delete', pv })}>
                          <i className="bi bi-trash me-2" />Delete
                        </button>
                      </li>
                    </ul>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* ── Pagination ── */}
      <div className="d-flex justify-content-between align-items-center mt-2 px-1" style={{ fontSize: 13 }}>
        <span className="text-muted">
          {total > 0
            ? `${(page - 1) * PAGE_SIZE + 1}–${Math.min(page * PAGE_SIZE, total)} of ${total}`
            : ''}
        </span>
        <nav>
          <ul className="pagination pagination-sm mb-0">
            <li className={`page-item ${page <= 1 ? 'disabled' : ''}`}>
              <button className="page-link" onClick={() => setPage(1)}>&laquo;</button>
            </li>
            <li className={`page-item ${page <= 1 ? 'disabled' : ''}`}>
              <button className="page-link" onClick={() => setPage(p => p - 1)}>&lsaquo;</button>
            </li>
            <li className="page-item disabled">
              <span className="page-link">{page} / {totalPages}</span>
            </li>
            <li className={`page-item ${page >= totalPages ? 'disabled' : ''}`}>
              <button className="page-link" onClick={() => setPage(p => p + 1)}>&rsaquo;</button>
            </li>
            <li className={`page-item ${page >= totalPages ? 'disabled' : ''}`}>
              <button className="page-link" onClick={() => setPage(totalPages)}>&raquo;</button>
            </li>
          </ul>
        </nav>
      </div>
    </div>
  );
}
