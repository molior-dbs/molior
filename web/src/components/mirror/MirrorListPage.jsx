/**
 * MirrorListPage — port of MirrorListComponent + mirror-list.html.
 *
 * Columns: type (base mirror flag) · state · name/version · components ·
 *          architectures · basemirror · url · actions
 *
 * Actions: Details · Edit · Copy · Update · Delete
 * Header:  + Create button
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchMirrors, deleteMirror, updateMirror } from '../../api/mirrors';
import MirrorForm from './MirrorForm';
import ConfirmModal from '../build/ConfirmModal';

const PRIMARY = '#571845';
const TH = { backgroundColor: PRIMARY, color: 'white' };
const PAGE_SIZE = 20;

function mirrorIcon(state) {
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

export default function MirrorListPage() {
  const navigate = useNavigate();

  const [mirrors, setMirrors] = useState([]);
  const [total, setTotal]     = useState(null);
  const [error, setError]     = useState('');
  const [page, setPage]       = useState(1);

  const [filterName, setFilterName]       = useState('');
  const [filterBase, setFilterBase]       = useState('');

  // modals: { type: 'create'|'edit'|'copy'|'delete', mirror? }
  const [modal, setModal] = useState(null);

  const load = useCallback(async (pg = page) => {
    setError(''); setTotal(null);
    try {
      const data = await fetchMirrors({ q: filterName, q_basemirror: filterBase, page: pg, page_size: PAGE_SIZE });
      setMirrors(data.results ?? []);
      setTotal(data.total_result_count ?? 0);
    } catch (e) { setError(e.message); setTotal(-1); }
  }, [page, filterName, filterBase]);

  useEffect(() => { load(page); }, [page]);

  const prevRef = useRef({ filterName, filterBase });
  useEffect(() => {
    const p = prevRef.current;
    if (p.filterName !== filterName || p.filterBase !== filterBase) {
      prevRef.current = { filterName, filterBase };
      setPage(1); load(1);
    }
  }, [filterName, filterBase]);

  function closeModal(reload) { setModal(null); if (reload) load(page); }

  const totalPages = total > 0 ? Math.ceil(total / PAGE_SIZE) : 1;

  return (
    <div className="p-3">

      {/* ── Modals ── */}
      {modal?.type === 'create' && <MirrorForm onClose={closeModal} />}
      {modal?.type === 'edit'   && <MirrorForm mirror={modal.mirror} onClose={closeModal} />}
      {modal?.type === 'copy'   && <MirrorForm copyFrom={modal.mirror} onClose={closeModal} />}
      {modal?.type === 'delete' && (
        <ConfirmModal
          title="Delete Mirror"
          body="The mirror will be deleted only if no project version is using it. This operation cannot be undone."
          onConfirm={() => deleteMirror(modal.mirror.name, modal.mirror.version)}
          onClose={closeModal}
        />
      )}

      <h1 className="mb-3 d-flex align-items-center gap-2" style={{ fontSize: 24, fontWeight: 500 }}>
        <i className="bi bi-folder-symlink" />Mirrors
      </h1>

      <div>
        <table className="table table-sm table-hover align-middle mb-0" style={{ fontSize: 13 }}>
          <thead>
            <tr>
              <th style={{ ...TH, width: 44 }} title="Type">Type</th>
              <th style={{ ...TH, width: 44 }} title="State">State</th>
              <th style={TH}>
                <input className="form-control form-control-sm bg-transparent border-0 text-white"
                  placeholder="Name / Version / Distribution"
                  value={filterName} onChange={e => setFilterName(e.target.value)}
                  style={{ minWidth: 200 }} />
              </th>
              <th style={TH}>Components</th>
              <th style={TH}>Architectures</th>
              <th style={TH}>
                <input className="form-control form-control-sm bg-transparent border-0 text-white"
                  placeholder="Basemirror"
                  value={filterBase} onChange={e => setFilterBase(e.target.value)}
                  style={{ minWidth: 140 }} />
              </th>
              <th style={TH}>Source URL</th>
              {/* Create button in header */}
              <th style={{ ...TH, textAlign: 'right' }}>
                <button className="btn btn-sm border-0 p-0" style={{ color: 'white', fontSize: 20, lineHeight: 1 }}
                  title="Add mirror" onClick={() => setModal({ type: 'create' })}>
                  ⊕
                </button>
              </th>
            </tr>
          </thead>
          <tbody>
            {total === null && (
              <tr><td colSpan={8} className="text-center py-3 text-muted">Loading…</td></tr>
            )}
            {total === -1 && (
              <tr><td colSpan={8} className="text-center py-3 text-danger">Unable to load data ({error})</td></tr>
            )}
            {total === 0 && (
              <tr><td colSpan={8} className="text-center py-3 text-muted">No entries found</td></tr>
            )}

            {mirrors.map(m => (
              <tr key={m.id} style={{ cursor: 'pointer' }}
                onClick={() => navigate(`/mirror/${m.name}/${m.version}`)}>

                {/* Base mirror flag */}
                <td className="text-center">
                  {m.is_basemirror && <i className="bi bi-debian text-primary" title="Debian Base Mirror" />}
                </td>

                {/* State icon */}
                <td className="text-center">
                  <i className={`bi ${mirrorIcon(m.state)}`} title={m.state} style={{ fontSize: 16 }} />
                </td>

                {/* Name / version / distribution / progress */}
                <td>
                  <strong>{m.name}/{m.version}</strong>
                  {m.name !== m.distribution && (
                    <span className="text-muted ms-2" style={{ float: 'right', marginRight: 10 }}>{m.distribution}</span>
                  )}
                  {m.progress != null && (m.state === 'updating' || m.state === 'publishing') && (
                    <span className="ms-2 text-muted" style={{ fontFamily: 'monospace', fontSize: 12 }}>
                      {Math.round(m.progress)}%
                    </span>
                  )}
                </td>

                {/* Components */}
                <td>{(m.components || '').split(',').join(' ')}</td>

                {/* Architectures */}
                <td>
                  {(m.architectures || []).join(', ')}
                  {m.with_sources   && <span className="text-muted">, sources</span>}
                  {m.with_installer && <span className="text-muted">, installer</span>}
                </td>

                {/* Basemirror */}
                <td onClick={e => {
                  e.stopPropagation();
                  if (m.basemirror_name) {
                    const [bn, bv] = m.basemirror_name.split('/');
                    navigate(`/mirror/${bn}/${bv}`);
                  }
                }}>
                  {m.basemirror_name && (
                    <span style={{ color: 'darkblue', cursor: 'pointer' }}>{m.basemirror_name}</span>
                  )}
                </td>

                {/* URL */}
                <td onClick={e => e.stopPropagation()}
                  style={{ userSelect: 'all', color: 'darkblue', fontFamily: 'monospace', fontSize: 12 }}>
                  {m.url}
                </td>

                {/* Actions */}
                <td className="text-end" onClick={e => e.stopPropagation()}>
                  <div className="dropdown">
                    <button className="btn btn-sm btn-link p-0 text-secondary"
                      data-bs-toggle="dropdown"><i className="bi bi-three-dots-vertical" /></button>
                    <ul className="dropdown-menu dropdown-menu-end">
                      <li>
                        <button className="dropdown-item" onClick={() => navigate(`/mirror/${m.name}/${m.version}`)}>
                          <i className="bi bi-list me-2" />Details
                        </button>
                      </li>
                      <li>
                        <button className="dropdown-item" onClick={() => setModal({ type: 'edit', mirror: m })}>
                          <i className="bi bi-pencil me-2" />Edit
                        </button>
                      </li>
                      <li>
                        <button className="dropdown-item" onClick={() => setModal({ type: 'copy', mirror: m })}>
                          <i className="bi bi-copy me-2" />Copy
                        </button>
                      </li>
                      <li>
                        <button className="dropdown-item" onClick={() => updateMirror(m.id)}>
                          <i className="bi bi-arrow-clockwise me-2" />Update
                        </button>
                      </li>
                      <li>
                        <button className="dropdown-item text-danger" onClick={() => setModal({ type: 'delete', mirror: m })}>
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

      {/* Pagination */}
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
