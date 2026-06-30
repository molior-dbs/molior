/**
 * TokenListPage — port of TokenListComponent + token-list.html.
 *
 * Route: /tokens
 * Shows API tokens for the current user.
 * Columns: description · actions (delete)
 * Header:  + Create button  →  opens CreateTokenModal which reveals the
 *           generated token (shown once, cannot be retrieved later).
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { rules } from '../../lib/validate';
import { NavLink } from 'react-router-dom';
import { fetchTokens, createToken, deleteToken } from '../../api/admin';
import ConfirmModal from '../build/ConfirmModal';
import ContextMenu from '../common/ContextMenu';
import Pagination from '../common/Pagination';

const PRIMARY  = '#571845';
const TH       = { backgroundColor: PRIMARY, color: 'white' };
const PAGE_SIZE = 20;

// ── Create token modal ────────────────────────────────────────────────────────
function CreateTokenModal({ onClose }) {
  const [description, setDescription] = useState('');
  const [token,       setToken]       = useState('');   // revealed after creation
  const [busy,        setBusy]        = useState(false);
  const [error,       setError]       = useState('');

  const descError = rules.required(description, 2, 'Description');

  async function handleCreate() {
    if (descError) return;
    setBusy(true); setError('');
    try {
      const data = await createToken(description.trim());
      setToken(data.token ?? '');
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const created = token.length > 0;

  return (
    <div className="modal fade show d-block" tabIndex="-1"
         style={{ backgroundColor: 'rgba(0,0,0,.4)' }}>
      <div className="modal-dialog modal-dialog-centered">
        <div className="modal-content">
          <div className="modal-header">
            <h5 className="modal-title">Create Authentication Token</h5>
            <button className="btn-close" onClick={() => onClose(created)} disabled={busy} />
          </div>
          <div className="modal-body">
            {error && <div className="alert alert-danger py-2">{error}</div>}

            <label className="form-label fw-semibold">Description</label>
            <div className="d-flex gap-2 mb-3">
              <input
                className="form-control"
                value={description}
                autoFocus={!created}
                readOnly={created}
                placeholder="e.g. CI pipeline key"
                onChange={e => setDescription(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && !created && handleCreate()}
              />
              <button
                className="btn btn-primary"
                onClick={handleCreate}
                disabled={busy || created || !!descError}
              >
                {busy
                  ? <span className="spinner-border spinner-border-sm" />
                  : 'Create'}
              </button>
            </div>

            <label className="form-label fw-semibold">Token</label>
            <input
              className="form-control font-monospace mb-1"
              value={token}
              readOnly
              placeholder="— generated after clicking Create —"
              style={{ fontSize: 13 }}
            />
            {created && (
              <div className="text-muted" style={{ fontSize: 12 }}>
                <i className="bi bi-exclamation-triangle me-1 text-warning" />
                Note: the token cannot be displayed again once this dialog is closed.
              </div>
            )}
          </div>
          <div className="modal-footer">
            <button
              className="btn btn-secondary"
              onClick={() => onClose(created)}
              disabled={busy}
            >
              {created ? 'Close' : 'Cancel'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function TokenListPage() {
  const [tokens, setTokens] = useState([]);
  const [total,  setTotal]  = useState(null);
  const [error,  setError]  = useState('');
  const [page,   setPage]   = useState(1);
  const [filter, setFilter] = useState('');
  const [modal,  setModal]  = useState(null); // { type: 'create' | 'delete', token? }
  const [ctxMenu, setCtxMenu] = useState(null);

  const load = useCallback(async (pg = page) => {
    setError(''); setTotal(null);
    try {
      const data = await fetchTokens({ description: filter, page: pg, page_size: PAGE_SIZE });
      setTokens(data.results ?? []);
      setTotal(data.total_result_count ?? 0);
    } catch (e) {
      setError(e.message);
      setTotal(-1);
    }
  }, [page, filter]);

  useEffect(() => { load(page); }, [page]);

  const prevFilter = useRef(filter);
  useEffect(() => {
    if (prevFilter.current !== filter) {
      prevFilter.current = filter;
      setPage(1); load(1);
    }
  }, [filter]);

  function closeModal(reload) { setModal(null); if (reload) load(page); }

  const totalPages = total > 0 ? Math.ceil(total / PAGE_SIZE) : 1;

  return (
    <div className="p-3">

      {/* ── Modals ── */}
      {modal?.type === 'create' && <CreateTokenModal onClose={closeModal} />}
      {modal?.type === 'delete' && (
        <ConfirmModal
          title="Delete Token"
          body="The token will be deleted. This operation cannot be undone."
          onConfirm={() => deleteToken(modal.token.id)}
          onClose={closeModal}
        />
      )}

      {ctxMenu && (
        <ContextMenu x={ctxMenu.x} y={ctxMenu.y} onClose={() => setCtxMenu(null)}>
          <li><button className="dropdown-item text-danger" onClick={() => { setModal({ type: 'delete', token: ctxMenu.t }); setCtxMenu(null); }}><i className="bi bi-trash me-2" />Delete</button></li>
        </ContextMenu>
      )}

      <h1 className="mb-2 d-flex align-items-center gap-2" style={{ fontSize: 24, fontWeight: 500 }}>
        <i className="bi bi-people" />Accounts
      </h1>

      {/* ── Tab bar ── */}
      <ul className="nav nav-tabs mb-3">
        <li className="nav-item">
          <NavLink className={({ isActive }) => `nav-link${isActive ? ' active' : ' text-muted'}`}
                   to="/users">Users</NavLink>
        </li>
        <li className="nav-item">
          <NavLink className={({ isActive }) => `nav-link${isActive ? ' active' : ' text-muted'}`}
                   to="/tokens">Tokens</NavLink>
        </li>
      </ul>

      <Pagination page={page} totalPages={totalPages} total={total} pageSize={PAGE_SIZE}
                  onPageChange={setPage} label="tokens" />

      <div>
        <table className="table table-sm table-hover align-middle mb-0" style={{ fontSize: 13 }}>
          <thead>
            <tr>
              <th style={{ ...TH, minWidth: 260 }}>
                <input
                  className="form-control form-control-sm bg-transparent border-0 text-white"
                  placeholder="Description"
                  value={filter}
                  onChange={e => setFilter(e.target.value)}
                  style={{ minWidth: 200 }}
                />
              </th>
              <th style={{ ...TH, textAlign: 'right' }}>
                <button
                  className="btn btn-sm border-0 p-0"
                  style={{ color: 'white', fontSize: 20, lineHeight: 1 }}
                  title="Create token"
                  onClick={() => setModal({ type: 'create' })}
                >⊕</button>
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

            {tokens.map(t => (
              <tr key={t.id}
                  onContextMenu={e => { e.preventDefault(); setCtxMenu({ x: e.clientX, y: e.clientY, t }); }}>
                <td><strong>{t.description}</strong></td>
                <td className="text-end">
                  <div className="dropdown">
                    <button className="btn btn-sm btn-link p-0 text-secondary"
                            data-bs-toggle="dropdown" onClick={e => e.stopPropagation()}>
                      <i className="bi bi-three-dots-vertical" />
                    </button>
                    <ul className="dropdown-menu dropdown-menu-end">
                      <li>
                        <button className="dropdown-item text-danger"
                                onClick={() => setModal({ type: 'delete', token: t })}>
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

    </div>
  );
}
