/**
 * UserInfoPage — port of UserInfoComponent + user-info.html.
 *
 * Route: /users/:username
 * Shows user details (email, admin flag) with Edit / Delete actions.
 * Edit and Delete are hidden for the 'admin' built-in user.
 */
import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { fetchUser, deleteUser } from '../../api/users';
import UserForm from './UserForm';
import ConfirmModal from '../build/ConfirmModal';

const PRIMARY = '#571845';

export default function UserInfoPage() {
  const { username } = useParams();
  const navigate     = useNavigate();

  const [user,  setUser]  = useState(null);
  const [error, setError] = useState('');
  const [modal, setModal] = useState(null); // { type: 'edit' | 'delete' }

  useEffect(() => {
    fetchUser(username)
      .then(setUser)
      .catch(e => setError(e.message));
  }, [username]);

  function closeModal(reload) {
    setModal(null);
    if (reload) {
      if (modal?.type === 'delete') {
        navigate('/users');
      } else {
        fetchUser(username).then(setUser).catch(() => {});
      }
    }
  }

  const isBuiltIn = username === 'admin';

  return (
    <div className="p-3">

      {/* ── Modals ── */}
      {modal?.type === 'edit' && user && (
        <UserForm user={user} onClose={closeModal} />
      )}
      {modal?.type === 'delete' && user && (
        <ConfirmModal
          title="Delete User"
          body={<>User <strong>{user.username}</strong> will be deleted. This operation cannot be undone.</>}
          onConfirm={() => deleteUser(user.id)}
          onClose={closeModal}
        />
      )}

      {/* ── Heading ── */}
      <h1 className="mb-3 d-flex align-items-center gap-2" style={{ fontSize: 24, fontWeight: 500 }}>
        <i className="bi bi-people" />
        User <span className="ms-1">{username}</span>
      </h1>

      {error && <div className="alert alert-danger py-2">{error}</div>}

      {/* ── Info card ── */}
      <div className="card card-body py-2 px-3 mb-3 d-flex flex-row align-items-start"
           style={{ fontSize: 13 }}>
        <table style={{ borderCollapse: 'collapse' }}>
          <tbody>
            <tr>
              <td className="pe-4 py-1"><strong>Email</strong></td>
              <td className="py-1">{user?.email ?? <span className="text-muted">—</span>}</td>
            </tr>
            <tr>
              <td className="pe-4 py-1"><strong>Administrator</strong></td>
              <td className="py-1">
                {user?.is_admin
                  ? <i className="bi bi-check-lg text-success" />
                  : <i className="bi bi-dash text-muted" />}
              </td>
            </tr>
          </tbody>
        </table>

        {/* Actions — hidden for 'admin' built-in user */}
        {!isBuiltIn && user && (
          <div className="ms-auto dropdown">
            <button className="btn btn-sm btn-outline-secondary" data-bs-toggle="dropdown">
              <i className="bi bi-three-dots-vertical" />
            </button>
            <ul className="dropdown-menu dropdown-menu-end">
              <li>
                <button className="dropdown-item" onClick={() => setModal({ type: 'edit' })}>
                  <i className="bi bi-pencil me-2" />Edit
                </button>
              </li>
              <li>
                <button className="dropdown-item text-danger"
                        onClick={() => setModal({ type: 'delete' })}>
                  <i className="bi bi-trash me-2" />Delete
                </button>
              </li>
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
