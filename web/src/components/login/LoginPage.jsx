/**
 * LoginPage — React + Bootstrap port of the Angular login component.
 *
 * Angular original: oldweb/app/components/login/
 *
 * What changed:
 *  - Angular Material (mat-card, mat-form-field, mat-icon) → Bootstrap 5 cards / form-control
 *  - Angular FormGroup / Validators → React controlled state + HTML5 required
 *  - Angular AlertService → local error state (can be wired to a global AlertContext later)
 *  - Angular Router.navigateByUrl → react-router-dom useNavigate
 *  - MoliorService.connect() (WebSocket) → called from App-level effect after login
 *    (keeps this component simple; the WS hook lives near the router outlet)
 *
 * Brand colour: #571845  (same as $primary-color in the old SCSS)
 */
import React, { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import moliorLogo from '../../assets/moliorlogo-large.png';

const PRIMARY = '#571845';

export default function LoginPage() {
  const { currentUser, login } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  // If already logged in, redirect immediately (mirrors Angular constructor guard)
  if (currentUser) {
    const returnUrl = searchParams.get('returnUrl') || '/builds';
    navigate(returnUrl, { replace: true });
  }

  const [username, setUsername]   = useState('');
  const [password, setPassword]   = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [loading, setLoading]     = useState(false);
  const [error, setError]         = useState('');

  const usernameInvalid = submitted && !username.trim();
  const passwordInvalid = submitted && !password;

  async function handleSubmit(e) {
    e.preventDefault();
    setSubmitted(true);
    setError('');

    if (!username.trim() || !password) return;

    setLoading(true);
    try {
      await login(username, password);
      const returnUrl = searchParams.get('returnUrl') || '/builds';
      navigate(returnUrl, { replace: true });
    } catch (err) {
      setError(err.message || 'Login failed');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      className="d-flex flex-column justify-content-center align-items-center vh-100"
      style={{ backgroundColor: '#f5f5f5' }}
    >
      <div className="card shadow-sm" style={{ width: '22rem' }}>
        {/* Header — logo, matching the Angular mat-card-header */}
        <div className="card-header text-center py-4" style={{ backgroundColor: PRIMARY }}>
          <img src={moliorLogo} alt="Molior" style={{ maxWidth: '180px' }} />
        </div>

        <div className="card-body px-4 pb-4 pt-3">
          {/* Global error alert — mirrors Angular's AlertService display */}
          {error && (
            <div className="alert alert-danger py-2 mb-3" role="alert">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} noValidate>
            {/* Username field */}
            <div className="mb-3">
              <label htmlFor="username" className="form-label fw-semibold">
                Username
              </label>
              <div className="input-group">
                <input
                  id="username"
                  type="text"
                  autoComplete="username"
                  className={`form-control${usernameInvalid ? ' is-invalid' : ''}`}
                  value={username}
                  onChange={e => setUsername(e.target.value)}
                  disabled={loading}
                />
                {/* Bootstrap icon equivalent of mat-icon perm_identity */}
                <span className="input-group-text">
                  <i className="bi bi-person" aria-hidden="true" />
                </span>
                {usernameInvalid && (
                  <div className="invalid-feedback">Username is required</div>
                )}
              </div>
            </div>

            {/* Password field */}
            <div className="mb-4">
              <label htmlFor="password" className="form-label fw-semibold">
                Password
              </label>
              <div className="input-group">
                <input
                  id="password"
                  type="password"
                  autoComplete="current-password"
                  className={`form-control${passwordInvalid ? ' is-invalid' : ''}`}
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  disabled={loading}
                />
                {/* Bootstrap icon equivalent of mat-icon lock */}
                <span className="input-group-text">
                  <i className="bi bi-lock" aria-hidden="true" />
                </span>
                {passwordInvalid && (
                  <div className="invalid-feedback">Password is required</div>
                )}
              </div>
            </div>

            {/* Submit button — float right, matches Angular mat-raised-button */}
            <div className="d-flex justify-content-end">
              <button
                type="submit"
                className="btn"
                style={{ backgroundColor: PRIMARY, color: 'white', minWidth: '80px' }}
                disabled={loading}
              >
                {loading && (
                  <span
                    className="spinner-border spinner-border-sm me-2"
                    role="status"
                    aria-hidden="true"
                  />
                )}
                Login
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
