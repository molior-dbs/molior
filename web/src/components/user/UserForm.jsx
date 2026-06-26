/**
 * UserForm — port of UserDialogComponent + user-form.html.
 *
 * Props:
 *   user      object|null   if set → edit mode
 *   onClose   fn(reload)
 */
import React, { useState } from 'react';
import { createUser, editUser } from '../../api/users';

export default function UserForm({ user, onClose }) {
  const isEdit = !!user;

  const [username, setUsername] = useState(user?.username ?? '');
  const [email,    setEmail]    = useState(user?.email    ?? '');
  const [password, setPassword] = useState('');
  const [isAdmin,  setIsAdmin]  = useState(user?.is_admin ?? false);
  const [busy,     setBusy]     = useState(false);
  const [error,    setError]    = useState('');

  // username validation (same rules as Angular nameValidator)
  const usernameValid = isEdit || (/^[a-zA-Z0-9][a-zA-Z0-9._-]*$/.test(username) && username.length >= 2);

  // password: required for create, optional for edit (min 8 if provided)
  const passwordOk = isEdit
    ? (password === '' || password.length >= 8)
    : password.length >= 8;

  const canSave = usernameValid && passwordOk && (isEdit ? true : !!username.trim());

  async function save() {
    setBusy(true); setError('');
    try {
      if (isEdit) {
        await editUser(user.id, {
          email:    email.trim()    || undefined,
          password: password        || undefined,
          is_admin: isAdmin,
        });
      } else {
        await createUser({ name: username.trim(), email: email.trim(), password, is_admin: isAdmin });
      }
      onClose(true);
    } catch (e) { setError(e.message); setBusy(false); }
  }

  return (
    <div className="modal fade show d-block" tabIndex="-1"
         style={{ backgroundColor: 'rgba(0,0,0,.4)' }}>
      <div className="modal-dialog modal-dialog-centered">
        <div className="modal-content">
          <div className="modal-header">
            <h5 className="modal-title d-flex align-items-center gap-2">
              <i className="bi bi-person" />
              {isEdit ? `Edit User: ${user.username}` : 'Create User'}
            </h5>
            <button className="btn-close" onClick={() => onClose(false)} disabled={busy} />
          </div>

          <div className="modal-body">
            {error && <div className="alert alert-danger py-2">{error}</div>}

            {/* Username (create only) */}
            {!isEdit && (
              <div className="mb-3">
                <label className="form-label fw-semibold">Username</label>
                <input className="form-control" value={username} autoFocus
                       autoComplete="new-password"
                       onChange={e => setUsername(e.target.value)} />
                {username.length > 0 && !usernameValid && (
                  <div className="form-text text-danger">
                    Must be ≥ 2 chars and contain only letters, digits, dots, hyphens or underscores.
                  </div>
                )}
              </div>
            )}

            {/* Email */}
            <div className="mb-3">
              <label className="form-label fw-semibold">Email</label>
              <input className="form-control" type="email" value={email}
                     autoComplete="new-password"
                     autoFocus={isEdit}
                     onChange={e => setEmail(e.target.value)} />
            </div>

            {/* Administrator */}
            <div className="mb-3 form-check">
              <input className="form-check-input" type="checkbox" id="isAdmin"
                     checked={isAdmin} onChange={e => setIsAdmin(e.target.checked)} />
              <label className="form-check-label fw-semibold" htmlFor="isAdmin">Administrator</label>
            </div>

            {/* Password */}
            <div className="mb-3">
              <label className="form-label fw-semibold">
                {isEdit ? 'Change Password (or leave empty)' : 'Set Password'}
              </label>
              <input className="form-control" type="password" value={password}
                     autoComplete="new-password"
                     onChange={e => setPassword(e.target.value)} />
              {password.length > 0 && password.length < 8 && (
                <div className="form-text text-danger">Password must be at least 8 characters.</div>
              )}
            </div>
          </div>

          <div className="modal-footer">
            <button className="btn btn-secondary" onClick={() => onClose(false)} disabled={busy}>Cancel</button>
            <button className="btn btn-primary" onClick={save} disabled={busy || !canSave}>
              {busy && <span className="spinner-border spinner-border-sm me-2" />}Ok
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
