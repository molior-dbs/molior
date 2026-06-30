/**
 * RepoListPage — port of RepositoryListComponent + repo-list.html.
 *
 * Columns: state · name · url · actions
 * Actions: Details · Merge Duplicate · Edit URL · Delete · Check for new builds ·
 *          Trigger build · Re-clone
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  fetchRepos, fetchRepoDependentProjectVersions,
  editRepoUrl, deleteRepo, buildRepo, recloneRepo, mergeRepo, triggerBuild,
} from '../../api/repos';
import ConfirmModal from '../build/ConfirmModal';
import ContextMenu from '../common/ContextMenu';
import { rules, fieldClass, fieldError } from '../../lib/validate';
import { apiUrl } from '../../lib/base';

const PRIMARY  = '#571845';
const TH       = { backgroundColor: PRIMARY, color: 'white' };
const PAGE_SIZE = 20;

// ── SSH → HTTPS URL transform (mirrors transformUrl in Angular) ────────────
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
  const [originalUrl, setOriginalUrl] = useState('');
  const [matches, setMatches]         = useState([]);
  const [error, setError]             = useState('');
  const [saving, setSaving]           = useState(false);

  // Search as user types
  useEffect(() => {
    if (!originalUrl.trim()) { setMatches([]); return; }
    const params = new URLSearchParams({ filter_url: originalUrl, page: 1, page_size: 25 });
    fetch(apiUrl(`/api2/repositories?${params}`), { credentials: 'same-origin' })
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
            <p className="mb-1">
              Merging <strong>{repo.name}</strong> into an existing repository.
            </p>
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
  const [gitref, setGitref]         = useState('');
  const [pvs, setPvs]               = useState([]);
  const [selectedPvs, setSelectedPvs] = useState([]);
  const [forceCI, setForceCI]       = useState(false);
  const [error, setError]           = useState('');
  const [saving, setSaving]         = useState(false);

  useEffect(() => {
    fetchRepoDependentProjectVersions(repo.id, { unlocked: true })
      .then(d => {
        const list = (d.results ?? []).map(r => `${r.project_name}/${r.name}`);
        setPvs(list);
      })
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

// ── Main list page ────────────────────────────────────────────────────────
export default function RepoListPage() {
  const navigate = useNavigate();

  const [repos, setRepos]   = useState([]);
  const [total, setTotal]   = useState(null);
  const [error, setError]   = useState('');
  const [page, setPage]     = useState(1);

  const [filterName, setFilterName] = useState('');
  const [filterUrl, setFilterUrl]   = useState('');

  // modal: { type: 'edit'|'delete'|'reclone'|'merge'|'trigger', repo }
  const [modal, setModal] = useState(null);
  const [ctxMenu, setCtxMenu] = useState(null);

  const load = useCallback(async (pg = page) => {
    setError(''); setTotal(null);
    try {
      const data = await fetchRepos({ q: filterName, filter_url: filterUrl, page: pg, page_size: PAGE_SIZE });
      setRepos(data.results ?? []);
      setTotal(data.total_result_count ?? 0);
    } catch (e) { setError(e.message); setTotal(-1); }
  }, [page, filterName, filterUrl]);

  useEffect(() => { load(page); }, [page]);

  const prevRef = useRef({ filterName, filterUrl });
  useEffect(() => {
    const p = prevRef.current;
    if (p.filterName !== filterName || p.filterUrl !== filterUrl) {
      prevRef.current = { filterName, filterUrl };
      setPage(1); load(1);
    }
  }, [filterName, filterUrl]);

  function closeModal(reload) { setModal(null); if (reload) load(page); }

  const totalPages = total > 0 ? Math.ceil(total / PAGE_SIZE) : 1;

  return (
    <div className="p-3">

      {/* ── Modals ── */}
      {modal?.type === 'edit'    && <EditUrlModal repo={modal.repo} onClose={closeModal} />}
      {modal?.type === 'merge'   && <MergeModal   repo={modal.repo} onClose={closeModal} />}
      {modal?.type === 'trigger' && <TriggerModal  repo={modal.repo} onClose={closeModal} />}
      {modal?.type === 'delete'  && (
        <ConfirmModal
          title="Delete Repository"
          body={<span>The repository <strong>{modal.repo.name}</strong> will be deleted. This operation cannot be undone.</span>}
          onConfirm={() => deleteRepo(modal.repo.id)}
          onClose={closeModal}
        />
      )}
      {modal?.type === 'reclone' && (
        <ConfirmModal
          title="Re-clone Source Repository"
          body="The source repository will be re-cloned. Do you want to continue?"
          onConfirm={() => recloneRepo(modal.repo.id)}
          onClose={closeModal}
        />
      )}

      {/* ── Context menu (right-click on row) ── */}
      {ctxMenu && (
        <ContextMenu x={ctxMenu.x} y={ctxMenu.y} onClose={() => setCtxMenu(null)}>
          <li><button className="dropdown-item" onClick={() => { navigate(`/repo/${ctxMenu.repo.id}`); setCtxMenu(null); }}><i className="bi bi-list me-2" />Details</button></li>
          <li><button className="dropdown-item" onClick={() => { setModal({ type: 'merge', repo: ctxMenu.repo }); setCtxMenu(null); }}><i className="bi bi-diagram-2 me-2" />Merge Duplicate</button></li>
          <li><button className="dropdown-item" onClick={() => { setModal({ type: 'edit', repo: ctxMenu.repo }); setCtxMenu(null); }}><i className="bi bi-pencil me-2" />Edit</button></li>
          <li><button className="dropdown-item text-danger" onClick={() => { setModal({ type: 'delete', repo: ctxMenu.repo }); setCtxMenu(null); }}><i className="bi bi-trash me-2" />Delete</button></li>
          <li><button className="dropdown-item" onClick={() => { buildRepo(ctxMenu.repo.id).catch(() => {}); setCtxMenu(null); }}><i className="bi bi-arrow-repeat me-2" />Check for new builds</button></li>
          <li><button className="dropdown-item" onClick={() => { setModal({ type: 'trigger', repo: ctxMenu.repo }); setCtxMenu(null); }}><i className="bi bi-play me-2" />Trigger build</button></li>
          <li><button className="dropdown-item" onClick={() => { setModal({ type: 'reclone', repo: ctxMenu.repo }); setCtxMenu(null); }}><i className="bi bi-arrow-down-up me-2" />Re-clone</button></li>
        </ContextMenu>
      )}

      <h1 className="mb-3 d-flex align-items-center gap-2" style={{ fontSize: 24, fontWeight: 500 }}>
        <i className="bi bi-git" />Repositories
      </h1>

      <div>
        <table className="table table-sm table-hover align-middle mb-0" style={{ fontSize: 13 }}>
          <thead>
            <tr>
              <th style={{ ...TH, width: 44 }} title="State">State</th>
              <th style={TH}>
                <input
                  className="form-control form-control-sm bg-transparent border-0 text-white"
                  placeholder="Name"
                  value={filterName}
                  onChange={e => setFilterName(e.target.value)}
                  style={{ minWidth: 160 }}
                />
              </th>
              <th style={TH}>
                <input
                  className="form-control form-control-sm bg-transparent border-0 text-white"
                  placeholder="Source URL"
                  value={filterUrl}
                  onChange={e => setFilterUrl(e.target.value)}
                  style={{ minWidth: 260 }}
                />
              </th>
              <th style={TH} />
            </tr>
          </thead>
          <tbody>
            {total === null && (
              <tr><td colSpan={4} className="text-center py-3 text-muted">Loading…</td></tr>
            )}
            {total === -1 && (
              <tr><td colSpan={4} className="text-center py-3 text-danger">Unable to load data ({error})</td></tr>
            )}
            {total === 0 && (
              <tr><td colSpan={4} className="text-center py-3 text-muted">No entries found</td></tr>
            )}

            {repos.map(repo => (
              <tr key={repo.id} style={{ cursor: 'pointer' }}
                onClick={e => { if (!e.target.closest('.dropdown')) navigate(`/repo/${repo.id}`); }}
                onContextMenu={e => { e.preventDefault(); setCtxMenu({ x: e.clientX, y: e.clientY, repo }); }}>

                <td className="text-center">
                  <i className={`bi ${stateIcon(repo.state)}`} title={repo.state} style={{ fontSize: 16 }} />
                </td>

                <td><strong>{repo.name}</strong></td>

                <td onClick={e => e.stopPropagation()}
                  style={{ userSelect: 'all', fontFamily: 'monospace', fontSize: 12 }}>
                  <a href={transformUrl(repo.url)} target="_blank" rel="noreferrer"
                    style={{ color: 'darkblue' }}>{repo.url}</a>
                </td>

                <td className="text-end">
                  <div className="dropdown">
                    <button className="btn btn-sm btn-link p-0 text-secondary"
                      data-bs-toggle="dropdown" onClick={e => e.stopPropagation()}><i className="bi bi-three-dots-vertical" /></button>
                    <ul className="dropdown-menu dropdown-menu-end">
                      <li>
                        <button className="dropdown-item" onClick={() => navigate(`/repo/${repo.id}`)}>
                          <i className="bi bi-list me-2" />Details
                        </button>
                      </li>
                      <li>
                        <button className="dropdown-item" onClick={() => setModal({ type: 'merge', repo })}>
                          <i className="bi bi-diagram-2 me-2" />Merge Duplicate
                        </button>
                      </li>
                      <li>
                        <button className="dropdown-item" onClick={() => setModal({ type: 'edit', repo })}>
                          <i className="bi bi-pencil me-2" />Edit
                        </button>
                      </li>
                      <li>
                        <button className="dropdown-item text-danger" onClick={() => setModal({ type: 'delete', repo })}>
                          <i className="bi bi-trash me-2" />Delete
                        </button>
                      </li>
                      <li>
                        <button className="dropdown-item" onClick={() => buildRepo(repo.id)}>
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
            ))}
          </tbody>
        </table>
      </div>

      {/* ── Pagination ── */}
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
