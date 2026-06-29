/**
 * RepoDetailPage — port of RepositoryInfoComponent + repo-info.html
 *                  and RepositoryBuildsComponent + repo-builds.html.
 *
 * Route: /repo/:id/*
 * Tabs:  Dependent Projects | Dependent Builds
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate, NavLink, Routes, Route, Navigate } from 'react-router-dom';
import {
  fetchRepo, fetchRepoDependents,
  editRepoUrl, deleteRepo, buildRepo, recloneRepo, mergeRepo, triggerBuild,
  fetchRepoDependentProjectVersions,
} from '../../api/repos';
import BuildTable from '../build/BuildTable';
import ConfirmModal from '../build/ConfirmModal';
import { rules, fieldClass, fieldError } from '../../lib/validate';

const PRIMARY  = '#571845';
const TH       = { backgroundColor: PRIMARY, color: 'white' };
const PAGE_SIZE = 20;

// ── SSH → HTTPS URL transform ─────────────────────────────────────────────
function transformUrl(url) {
  const m = url?.match(/^git@ssh\.code\.roche\.com:(.+)\/(.+)\.git$/);
  return m ? `https://code.roche.com/${m[1]}/${m[2]}` : url;
}

// ── State icon ────────────────────────────────────────────────────────────
function stateIcon(state) {
  switch (state) {
    case 'ready': return 'bi-check-lg text-success';
    case 'busy':  return 'bi-arrow-repeat rotating text-primary';
    case 'error': return 'bi-x-lg text-danger';
    default:      return 'bi-three-dots text-muted';
  }
}

// ── Edit URL modal ────────────────────────────────────────────────────────
function EditUrlModal({ repo, onClose }) {
  const [url,     setUrl]     = useState(repo.url);
  const [touched, setTouched] = useState(false);
  const [error,   setError]   = useState('');
  const [saving,  setSaving]  = useState(false);

  const urlError = rules.gitUrl(url);

  async function save() {
    if (urlError) { setTouched(true); return; }
    setSaving(true); setError('');
    try {
      await editRepoUrl(repo.id, url.trim());
      onClose(true);
    } catch (e) { setError(e.message); setSaving(false); }
  }

  return (
    <div className="modal d-block" style={{ backgroundColor: 'rgba(0,0,0,.4)' }}>
      <div className="modal-dialog">
        <div className="modal-content">
          <div className="modal-header">
            <h5 className="modal-title"><i className="bi bi-git me-2" />Edit git repository</h5>
            <button className="btn-close" onClick={() => onClose(false)} />
          </div>
          <div className="modal-body">
            {error && <div className="alert alert-danger py-1">{error}</div>}
            <label className="form-label fw-bold">git Repository URL</label>
            <input
              className={fieldClass(touched && urlError)}
              value={url}
              onChange={e => setUrl(e.target.value)}
              onBlur={() => setTouched(true)}
              autoFocus
            />
            {touched && urlError && <div className="invalid-feedback">{urlError}</div>}
          </div>
          <div className="modal-footer">
            <button className="btn btn-secondary" onClick={() => onClose(false)} disabled={saving}>Cancel</button>
            <button className="btn btn-primary" onClick={save} disabled={saving || !!urlError}>Save</button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Merge Duplicate modal ─────────────────────────────────────────────────
function MergeModal({ repo, onClose }) {
  const navigate = useNavigate();
  const [originalUrl, setOriginalUrl] = useState('');
  const [matches, setMatches]         = useState([]);
  const [error, setError]             = useState('');
  const [saving, setSaving]           = useState(false);

  useEffect(() => {
    if (!originalUrl.trim()) { setMatches([]); return; }
    const params = new URLSearchParams({ filter_url: originalUrl, page: 1, page_size: 25 });
    fetch(`/api2/repositories?${params}`, { credentials: 'same-origin' })
      .then(r => r.json())
      .then(d => setMatches((d.results ?? []).filter(r => r.url !== repo.url)))
      .catch(() => {});
  }, [originalUrl]);

  async function save() {
    const original = matches.find(r => r.url === originalUrl);
    if (!original) return;
    setSaving(true); setError('');
    try {
      await mergeRepo(original.id, repo.id);
      onClose(true);
      navigate('/repos');
    } catch (e) { setError(e.message); setSaving(false); }
  }

  const matched = matches.find(r => r.url === originalUrl);

  return (
    <div className="modal d-block" style={{ backgroundColor: 'rgba(0,0,0,.4)' }}>
      <div className="modal-dialog">
        <div className="modal-content">
          <div className="modal-header">
            <h5 className="modal-title"><i className="bi bi-git me-2" />Merge Duplicate</h5>
            <button className="btn-close" onClick={() => onClose(false)} />
          </div>
          <div className="modal-body">
            {error && <div className="alert alert-danger py-1">{error}</div>}
            <p className="mb-1">Merging <strong>{repo.name}</strong> into an existing repository.</p>
            <label className="form-label fw-bold">Original Repository URL</label>
            <input
              className="form-control"
              placeholder="Type to search…"
              value={originalUrl}
              onChange={e => setOriginalUrl(e.target.value)}
              list="merge-matches"
              autoFocus
            />
            <datalist id="merge-matches">
              {matches.map(r => <option key={r.id} value={r.url} />)}
            </datalist>
          </div>
          <div className="modal-footer">
            <button className="btn btn-secondary" onClick={() => onClose(false)} disabled={saving}>Cancel</button>
            <button className="btn btn-primary" onClick={save} disabled={saving || !matched}>Merge</button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Trigger Build modal ───────────────────────────────────────────────────
function TriggerModal({ repo, onClose }) {
  const [gitref, setGitref]           = useState('');
  const [pvs, setPvs]                 = useState([]);
  const [selectedPvs, setSelectedPvs] = useState([]);
  const [forceCI, setForceCI]         = useState(false);
  const [error, setError]             = useState('');
  const [saving, setSaving]           = useState(false);

  useEffect(() => {
    fetchRepoDependentProjectVersions(repo.id, { unlocked: true })
      .then(d => setPvs((d.results ?? []).map(r => `${r.project_name}/${r.name}`)))
      .catch(() => {});
  }, [repo.id]);

  function togglePv(pv) {
    setSelectedPvs(prev => prev.includes(pv) ? prev.filter(p => p !== pv) : [...prev, pv]);
  }

  async function save() {
    if (!gitref.trim()) return;
    setSaving(true); setError('');
    try {
      await triggerBuild(repo.url, gitref.trim(), selectedPvs, forceCI);
      onClose(true);
    } catch (e) { setError(e.message); setSaving(false); }
  }

  return (
    <div className="modal d-block" style={{ backgroundColor: 'rgba(0,0,0,.4)' }}>
      <div className="modal-dialog modal-lg">
        <div className="modal-content">
          <div className="modal-header">
            <h5 className="modal-title"><i className="bi bi-git me-2" />Trigger Build</h5>
            <button className="btn-close" onClick={() => onClose(false)} />
          </div>
          <div className="modal-body">
            {error && <div className="alert alert-danger py-1">{error}</div>}
            <p>Trigger a build for <code>{repo.url}</code></p>
            <div className="mb-3">
              <label className="form-label fw-bold">Git Reference</label>
              <p className="text-muted small mb-1">Specify git tag, branch or commit hash to build:</p>
              <input
                className="form-control"
                placeholder="e.g. main, v1.2.3, abc1234"
                value={gitref}
                onChange={e => setGitref(e.target.value)}
                autoFocus
              />
            </div>
            {pvs.length > 0 && (
              <div className="mb-3">
                <label className="form-label fw-bold">Project Versions</label>
                <p className="text-muted small mb-1">Select project versions to build for (leave empty to use debian/molior.yml):</p>
                <div style={{ maxHeight: 160, overflowY: 'auto', border: '1px solid #dee2e6', borderRadius: 4, padding: '4px 8px' }}>
                  {pvs.map(pv => (
                    <div key={pv} className="form-check">
                      <input
                        className="form-check-input" type="checkbox" id={`pv-${pv}`}
                        checked={selectedPvs.includes(pv)}
                        onChange={() => togglePv(pv)}
                      />
                      <label className="form-check-label" htmlFor={`pv-${pv}`}>{pv}</label>
                    </div>
                  ))}
                </div>
              </div>
            )}
            <div className="form-check">
              <input
                className="form-check-input" type="checkbox" id="force-ci"
                checked={forceCI}
                onChange={e => setForceCI(e.target.checked)}
              />
              <label className="form-check-label" htmlFor="force-ci">
                Force CI build even on version tags
              </label>
            </div>
          </div>
          <div className="modal-footer">
            <button className="btn btn-secondary" onClick={() => onClose(false)} disabled={saving}>Cancel</button>
            <button className="btn btn-primary" onClick={save} disabled={saving || !gitref.trim()}>Trigger</button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Tab: Dependent Projects ───────────────────────────────────────────────
function DependentsTab({ repoId }) {
  const navigate = useNavigate();

  const [items, setItems]   = useState([]);
  const [total, setTotal]   = useState(null);
  const [error, setError]   = useState('');
  const [page, setPage]     = useState(1);
  const [filter, setFilter] = useState('');

  const load = useCallback(async (pg = page) => {
    setError(''); setTotal(null);
    try {
      const data = await fetchRepoDependents(repoId, { q: filter, page: pg, page_size: PAGE_SIZE });
      setItems(data.results ?? []);
      setTotal(data.total_result_count ?? 0);
    } catch (e) { setError(e.message); setTotal(-1); }
  }, [repoId, page, filter]);

  useEffect(() => { load(page); }, [page]);

  const prevFilter = useRef(filter);
  useEffect(() => {
    if (prevFilter.current !== filter) {
      prevFilter.current = filter;
      setPage(1); load(1);
    }
  }, [filter]);

  function depLink(dep) {
    return dep.is_mirror
      ? `/mirror/${dep.project_name}/${dep.name}`
      : `/project/${dep.project_name}/${dep.name}`;
  }

  const totalPages = total > 0 ? Math.ceil(total / PAGE_SIZE) : 1;

  return (
    <div>
      <div>
        <table className="table table-sm table-hover align-middle mb-0" style={{ fontSize: 13 }}>
          <thead>
            <tr>
              <th style={{ ...TH, minWidth: 220 }}>
                <input
                  className="form-control form-control-sm bg-transparent border-0 text-white"
                  placeholder="Dependent"
                  value={filter}
                  onChange={e => setFilter(e.target.value)}
                  style={{ minWidth: 180 }}
                />
              </th>
              <th style={TH}>Architectures</th>
              <th style={TH}>Base Mirror</th>
              <th style={{ ...TH, textAlign: 'center' }}>Locked</th>
              <th style={{ ...TH, width: '100%' }}>Description</th>
              <th style={TH} />
            </tr>
          </thead>
          <tbody>
            {total === null && (
              <tr><td colSpan={6} className="text-center py-3 text-muted">Loading…</td></tr>
            )}
            {total === -1 && (
              <tr><td colSpan={6} className="text-center py-3 text-danger">Unable to load data ({error})</td></tr>
            )}
            {total === 0 && (
              <tr><td colSpan={6} className="text-center py-3 text-muted">No entries found</td></tr>
            )}
            {items.map(dep => (
              <tr key={dep.id} style={{ cursor: 'pointer' }} onClick={() => navigate(depLink(dep))}>
                <td>
                  <strong className="d-flex align-items-center gap-1">
                    <i className={`bi ${dep.is_mirror ? 'bi-folder2-open' : 'bi-collection'}`} />
                    {dep.project_name}/{dep.name}
                  </strong>
                </td>
                <td>{(dep.architectures ?? []).join(', ')}</td>
                <td
                  onClick={e => {
                    e.stopPropagation();
                    if (dep.basemirror) {
                      const [bn, bv] = dep.basemirror.split('/');
                      navigate(`/mirror/${bn}/${bv}`);
                    }
                  }}
                  style={dep.basemirror ? { color: 'darkblue', cursor: 'pointer' } : {}}
                >
                  {dep.basemirror}
                </td>
                <td className="text-center">
                  <i className={`bi ${dep.is_locked ? 'bi-lock-fill' : 'bi-dash'}`} />
                </td>
                <td className="text-muted">{dep.description}</td>
                <td className="text-end" onClick={e => e.stopPropagation()}>
                  <div className="dropdown">
                    <button className="btn btn-sm btn-link p-0 text-secondary" data-bs-toggle="dropdown">
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
            ))}
          </tbody>
        </table>
      </div>

      <div className="d-flex justify-content-between align-items-center mt-2 px-1" style={{ fontSize: 13 }}>
        <span className="text-muted">
          {total > 0 ? `${(page - 1) * PAGE_SIZE + 1}–${Math.min(page * PAGE_SIZE, total)} of ${total}` : ''}
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

// ── Root component ────────────────────────────────────────────────────────
export default function RepoDetailPage() {
  const { id }    = useParams();
  const navigate  = useNavigate();
  const repoId    = Number(id);

  const [repo,      setRepo]      = useState(null);
  const [loadError, setLoadError] = useState('');
  const [modal,     setModal]     = useState(null);

  const base = `/repo/${id}`;

  function loadRepo() {
    fetchRepo(repoId)
      .then(setRepo)
      .catch(e => setLoadError(e.message));
  }

  useEffect(() => { loadRepo(); }, [repoId]);

  function closeModal(didChange) {
    setModal(null);
    if (didChange) loadRepo();
  }

  return (
    <div className="p-3">

      {/* ── Modals ── */}
      {modal?.type === 'edit'    && repo && <EditUrlModal repo={repo} onClose={closeModal} />}
      {modal?.type === 'merge'   && repo && <MergeModal   repo={repo} onClose={closeModal} />}
      {modal?.type === 'trigger' && repo && <TriggerModal  repo={repo} onClose={closeModal} />}
      {modal?.type === 'delete'  && repo && (
        <ConfirmModal
          title="Delete Repository"
          body={<span>The repository <strong>{repo.name}</strong> will be deleted. This operation cannot be undone.</span>}
          onConfirm={() => deleteRepo(repo.id)}
          onClose={didChange => { setModal(null); if (didChange) navigate('/repos'); }}
        />
      )}
      {modal?.type === 'reclone' && repo && (
        <ConfirmModal
          title="Re-clone Source Repository"
          body="The source repository will be re-cloned. Do you want to continue?"
          onConfirm={() => recloneRepo(repo.id)}
          onClose={closeModal}
        />
      )}

      {/* ── Header ── */}
      {loadError && <div className="alert alert-danger py-2">Failed to load repository: {loadError}</div>}

      <div className="d-flex align-items-center mb-1 gap-2">
        <h1 className="mb-0 d-flex align-items-center gap-2" style={{ fontSize: 24, fontWeight: 500 }}>
          <i className="bi bi-git" />
          <NavLink to="/repos" style={{ color: 'inherit', textDecoration: 'none' }}>Repositories</NavLink>
          <span className="text-muted fw-normal">/</span>
          <span>{repo ? repo.name : `#${id}`}</span>
          {repo && (
            <i
              className={`bi ${stateIcon(repo.state)} ms-1`}
              title={repo.state}
              style={{ fontSize: 18 }}
            />
          )}
        </h1>

        {/* Actions menu */}
        {repo && (
          <div className="ms-auto dropdown">
            <button className="btn btn-sm btn-outline-secondary" data-bs-toggle="dropdown">
              <i className="bi bi-three-dots-vertical" />
            </button>
            <ul className="dropdown-menu dropdown-menu-end">
              <li>
                <button className="dropdown-item" onClick={() => setModal({ type: 'merge' })}>
                  <i className="bi bi-diagram-2 me-2" />Merge Duplicate
                </button>
              </li>
              <li>
                <button className="dropdown-item" onClick={() => setModal({ type: 'edit' })}>
                  <i className="bi bi-pencil me-2" />Edit
                </button>
              </li>
              <li>
                <button className="dropdown-item text-danger" onClick={() => setModal({ type: 'delete' })}>
                  <i className="bi bi-trash me-2" />Delete
                </button>
              </li>
              <li>
                <button className="dropdown-item" onClick={() => buildRepo(repoId)}>
                  <i className="bi bi-arrow-repeat me-2" />Check for new builds
                </button>
              </li>
              <li>
                <button className="dropdown-item" onClick={() => setModal({ type: 'trigger' })}>
                  <i className="bi bi-play me-2" />Trigger build
                </button>
              </li>
              <li>
                <button className="dropdown-item" onClick={() => setModal({ type: 'reclone' })}>
                  <i className="bi bi-arrow-down-up me-2" />Re-clone
                </button>
              </li>
            </ul>
          </div>
        )}
      </div>

      {/* Info card */}
      {repo && (
        <div className="card card-body mb-3 py-2 px-3" style={{ fontSize: 13 }}>
          <table style={{ borderCollapse: 'collapse' }}>
            <tbody>
              <tr>
                <td className="pe-4 py-1"><strong>URL</strong></td>
                <td className="py-1" style={{ userSelect: 'all', fontFamily: 'monospace', fontSize: 12 }}>
                  <a href={transformUrl(repo.url)} target="_blank" rel="noreferrer"
                    style={{ color: PRIMARY }}>{repo.url}</a>
                </td>
              </tr>
              <tr>
                <td className="pe-4 py-1"><strong>State</strong></td>
                <td className="py-1">
                  <i className={`bi ${stateIcon(repo.state)} me-1`} />
                  {repo.state}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      )}

      {/* ── Tab bar ── */}
      <ul className="nav nav-tabs mb-3">
        {[
          { label: 'Dependent Projects', path: `${base}/info`   },
          { label: 'Dependent Builds',   path: `${base}/builds` },
        ].map(({ label, path }) => (
          <li className="nav-item" key={path}>
            <NavLink
              className={({ isActive }) => `nav-link${isActive ? ' active' : ' text-muted'}`}
              to={path}
            >
              {label}
            </NavLink>
          </li>
        ))}
      </ul>

      {/* ── Routed tab content ── */}
      <Routes>
        <Route path="info"   element={<DependentsTab repoId={repoId} />} />
        <Route path="builds" element={repo ? <BuildTable repository={repo} /> : null} />
        <Route path="*"      element={<Navigate to={`${base}/info`} replace />} />
      </Routes>
    </div>
  );
}
