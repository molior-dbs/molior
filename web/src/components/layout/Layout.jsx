/**
 * Layout — app shell porting AppComponent from the Angular app.
 *
 * Structure (mirrors the Angular CSS grid):
 *   ┌─────────────────────────────────┐
 *   │  Topbar (logo · username · dot) │
 *   ├──────────┬──────────────────────┤
 *   │  Sidenav │  <Outlet />          │
 *   ├──────────┴──────────────────────┤
 *   │  Footer (version)               │
 *   └─────────────────────────────────┘
 *
 * Angular features ported:
 *   - Logo → /builds on click
 *   - Username + person icon → dropdown with Logout
 *   - WebSocket status dot (red / green)
 *   - Side nav with active-link highlight
 *   - Admin-only nav items hidden for non-admins
 *   - Maintenance mode hides nav for non-admins
 *   - Server version in footer from GET /api/status
 */
import React, { useEffect, useState } from 'react';
import { Outlet, NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { apiUrl, wsUrl } from '../../lib/base';
import moliorLogo from '../../assets/moliorlogo.png';

const PRIMARY = '#571845';

const NAV_ITEMS = [
  { path: '/builds',   icon: 'bi-journals',        label: 'Builds'   },
  { path: '/projects', icon: 'bi-collection',       label: 'Projects' },
  { path: '/mirrors',  icon: 'bi-folder-symlink',   label: 'Mirrors'  },
  { path: '/repos',    icon: 'bi-git',              label: 'Repos'    },

  { path: '/users',    icon: 'bi-people',           label: 'Accounts' },
];

const ADMIN_ITEMS = [
  { path: '/admin',    icon: 'bi-clipboard-data',   label: 'Admin'    },
  { path: '/about',    icon: 'bi-chat-square-dots', label: 'About'    },
];

export default function Layout() {
  const { currentUser, logout } = useAuth();
  const navigate = useNavigate();

  const [wsColor, setWsColor]             = useState('red');
  const [version, setVersion]             = useState('');
  const [maintenanceMode, setMaintenance] = useState(false);

  // Fetch server status (version + maintenance flag)
  useEffect(() => {
    fetch(apiUrl('/api/status'), { credentials: 'same-origin' })
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data) {
          setVersion(data.version_molior_server || '');
          setMaintenance(!!data.maintenance_mode);
        }
      })
      .catch(() => {});
  }, []);

  // WebSocket connection + status dot, with exponential-backoff reconnection.
  useEffect(() => {
    if (!currentUser) return;

    let ws;
    let retryTimer;
    let delay = 1000;          // start at 1 s, double on each failure up to 30 s
    let unmounted = false;

    function connect() {
      ws = new WebSocket(wsUrl('/api/websocket'));

      ws.onopen = () => {
        setWsColor('lightgreen');
        delay = 1000;          // reset backoff on a successful connection
      };

      ws.onclose = () => {
        setWsColor('red');
        if (!unmounted) {
          retryTimer = setTimeout(connect, delay);
          delay = Math.min(delay * 2, 30000);
        }
      };

      ws.onerror = () => {
        ws.close(); // triggers onclose which handles the retry
      };

      ws.onmessage = (evt) => {
        try {
          const data = JSON.parse(evt.data);
          // subject 1 = websocket, event 4 = connected
          if (data.subject === 1 && data.event === 4) setWsColor('lightgreen');
          if (data.status === 401) { handleLogout(); }
        } catch {}
      };
    }

    connect();

    return () => {
      unmounted = true;
      clearTimeout(retryTimer);
      ws?.close();
    };
  }, [currentUser]);

  async function handleLogout() {
    await logout();
    navigate('/login');
  }

  const isAdmin = currentUser?.is_admin;
  const showNav = isAdmin || !maintenanceMode;

  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: showNav ? '180px 1fr' : '1fr',
      gridTemplateRows: '42px 1fr 28px',
      gridTemplateAreas: showNav
        ? '"header header" "nav main" "footer footer"'
        : '"header" "main" "footer"',
      height: '100vh',
      overflow: 'hidden',
    }}>

      {/* ── Topbar ── */}
      <div style={{ gridArea: 'header', backgroundColor: PRIMARY, display: 'flex', alignItems: 'center', padding: '0 12px' }}>
        {/* Logo */}
        <img
          src={moliorLogo}
          alt="Molior"
          style={{ height: 32, cursor: 'pointer' }}
          onClick={() => navigate('/builds')}
        />

        {/* Right side: username + dot */}
        {currentUser && (
          <div className="ms-auto d-flex align-items-center gap-2">
            {/* WS status dot */}
            <span style={{
              display: 'inline-block', width: 10, height: 10,
              borderRadius: '50%', backgroundColor: wsColor,
            }} title={wsColor === 'lightgreen' ? 'Connected' : 'Disconnected'} />

            {/* User dropdown */}
            <div className="dropdown">
              <button
                className="btn btn-sm border-0 d-flex align-items-center gap-1"
                style={{ color: 'white', backgroundColor: 'transparent' }}
                data-bs-toggle="dropdown"
                aria-expanded="false"
              >
                <span style={{ fontSize: 14 }}>{currentUser.username}</span>
                <i className="bi bi-person" style={{ fontSize: 18 }} />
              </button>
              <ul className="dropdown-menu dropdown-menu-end">
                <li>
                  <button className="dropdown-item d-flex align-items-center gap-2" onClick={handleLogout}>
                    <i className="bi bi-box-arrow-right" />
                    Logout
                  </button>
                </li>
              </ul>
            </div>
          </div>
        )}
      </div>

      {/* ── Side nav ── */}
      {showNav && (
        <nav style={{ gridArea: 'nav', backgroundColor: '#fafafa', borderRight: '1px solid #e0e0e0', overflowY: 'auto' }}>
          <ul className="nav flex-column pt-1">
            {NAV_ITEMS.map(item => (
              <li key={item.path} className="nav-item">
                <NavLink
                  to={item.path}
                  className={({ isActive }) =>
                    `nav-link d-flex align-items-center gap-2 px-3 py-2${isActive ? ' active-nav' : ''}`
                  }
                  style={({ isActive }) => ({
                    color: isActive ? 'white' : '#333',
                    backgroundColor: isActive ? PRIMARY : 'transparent',
                    fontSize: 14,
                  })}
                >
                  <i className={`bi ${item.icon}`} />
                  {item.label}
                </NavLink>
              </li>
            ))}

            <li><hr className="my-1" /></li>

            {ADMIN_ITEMS.filter(item => item.path !== '/admin' || isAdmin).map(item => (
              <li key={item.path} className="nav-item">
                <NavLink
                  to={item.path}
                  className={({ isActive }) =>
                    `nav-link d-flex align-items-center gap-2 px-3 py-2${isActive ? ' active-nav' : ''}`
                  }
                  style={({ isActive }) => ({
                    color: isActive ? 'white' : '#333',
                    backgroundColor: isActive ? PRIMARY : 'transparent',
                    fontSize: 14,
                  })}
                >
                  <i className={`bi ${item.icon}`} />
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
      )}

      {/* ── Main content ── */}
      <main style={{ gridArea: 'main', overflowY: 'auto', display: 'flex', flexDirection: 'column' }}>
        <Outlet />
      </main>

      {/* ── Footer ── */}
      <footer style={{
        gridArea: 'footer',
        textAlign: 'center',
        fontSize: 12,
        color: '#888',
        borderTop: '1px solid #e0e0e0',
        lineHeight: '28px',
      }}>
        molior {version}
      </footer>
    </div>
  );
}
