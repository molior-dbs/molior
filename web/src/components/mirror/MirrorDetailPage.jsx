/**
 * MirrorDetailPage — port of MirrorInfoComponent + mirror-info.html
 *                    and MirrorAPTSourcesComponent + mirror-aptsources.html.
 *
 * Route: /mirror/:name/:version/*
 * Tabs:  Info (mirror details + dependents table) | APT Sources
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate, NavLink, Routes, Route, Navigate } from 'react-router-dom';
import { fetchMirror, fetchMirrorDependents, fetchMirrorAptSources, deleteMirror, updateMirror } from '../../api/mirrors';
import MirrorForm from './MirrorForm';
import ConfirmModal from '../build/ConfirmModal';
import Pagination from '../common/Pagination';
import debianLogo from '../../assets/debian.svg';

const PRIMARY  = '#571845';
const TH       = { backgroundColor: PRIMARY, color: 'white' };
const PAGE_SIZE = 20;

// ── State icon (reused from MirrorListPage) ────────────────────────────────
function mirrorStateIcon(state) {
  switch (state) {
    case 'ready':      return 'bi-check-lg text-success';
    case 'updating':   return 'bi-arrow-repeat rotating text-primary';
    case 'publishing': return 'bi-upload text-primary';
    case 'created':    return 'bi-clock text-muted';
    case 'init_error':
    case 'error':      return 'bi-exclamation-triangle text-danger';
    default:           return 'bi-three-dots text-muted';
  }
}

// ── Shared header (info card + actions menu) ───────────────────────────────
function MirrorHeader({ mirror, name, version, onAction }) {
  if (!mirror) {
    return (
      <h1 className="mb-3" style={{ fontSize: 24, fontWeight: 500 }}>
        <i className="bi bi-folder-symlink me-2" />
        Mirror {name}/{version}
      </h1>
    );
  }

  const baseParts = mirror.basemirror_name?.split('/') ?? [];

  return (
    <>
      {/* Heading */}
      <div className="d-flex align-items-center mb-1 gap-2">
        <h1 className="mb-0 d-flex align-items-center gap-2 flex-wrap" style={{ fontSize: 24, fontWeight: 500 }}>
          <i className="bi bi-folder-symlink" />
          <NavLink to="/mirrors" style={{ color: 'inherit', textDecoration: 'none' }}>
            {mirror.name}
          </NavLink>
          <span className="text-muted fw-normal">/</span>
          <span>{mirror.version}</span>
          {mirror.is_basemirror && (
            <img src={debianLogo} alt="Debian" title="Debian Base Mirror" style={{ width: 16, height: 16, marginLeft: 4 }} />
          )}
        </h1>

        {/* Actions menu */}
        <div className="ms-auto dropdown">
          <button className="btn btn-sm btn-outline-secondary" data-bs-toggle="dropdown">
            <i className="bi bi-three-dots-vertical" />
          </button>
          <ul className="dropdown-menu dropdown-menu-end">
            <li>
              <button className="dropdown-item" onClick={() => onAction('edit')}>
                <i className="bi bi-pencil me-2" />Edit
              </button>
            </li>
            <li>
              <button className="dropdown-item" onClick={() => onAction('copy')}>
                <i className="bi bi-copy me-2" />Copy
              </button>
            </li>
            <li>
              <button className="dropdown-item" onClick={() => onAction('update')}>
                <i className="bi bi-arrow-clockwise me-2" />Update
              </button>
            </li>
            <li>
              <button className="dropdown-item text-danger" onClick={() => onAction('delete')}>
                <i className="bi bi-trash me-2" />Delete
              </button>
            </li>
          </ul>
        </div>
      </div>

      {/* Description */}
      {mirror.description && (
        <div className="text-muted mb-2" style={{ fontSize: 14 }}>{mirror.description}</div>
      )}

      {/* Info card */}
      <div className="card card-body mb-3 py-2 px-3" style={{ fontSize: 13 }}>
        <table style={{ borderCollapse: 'collapse' }}>
          <tbody>
            <tr>
              <td className="pe-4 py-1"><strong>APT Repository</strong></td>
              <td className="pe-5 py-1">
                <a href={mirror.apt_url} target="_blank" rel="noreferrer"
                   style={{ color: PRIMARY }}>{mirror.apt_url}</a>
              </td>
              <td className="pe-4 py-1"><strong>Mirror URL</strong></td>
              <td className="py-1">
                <a href={mirror.url} target="_blank" rel="noreferrer"
                   style={{ color: PRIMARY, wordBreak: 'break-all' }}>{mirror.url}</a>
              </td>
            </tr>
            <tr>
              <td className="pe-4 py-1"><strong>Architectures</strong></td>
              <td className="pe-5 py-1">
                {(mirror.architectures ?? []).join(', ')}
                {mirror.with_sources   && <span className="text-muted">, sources</span>}
                {mirror.with_installer && <span className="text-muted">, installer</span>}
              </td>
              <td className="pe-4 py-1"><strong>Components</strong></td>
              <td className="py-1">{(mirror.components || '').split(',').join(' ')}</td>
            </tr>
            <tr>
              <td className="pe-4 py-1"><strong>State</strong></td>
              <td className="pe-5 py-1">
                <i className={`bi ${mirrorStateIcon(mirror.state)} me-1`} />
                {mirror.state}
                {mirror.progress != null &&
                 (mirror.state === 'updating' || mirror.state === 'publishing') && (
                  <span className="ms-2 text-muted" style={{ fontFamily: 'monospace' }}>
                    {Math.round(mirror.progress)}%
                  </span>
                )}
              </td>
              <td className="pe-4 py-1"><strong>Distribution</strong></td>
              <td className="py-1">{mirror.distribution}</td>
            </tr>
            {mirror.mirrorfilter && (
              <tr>
                <td className="pe-4 py-1"><strong>Filter</strong></td>
                <td className="pe-5 py-1" colSpan={3}
                    style={{ fontFamily: 'monospace', fontSize: 12 }}>{mirror.mirrorfilter}</td>
              </tr>
            )}
            <tr>
              <td className="pe-4 py-1"><strong>External repo</strong></td>
              <td className="pe-5 py-1">
                <i className={`bi ${mirror.external_repo ? 'bi-check-lg text-success' : 'bi-dash'}`} />
              </td>
              {mirror.mirrorkeyserver ? (
                <>
                  <td className="pe-4 py-1"><strong>Key Server</strong></td>
                  <td className="py-1">
                    <a href={mirror.mirrorkeyserver} target="_blank" rel="noreferrer"
                       style={{ color: PRIMARY }}>{mirror.mirrorkeyserver}</a>
                  </td>
                </>
              ) : mirror.mirrorkeyurl ? (
                <>
                  <td className="pe-4 py-1"><strong>Key URL</strong></td>
                  <td className="py-1">
                    <a href={mirror.mirrorkeyurl} target="_blank" rel="noreferrer"
                       style={{ color: PRIMARY }}>{mirror.mirrorkeyurl}</a>
                  </td>
                </>
              ) : <td colSpan={2} />}
            </tr>
            <tr>
              <td className="pe-4 py-1">
                {mirror.basemirror_name && <strong>Base Mirror</strong>}
              </td>
              <td className="pe-5 py-1">
                {mirror.basemirror_name && (
                  <NavLink to={`/mirror/${baseParts[0]}/${baseParts[1]}`}
                           style={{ color: PRIMARY }}>{mirror.basemirror_name}</NavLink>
                )}
              </td>
              {mirror.mirrorkeyids ? (
                <>
                  <td className="pe-4 py-1"><strong>Key IDs</strong></td>
                  <td className="py-1" style={{ fontFamily: 'monospace', fontSize: 12 }}>
                    {mirror.mirrorkeyids.split(',').join(' ')}
                  </td>
                </>
              ) : <td colSpan={2} />}
            </tr>
            {!mirror.is_basemirror && (
              <tr>
                <td className="pe-4 py-1"><strong>Dependency Policy</strong></td>
                <td className="py-1">{mirror.dependency_policy}</td>
                <td colSpan={2} />
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}

// ── Tab: Info (mirror details + dependents table) ──────────────────────────
function InfoTab({ mirror, name, version }) {
  const navigate = useNavigate();

  const [items, setItems]   = useState([]);
  const [total, setTotal]   = useState(null);
  const [error, setError]   = useState('');
  const [page, setPage]     = useState(1);
  const [filter, setFilter] = useState('');

  const load = useCallback(async (pg = page) => {
    setError('');
    try {
      const data = await fetchMirrorDependents(name, version, filter, pg, PAGE_SIZE);
      setItems(data.results ?? []);
      setTotal(data.total_result_count ?? 0);
    } catch (e) { setError(e.message); setTotal(-1); }
  }, [name, version, page, filter]);

  useEffect(() => { load(page); }, [page, mirror]); // mirror in deps: re-fire when parent data arrives (issue #2)

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
      <h2 style={{ fontSize: 17, fontWeight: 600 }} className="mb-2">Mirror Dependents</h2>

      <Pagination page={page} totalPages={totalPages} total={total} pageSize={PAGE_SIZE}
                  onPageChange={setPage} label="dependents" />

      <div>
        <table className="table table-sm table-hover align-middle mb-0" style={{ fontSize: 13 }}>
          <thead>
            <tr>
              <th style={{ ...TH, minWidth: 220 }}>
                <input
                  className="form-control form-control-sm"
                  placeholder="Dependent"
                  value={filter}
                  onChange={e => setFilter(e.target.value)}
                  style={{ minWidth: 180 }}
                />
              </th>
              <th style={TH}>Architectures</th>
              <th style={{ ...TH, textAlign: 'center' }}>Locked</th>
              <th style={{ ...TH, width: '100%' }}>Description</th>
              <th style={TH} />
            </tr>
          </thead>
          <tbody>
            {total === null && (
              <tr><td colSpan={5} className="text-center py-3 text-muted">Loading…</td></tr>
            )}
            {total === -1 && (
              <tr><td colSpan={5} className="text-center py-3 text-danger">
                Unable to load data ({error})
              </td></tr>
            )}
            {total === 0 && (
              <tr><td colSpan={5} className="text-center py-3 text-muted">No entries found</td></tr>
            )}

            {items.map(dep => (
              <tr key={dep.id} style={{ cursor: 'pointer' }} onClick={e => { if (!e.target.closest('.dropdown')) navigate(depLink(dep)); }}>
                <td>
                  <strong className="d-flex align-items-center gap-1">
                    <i className={`bi ${dep.is_mirror ? 'bi-folder2-open' : 'bi-collection'}`} />
                    {dep.project_name}/{dep.name}
                  </strong>
                </td>
                <td>{(dep.architectures ?? []).join(', ')}</td>
                <td className="text-center">
                  <i className={`bi ${dep.is_locked ? 'bi-lock-fill' : 'bi-dash'}`} />
                </td>
                <td className="text-muted">{dep.description}</td>
                <td className="text-end">
                  <div className="dropdown">
                    <button className="btn btn-sm btn-link p-0 text-secondary"
                            data-bs-toggle="dropdown" onClick={e => e.stopPropagation()}>
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


    </div>
  );
}

// ── Tab: APT Sources ───────────────────────────────────────────────────────
function AptSourcesTab({ name, version }) {
  const [sources, setSources] = useState('');
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState('');

  useEffect(() => {
    setLoading(true); setError('');
    fetchMirrorAptSources(name, version)
      .then(s => { setSources(s); setLoading(false); })
      .catch(e => { setError(e.message); setLoading(false); });
  }, [name, version]);

  function formatSources(raw) {
    const lines = raw.split('\n');
    if (lines[lines.length - 1] === '') lines.pop();
    return lines.map((line, i) => {
      if (line.startsWith('#')) {
        return <span key={i} className="text-muted">{line}{'\n'}</span>;
      }
      if (line.startsWith('deb ')) {
        const parts = line.split(' ');
        // Angular only shows 4 parts (deb URL dist component)
        return (
          <strong key={i} style={{ display: 'block' }}>
            <span>{parts[0]}</span>{' '}
            <span>{parts[1]}</span>{' '}
            <span>{parts[2]}</span>{' '}
            <span>{parts.slice(3).join(' ')}</span>{'\n'}
          </strong>
        );
      }
      return <span key={i}>{line}{'\n'}</span>;
    });
  }

  if (loading) return <div className="text-muted py-3">Loading…</div>;
  if (error)   return <div className="alert alert-danger py-2">Failed to load: {error}</div>;

  return (
    <div>
      <h2 style={{ fontSize: 17, fontWeight: 600 }} className="mb-2">APT Sources</h2>
      <pre className="bg-light p-3 rounded" style={{ fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
        {formatSources(sources)}
      </pre>
    </div>
  );
}

// ── Root component ─────────────────────────────────────────────────────────
export default function MirrorDetailPage() {
  const { name, version } = useParams();
  const navigate           = useNavigate();

  const [mirror,    setMirror]    = useState(null);
  const [loadError, setLoadError] = useState('');
  const [modal,     setModal]     = useState(null);

  const base = `/mirror/${name}/${version}`;

  // Load mirror metadata
  useEffect(() => {
    fetchMirror(name, version)
      .then(setMirror)
      .catch(e => setLoadError(e.message));
  }, [name, version]);

  function reload() {
    fetchMirror(name, version).then(setMirror).catch(() => {});
  }

  function closeModal(didChange) {
    setModal(null);
    if (didChange) reload();
  }

  function onAction(type) {
    if (type === 'update') {
      if (mirror) updateMirror(mirror.id).catch(() => {});
      return;
    }
    setModal({ type });
  }

  return (
    <div className="p-3">

      {/* ── Modals ── */}
      {modal?.type === 'edit' && mirror && (
        <MirrorForm mirror={mirror} onClose={closeModal} />
      )}
      {modal?.type === 'copy' && mirror && (
        <MirrorForm copyFrom={mirror} onClose={didChange => {
          setModal(null);
          // after copy navigate to mirror list so user can find the new mirror
          if (didChange) navigate('/mirrors');
        }} />
      )}
      {modal?.type === 'delete' && mirror && (
        <ConfirmModal
          title="Delete Mirror"
          body="The mirror will be deleted only if no project version is using it. This operation cannot be undone."
          onConfirm={() => deleteMirror(mirror.name, mirror.version)}
          onClose={didChange => {
            setModal(null);
            if (didChange) navigate('/mirrors');
          }}
        />
      )}

      {/* ── Header ── */}
      {loadError && (
        <div className="alert alert-danger py-2">Failed to load mirror: {loadError}</div>
      )}
      <MirrorHeader mirror={mirror} name={name} version={version} onAction={onAction} />

      {/* ── Tab bar ── */}
      <ul className="nav nav-tabs mb-3">
        {[
          { label: 'Info',        path: `${base}/info` },
          { label: 'APT Sources', path: `${base}/aptsources` },
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
        <Route path="info"       element={<InfoTab mirror={mirror} name={name} version={version} />} />
        <Route path="aptsources" element={<AptSourcesTab name={name} version={version} />} />
        <Route path="*"          element={<Navigate to={`${base}/info`} replace />} />
      </Routes>
    </div>
  );
}
