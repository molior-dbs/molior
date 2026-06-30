/**
 * UserListPage — port of UserListComponent + user-list.html.
 *
 * Route: /users
 * Tabs:  Users (this page) | Tokens (placeholder — separate route /tokens)
 *
 * Columns: username · email · administrator · actions
 * Filters: username text, email text, admin checkbox
 * Actions: Details · Edit · Delete  (Edit/Delete disabled for 'admin' user)
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate, NavLink } from 'react-router-dom';
import { fetchUsers, deleteUser } from '../../api/users';
import UserForm from './UserForm';
import ConfirmModal from '../build/ConfirmModal';
import ContextMenu from '../common/ContextMenu';
import Pagination from '../common/Pagination';

const PRIMARY  = '#571845';
const TH       = { backgroundColor: PRIMARY, color: 'white' };
const PAGE_SIZE = 20;

export default function UserListPage() {
  const navigate = useNavigate();

  const [users,  setUsers]  = useState([]);
  const [total,  setTotal]  = useState(null);
  const [error,  setError]  = useState('');
  const [page,   setPage]   = useState(1);

  const [filterName,  setFilterName]  = useState('');
  const [filterEmail, setFilterEmail] = useState('');
  const [filterAdmin, setFilterAdmin] = useState(false);

  const [modal, setModal] = useState(null); // { type: 'create'|'edit'|'delete', user? }
  const [ctxMenu, setCtxMenu] = useState(null);

  const load = useCallback(async (pg = page) => {
    setError(''); setTotal(null);
    try {
      const data = await fetchUsers({ name: filterName, email: filterEmail, admin: filterAdmin, page: pg, page_size: PAGE_SIZE });
      setUsers(data.results ?? []);
      setTotal(data.total_result_count ?? 0);
    } catch (e) { setError(e.message); setTotal(-1); }
  }, [page, filterName, filterEmail, filterAdmin]);

  useEffect(() => { load(page); }, [page]);

  const prevRef = useRef({ filterName, filterEmail, filterAdmin });
  useEffect(() => {
    const p = prevRef.current;
    if (p.filterName !== filterName || p.filterEmail !== filterEmail || p.filterAdmin !== filterAdmin) {
      prevRef.current = { filterName, filterEmail, filterAdmin };
      setPage(1); load(1);
    }
  }, [filterName, filterEmail, filterAdmin]);

  function closeModal(reload) { setModal(null); if (reload) load(page); }

  const totalPages = total > 0 ? Math.ceil(total / PAGE_SIZE) : 1;

  return (
    <div className="p-3">

      {/* ── Modals ── */}
      {modal?.type === 'create' && <UserForm onClose={closeModal} />}
      {modal?.type === 'edit'   && <UserForm user={modal.user} onClose={closeModal} />}
      {modal?.type === 'delete' && (
        <ConfirmModal
          title="Delete User"
          body={<>User <strong>{modal.user.username}</strong> will be deleted. This operation cannot be undone.</>}
          onConfirm={() => deleteUser(modal.user.id)}
          onClose={closeModal}
        />
      )}

      {ctxMenu && (
        <ContextMenu x={ctxMenu.x} y={ctxMenu.y} onClose={() => setCtxMenu(null)}>
          <li><button className="dropdown-item" onClick={() => { navigate(`/users/${ctxMenu.u.username}`); setCtxMenu(null); }}><i className="bi bi-list me-2" />Details</button></li>
          {ctxMenu.u.username !== 'admin' && <li><button className="dropdown-item" onClick={() => { setModal({ type: 'edit', user: ctxMenu.u }); setCtxMenu(null); }}><i className="bi bi-pencil me-2" />Edit</button></li>}
          {ctxMenu.u.username !== 'admin' && <li><button className="dropdown-item text-danger" onClick={() => { setModal({ type: 'delete', user: ctxMenu.u }); setCtxMenu(null); }}><i className="bi bi-trash me-2" />Delete</button></li>}
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
                  onPageChange={setPage} label="users" />

      <div>
        <table className="table table-sm table-hover align-middle mb-0" style={{ fontSize: 13 }}>
          <thead>
            <tr>
              {/* Username filter */}
              <th style={{ ...TH, minWidth: 180 }}>
                <input
                  className="form-control form-control-sm bg-transparent border-0 text-white"
                  placeholder="Username"
                  value={filterName}
                  onChange={e => setFilterName(e.target.value)}
                  style={{ minWidth: 150 }}
                />
              </th>
              {/* Email filter */}
              <th style={{ ...TH, minWidth: 220 }}>
                <input
                  className="form-control form-control-sm bg-transparent border-0 text-white"
                  placeholder="Email"
                  value={filterEmail}
                  onChange={e => setFilterEmail(e.target.value)}
                  style={{ minWidth: 180 }}
                />
              </th>
              {/* Admin filter */}
              <th style={{ ...TH, whiteSpace: 'nowrap' }}>
                <div className="d-flex align-items-center gap-2">
                  <input
                    className="form-check-input mt-0"
                    type="checkbox"
                    checked={filterAdmin}
                    onChange={e => setFilterAdmin(e.target.checked)}
                    title="Show admins only"
                    style={{ cursor: 'pointer' }}
                  />
                  <span>Administrator</span>
                </div>
              </th>
              {/* Create button */}
              <th style={{ ...TH, textAlign: 'right' }}>
                <button
                  className="btn btn-sm border-0 p-0"
                  style={{ color: 'white', fontSize: 20, lineHeight: 1 }}
                  title="Create user"
                  onClick={() => setModal({ type: 'create' })}
                >
                  <i className="bi bi-person-plus" style={{ fontSize: 18 }} />
                </button>
              </th>
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

            {users.map(u => (
              <tr key={u.id} style={{ cursor: 'pointer' }}
                  onClick={e => { if (!e.target.closest('.dropdown')) navigate(`/users/${u.username}`); }}
                  onContextMenu={e => { e.preventDefault(); setCtxMenu({ x: e.clientX, y: e.clientY, u }); }}>
                <td><strong>{u.username}</strong></td>
                <td>{u.email}</td>
                <td className="text-center">
                  {u.is_admin && <i className="bi bi-check-lg text-success" />}
                </td>
                <td className="text-end">
                  <div className="dropdown">
                    <button className="btn btn-sm btn-link p-0 text-secondary"
                            data-bs-toggle="dropdown" onClick={e => e.stopPropagation()}>
                      <i className="bi bi-three-dots-vertical" />
                    </button>
                    <ul className="dropdown-menu dropdown-menu-end">
                      <li>
                        <button className="dropdown-item"
                                onClick={() => navigate(`/users/${u.username}`)}>
                          <i className="bi bi-list me-2" />Details
                        </button>
                      </li>
                      {u.username !== 'admin' && (
                        <li>
                          <button className="dropdown-item"
                                  onClick={() => setModal({ type: 'edit', user: u })}>
                            <i className="bi bi-pencil me-2" />Edit
                          </button>
                        </li>
                      )}
                      {u.username !== 'admin' && (
                        <li>
                          <button className="dropdown-item text-danger"
                                  onClick={() => setModal({ type: 'delete', user: u })}>
                            <i className="bi bi-trash me-2" />Delete
                          </button>
                        </li>
                      )}
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
