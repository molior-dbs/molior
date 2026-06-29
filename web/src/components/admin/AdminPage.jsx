/**
 * AdminPage — port of AdminComponent + AdminMaintenanceComponent + AdminRetentionComponent.
 *
 * Route: /admin  (admin-only)
 * Tabs:
 *   Cleanup Job      → /admin          (reads/writes GET|PUT /api2/cleanup)
 *   Package Retention → /retention     (reads/writes GET|PUT /api2/retention)
 *   Maintenance      → /maintenance_config (reads/writes GET|PUT /api2/maintenance)
 *
 * Each tab shows the current settings and opens an inline edit modal on "Edit Settings".
 */
import React, { useState, useEffect } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import {
  fetchCleanup,    saveCleanup,
  fetchRetention,  saveRetention,
  fetchMaintenance, saveMaintenance,
} from '../../api/admin';

const PRIMARY = '#571845';
const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const HOURS    = Array.from({ length: 24 }, (_, i) => i);
const MINUTES  = Array.from({ length: 12 }, (_, i) => i * 5);

function pad(n) { return String(n).padStart(2, '0'); }

// ── Shared: simple section card ───────────────────────────────────────────────
function Card({ children }) {
  return (
    <div className="card card-body py-3 px-4 mb-3" style={{ maxWidth: 600, fontSize: 14 }}>
      {children}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Tab: Cleanup Job
// ─────────────────────────────────────────────────────────────────────────────
function CleanupTab() {
  const [data,    setData]    = useState(null);
  const [error,   setError]   = useState('');
  const [modal,   setModal]   = useState(false);

  function load() {
    setError('');
    fetchCleanup()
      .then(setData)
      .catch(e => setError(e.message));
  }
  useEffect(load, []);

  if (error) return <div className="alert alert-danger py-2">{error}</div>;
  if (!data)  return <div className="text-muted py-3">Loading…</div>;

  const activeDays = typeof data.cleanup_weekdays === 'string'
    ? data.cleanup_weekdays.split(',').map(s => s.trim()).filter(Boolean)
    : (data.cleanup_weekdays ?? []);

  return (
    <>
      {modal && (
        <CleanupModal
          initial={{
            cleanupActive:   data.cleanup_active === 'true' || data.cleanup_active === true,
            cleanupTime:     data.cleanup_time ?? '00:00',
            cleanupWeekdays: activeDays,
          }}
          onClose={saved => {
            setModal(false);
            if (saved) load();
          }}
        />
      )}

      <h2 style={{ fontSize: 18, fontWeight: 600 }} className="mb-3">Configuration for the cleanup job</h2>
      <Card>
        <table style={{ borderCollapse: 'collapse', width: '100%' }}>
          <tbody>
            <tr>
              <td className="pe-4 py-1" style={{ whiteSpace: 'nowrap' }}><strong>Cleanup Active</strong></td>
              <td className="py-1">
                <i className={`bi ${data.cleanup_active === 'true' || data.cleanup_active === true ? 'bi-check-lg text-success' : 'bi-dash text-muted'}`} />
              </td>
            </tr>
            <tr>
              <td className="pe-4 py-1"><strong>Time</strong></td>
              <td className="py-1 font-monospace">{data.cleanup_time ?? '—'}</td>
            </tr>
            <tr>
              <td className="pe-4 py-1" style={{ verticalAlign: 'top' }}><strong>Days</strong></td>
              <td className="py-1">
                {WEEKDAYS.map(day => (
                  <span key={day} className="me-3 d-inline-flex align-items-center gap-1" style={{ fontSize: 13 }}>
                    <i className={`bi ${activeDays.includes(day) ? 'bi-check-square-fill text-success' : 'bi-square text-muted'}`} />
                    {day}
                  </span>
                ))}
              </td>
            </tr>
          </tbody>
        </table>
      </Card>
      <button className="btn btn-primary" onClick={() => setModal(true)}>
        <i className="bi bi-pencil me-2" />Edit Settings
      </button>
    </>
  );
}

function CleanupModal({ initial, onClose }) {
  const [active,   setActive]   = useState(initial.cleanupActive);
  const [days,     setDays]     = useState(initial.cleanupWeekdays);
  const [hour,     setHour]     = useState(() => {
    const [h] = (initial.cleanupTime ?? '00:00').split(':').map(Number);
    return h ?? 0;
  });
  const [minute, setMinute] = useState(() => {
    const [, m] = (initial.cleanupTime ?? '00:00').split(':').map(Number);
    return m ?? 0;
  });
  const [busy,  setBusy]  = useState(false);
  const [error, setError] = useState('');

  function toggleDay(day) {
    setDays(prev => prev.includes(day) ? prev.filter(d => d !== day) : [...prev, day]);
  }

  async function handleSave() {
    setBusy(true); setError('');
    try {
      await saveCleanup({
        cleanupActive:   active,
        cleanupWeekdays: days.join(','),
        cleanupTime:     `${pad(hour)}:${pad(minute)}`,
      });
      onClose(true);
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  return (
    <div className="modal fade show d-block" tabIndex="-1"
         style={{ backgroundColor: 'rgba(0,0,0,.4)' }}>
      <div className="modal-dialog modal-dialog-centered">
        <div className="modal-content">
          <div className="modal-header">
            <h5 className="modal-title">Edit Settings — Cleanup Job</h5>
            <button className="btn-close" onClick={() => onClose(false)} disabled={busy} />
          </div>
          <div className="modal-body">
            {error && <div className="alert alert-danger py-2">{error}</div>}

            {/* Time selector */}
            <div className="mb-3">
              <label className="form-label fw-semibold">Time</label>
              <div className="d-flex align-items-center gap-2">
                <select className="form-select w-auto" value={hour}
                        onChange={e => setHour(Number(e.target.value))}>
                  {HOURS.map(h => <option key={h} value={h}>{pad(h)}</option>)}
                </select>
                <span>:</span>
                <select className="form-select w-auto" value={minute}
                        onChange={e => setMinute(Number(e.target.value))}>
                  {MINUTES.map(m => <option key={m} value={m}>{pad(m)}</option>)}
                </select>
              </div>
            </div>

            {/* Weekday checkboxes */}
            <div className="mb-3">
              <label className="form-label fw-semibold">Days</label>
              <div className="d-flex flex-wrap gap-3">
                {WEEKDAYS.map(day => (
                  <div className="form-check" key={day}>
                    <input className="form-check-input" type="checkbox" id={`day-${day}`}
                           checked={days.includes(day)}
                           onChange={() => toggleDay(day)} />
                    <label className="form-check-label" htmlFor={`day-${day}`}>{day}</label>
                  </div>
                ))}
              </div>
            </div>

            {/* Active toggle */}
            <div className="form-check">
              <input className="form-check-input" type="checkbox" id="cleanup-active"
                     checked={active} onChange={e => setActive(e.target.checked)} />
              <label className="form-check-label fw-semibold" htmlFor="cleanup-active">Cleanup Active</label>
            </div>
          </div>
          <div className="modal-footer">
            <button className="btn btn-secondary" onClick={() => onClose(false)} disabled={busy}>Cancel</button>
            <button className="btn btn-primary" onClick={handleSave} disabled={busy}>
              {busy && <span className="spinner-border spinner-border-sm me-2" />}Save
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Tab: Package Retention
// ─────────────────────────────────────────────────────────────────────────────
function RetentionTab() {
  const [data,  setData]  = useState(null);
  const [error, setError] = useState('');
  const [modal, setModal] = useState(false);

  function load() {
    setError('');
    fetchRetention()
      .then(setData)
      .catch(e => setError(e.message));
  }
  useEffect(load, []);

  if (error) return <div className="alert alert-danger py-2">{error}</div>;
  if (!data)  return <div className="text-muted py-3">Loading…</div>;

  return (
    <>
      {modal && (
        <RetentionModal
          initial={{
            retentionSuccessfulBuilds: data.retention_successful_builds ?? 0,
            retentionFailedBuilds:     data.retention_failed_builds     ?? 0,
          }}
          onClose={saved => { setModal(false); if (saved) load(); }}
        />
      )}

      <h2 style={{ fontSize: 18, fontWeight: 600 }} className="mb-3">Configuration of Package Retention</h2>
      <Card>
        <table style={{ borderCollapse: 'collapse', width: '100%' }}>
          <tbody>
            <tr>
              <td className="pe-4 py-2" style={{ verticalAlign: 'top' }}>
                <strong>Successful Builds</strong>
                <div className="text-muted" style={{ fontSize: 12 }}>Max builds per source repo to retain (0 = disabled)</div>
              </td>
              <td className="py-2">
                <span className="badge bg-secondary fs-6">{data.retention_successful_builds ?? 0}</span>
              </td>
            </tr>
            <tr>
              <td className="pe-4 py-2" style={{ verticalAlign: 'top' }}>
                <strong>Failed Builds</strong>
                <div className="text-muted" style={{ fontSize: 12 }}>Days to keep failed builds (0 = disabled)</div>
              </td>
              <td className="py-2">
                <span className="badge bg-secondary fs-6">{data.retention_failed_builds ?? 0}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </Card>
      <button className="btn btn-primary" onClick={() => setModal(true)}>
        <i className="bi bi-pencil me-2" />Edit Settings
      </button>
    </>
  );
}

function RetentionModal({ initial, onClose }) {
  const [enableSuccessful, setEnableSuccessful] = useState(initial.retentionSuccessfulBuilds > 0);
  const [enableFailed,     setEnableFailed]     = useState(initial.retentionFailedBuilds > 0);
  const [successful, setSuccessful] = useState(initial.retentionSuccessfulBuilds);
  const [failed,     setFailed]     = useState(initial.retentionFailedBuilds);
  const [busy,  setBusy]  = useState(false);
  const [error, setError] = useState('');

  async function handleSave() {
    setBusy(true); setError('');
    try {
      await saveRetention({
        retentionSuccessfulBuilds: enableSuccessful ? Number(successful) : 0,
        retentionFailedBuilds:     enableFailed     ? Number(failed)     : 0,
      });
      onClose(true);
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  return (
    <div className="modal fade show d-block" tabIndex="-1"
         style={{ backgroundColor: 'rgba(0,0,0,.4)' }}>
      <div className="modal-dialog modal-dialog-centered">
        <div className="modal-content">
          <div className="modal-header">
            <h5 className="modal-title">Edit Package Retention Policy</h5>
            <button className="btn-close" onClick={() => onClose(false)} disabled={busy} />
          </div>
          <div className="modal-body">
            {error && <div className="alert alert-danger py-2">{error}</div>}

            {/* Successful builds */}
            <div className="mb-4">
              <div className="form-check mb-2">
                <input className="form-check-input" type="checkbox" id="enable-successful"
                       checked={enableSuccessful}
                       onChange={e => {
                         setEnableSuccessful(e.target.checked);
                         if (!e.target.checked) setSuccessful(0);
                         else setSuccessful(initial.retentionSuccessfulBuilds || 1);
                       }} />
                <label className="form-check-label fw-semibold" htmlFor="enable-successful">
                  Enable Retention for Successful Builds
                </label>
              </div>
              <label className="form-label text-muted" style={{ fontSize: 13 }}>
                Max successful builds per source repository to retain:
              </label>
              <input type="number" className="form-control w-auto" min="0"
                     value={successful}
                     disabled={!enableSuccessful}
                     onChange={e => setSuccessful(e.target.value)} />
            </div>

            {/* Failed builds */}
            <div>
              <div className="form-check mb-2">
                <input className="form-check-input" type="checkbox" id="enable-failed"
                       checked={enableFailed}
                       onChange={e => {
                         setEnableFailed(e.target.checked);
                         if (!e.target.checked) setFailed(0);
                         else setFailed(initial.retentionFailedBuilds || 1);
                       }} />
                <label className="form-check-label fw-semibold" htmlFor="enable-failed">
                  Enable Retention for Failed Builds
                </label>
              </div>
              <label className="form-label text-muted" style={{ fontSize: 13 }}>
                Days to keep failed builds:
              </label>
              <input type="number" className="form-control w-auto" min="0"
                     value={failed}
                     disabled={!enableFailed}
                     onChange={e => setFailed(e.target.value)} />
            </div>
          </div>
          <div className="modal-footer">
            <button className="btn btn-secondary" onClick={() => onClose(false)} disabled={busy}>Cancel</button>
            <button className="btn btn-primary" onClick={handleSave} disabled={busy}>
              {busy && <span className="spinner-border spinner-border-sm me-2" />}Save
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Tab: Maintenance
// ─────────────────────────────────────────────────────────────────────────────
function MaintenanceTab() {
  const [data,  setData]  = useState(null);
  const [error, setError] = useState('');
  const [modal, setModal] = useState(false);

  function load() {
    setError('');
    fetchMaintenance()
      .then(setData)
      .catch(e => setError(e.message));
  }
  useEffect(load, []);

  if (error) return <div className="alert alert-danger py-2">{error}</div>;
  if (!data)  return <div className="text-muted py-3">Loading…</div>;

  const modeOn = data.maintenance_mode === 'true' || data.maintenance_mode === true;

  return (
    <>
      {modal && (
        <MaintenanceModal
          initial={{
            maintenanceMode:    modeOn,
            maintenanceMessage: data.maintenance_message ?? '',
          }}
          onClose={saved => { setModal(false); if (saved) load(); }}
        />
      )}

      <h2 style={{ fontSize: 18, fontWeight: 600 }} className="mb-3">Configuration of Maintenance Mode</h2>
      <Card>
        <table style={{ borderCollapse: 'collapse', width: '100%' }}>
          <tbody>
            <tr>
              <td className="pe-4 py-1"><strong>Maintenance Mode</strong></td>
              <td className="py-1">
                <i className={`bi ${modeOn ? 'bi-check-lg text-success' : 'bi-dash text-muted'}`} />
                {modeOn
                  ? <span className="ms-2 badge bg-warning text-dark">Enabled</span>
                  : <span className="ms-2 text-muted">Disabled</span>}
              </td>
            </tr>
            <tr>
              <td className="pe-4 py-1"><strong>Message</strong></td>
              <td className="py-1">
                {data.maintenance_message
                  ? <em>{data.maintenance_message}</em>
                  : <span className="text-muted">—</span>}
              </td>
            </tr>
          </tbody>
        </table>
      </Card>
      <button className="btn btn-primary" onClick={() => setModal(true)}>
        <i className="bi bi-pencil me-2" />Edit Settings
      </button>
    </>
  );
}

function MaintenanceModal({ initial, onClose }) {
  const [modeOn,  setModeOn]  = useState(initial.maintenanceMode);
  const [message, setMessage] = useState(initial.maintenanceMessage);
  const [busy,    setBusy]    = useState(false);
  const [error,   setError]   = useState('');

  async function handleSave() {
    if (modeOn && !message.trim()) return;
    setBusy(true); setError('');
    try {
      await saveMaintenance({ maintenanceMode: modeOn, maintenanceMessage: message });
      onClose(true);
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  return (
    <div className="modal fade show d-block" tabIndex="-1"
         style={{ backgroundColor: 'rgba(0,0,0,.4)' }}>
      <div className="modal-dialog modal-dialog-centered">
        <div className="modal-content">
          <div className="modal-header">
            <h5 className="modal-title">Edit Maintenance Settings</h5>
            <button className="btn-close" onClick={() => onClose(false)} disabled={busy} />
          </div>
          <div className="modal-body">
            {error && <div className="alert alert-danger py-2">{error}</div>}

            <div className="form-check mb-3">
              <input className="form-check-input" type="checkbox" id="maint-mode"
                     checked={modeOn}
                     onChange={e => {
                       setModeOn(e.target.checked);
                       if (!e.target.checked) setMessage('');
                     }} />
              <label className="form-check-label fw-semibold" htmlFor="maint-mode">
                Maintenance mode enabled
              </label>
            </div>

            <div>
              <label className="form-label fw-semibold">Maintenance message</label>
              <input
                className="form-control"
                value={message}
                disabled={!modeOn}
                placeholder="e.g. Scheduled maintenance — back at 14:00"
                onChange={e => setMessage(e.target.value)}
              />
              {modeOn && !message.trim() && (
                <div className="text-danger mt-1" style={{ fontSize: 12 }}>Message is required when maintenance mode is enabled.</div>
              )}
            </div>
          </div>
          <div className="modal-footer">
            <button className="btn btn-secondary" onClick={() => onClose(false)} disabled={busy}>Cancel</button>
            <button className="btn btn-primary" onClick={handleSave}
                    disabled={busy || (modeOn && !message.trim())}>
              {busy && <span className="spinner-border spinner-border-sm me-2" />}Save
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Root: AdminPage
// ─────────────────────────────────────────────────────────────────────────────
export default function AdminPage() {
  const location = useLocation();
  const TABS = [
    { label: 'Cleanup Job',        path: '/admin' },
    { label: 'Package Retention',  path: '/retention' },
    { label: 'Maintenance',        path: '/maintenance_config' },
  ];

  return (
    <div className="p-3">
      <h1 className="mb-1 d-flex align-items-center gap-2" style={{ fontSize: 24, fontWeight: 500 }}>
        <i className="bi bi-clipboard-data" />Admin
      </h1>
      <p className="text-muted mb-3" style={{ fontSize: 14 }}>Configuration page for settings</p>

      {/* Tab bar — uses top-level routes so each tab has its own URL */}
      <ul className="nav nav-tabs mb-4">
        {TABS.map(({ label, path }) => (
          <li className="nav-item" key={path}>
            <NavLink
              className={({ isActive }) => `nav-link${isActive ? ' active' : ' text-muted'}`}
              to={path}
              end={path === '/admin'}
            >
              {label}
            </NavLink>
          </li>
        ))}
      </ul>

      {location.pathname.startsWith('/retention')         ? <RetentionTab />   :
       location.pathname.startsWith('/maintenance_config') ? <MaintenanceTab /> :
       <CleanupTab />}
    </div>
  );
}
