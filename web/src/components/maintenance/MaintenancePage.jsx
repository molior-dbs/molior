/**
 * MaintenancePage — port of MaintenanceComponent + maintenance.html.
 *
 * Route: /maintenance  (public — no auth required)
 * Shown to non-admin users when maintenance mode is active.
 * Fetches the maintenance message from GET /api2/maintenance and displays it.
 * Admins can click through to the Admin page.
 */
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchMaintenance } from '../../api/admin';
import moliorLogo from '../../assets/moliorlogo-large.png';

const PRIMARY = '#571845';

export default function MaintenancePage() {
  const navigate = useNavigate();
  const [message, setMessage] = useState('');

  useEffect(() => {
    fetchMaintenance()
      .then(data => setMessage(data?.maintenance_message ?? ''))
      .catch(() => {});
  }, []);

  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: '#f8f9fa',
      gap: 24,
      padding: 32,
    }}>
      <img src={moliorLogo} alt="Molior" style={{ height: 80, opacity: 0.85 }} />

      <div className="text-center">
        <i className="bi bi-cone-striped" style={{ fontSize: 48, color: PRIMARY }} />
        <h1 style={{ fontSize: 28, fontWeight: 600, marginTop: 12 }}>Under Maintenance</h1>
        {message && (
          <p className="text-muted mt-2" style={{ fontSize: 16, maxWidth: 480 }}>{message}</p>
        )}
      </div>

      <button
        className="btn btn-outline-secondary"
        onClick={() => navigate('/admin')}
        style={{ fontSize: 14 }}
      >
        <i className="bi bi-clipboard-data me-2" />
        Go to Admin Page
      </button>
    </div>
  );
}
