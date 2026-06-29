/**
 * UserForm — port of UserDialogComponent + user-form.html.
 *
 * Props:
 *   user      object|null   if set → edit mode
 *   onClose   fn(reload)
 */
import React, { useState } from 'react';
import { createUser, editUser } from '../../api/users';
import { rules, fieldClass, fieldError } from '../../lib/validate';

export default function UserForm({ user, onClose }) {
  const isEdit = !!user;

  const [username, setUsername] = useState(user?.username ?? '');
  const [email,    setEmail]    = useState(user?.email    ?? '');
  const [password, setPassword] = useState('');
  const [isAdmin,  setIsAdmin]  = useState(user?.is_admin ?? false);
  const [busy,     setBusy]     = useState(false);
  const [error,    setError]    = useState('');

  const [touched, setTouched] = useState({});
  const touch = f => setTouched(t => ({ ...t, [f]: true }));

  const errors = {
    username: isEdit ? '' : rules.name(username),
    email:    rules.email(email),
    password: rules.password(password, isEdit),
  };
  const canSave = Object.values(errors).every(e => !e);

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
                <input className={fieldClass(touched.username && errors.username)}
                       value={username} autoFocus autoComplete="new-password"
                       onChange={e => setUsername(e.target.value)}
                       onBlur={() => touch('username')} />
                {touched.username && errors.username && <div className="invalid-feedback">{errors.username}</div>}
              </div>
            )}

            {/* Email */}
            <div className="mb-3">
              <label className="form-label fw-semibold">Email</label>
              <input className={fieldClass(touched.email && errors.email)}
                     type="email" value={email}
                     autoComplete="new-password"
                     autoFocus={isEdit}
                     onChange={e => setEmail(e.target.value)}
                     onBlur={() => touch('email')} />
              {touched.email && errors.email && <div className="invalid-feedback">{errors.email}</div>}
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
              <input className={fieldClass(touched.password && errors.password)}
                     type="password" value={password}
                     autoComplete="new-password"
                     onChange={e => setPassword(e.target.value)}
                     onBlur={() => touch('password')} />
              {touched.password && errors.password && <div className="invalid-feedback">{errors.password}</div>}
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
