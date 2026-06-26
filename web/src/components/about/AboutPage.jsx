/**
 * AboutPage — port of AboutComponent + about.html.
 *
 * Shows: intro text, documentation links, server version table,
 * APT repo public key (fetched from gpgurl), SSH public key.
 */
import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { fetchStatus } from '../../api/users';

const PRIMARY = '#571845';

export default function AboutPage() {
  const [status,  setStatus]  = useState(null);
  const [repoAsc, setRepoAsc] = useState('');
  const [error,   setError]   = useState('');

  useEffect(() => {
    fetchStatus()
      .then(async s => {
        setStatus(s);
        if (s.gpgurl) {
          try {
            const r = await fetch(s.gpgurl);
            if (r.ok) setRepoAsc(await r.text());
          } catch { /* gpg key optional */ }
        }
      })
      .catch(e => setError(e.message));
  }, []);

  return (
    <div className="p-3" style={{ maxWidth: 900 }}>
      <h1 className="mb-3 d-flex align-items-center gap-2" style={{ fontSize: 24, fontWeight: 500 }}>
        <i className="bi bi-question-circle" />About
      </h1>

      <h2 style={{ fontSize: 18, fontWeight: 600 }}>Molior — Debian Build System</h2>

      <p style={{ maxWidth: 700 }}>
        Molior is based on{' '}
        <a href="https://www.aptly.info/" target="_blank" rel="noreferrer noopener" style={{ color: PRIMARY }}>aptly</a>
        {' '}for managing Debian package repositories and{' '}
        <a href="https://wiki.debian.org/sbuild" target="_blank" rel="noreferrer noopener" style={{ color: PRIMARY }}>sbuild</a>
        {' '}for building Debian packages for multiple distributions and architectures.
      </p>

      <p style={{ maxWidth: 700 }}>Molior allows the following via WebUI, REST API or commandline tools:</p>
      <ul>
        <li>Manage Debian repository <Link to="/mirrors" style={{ color: PRIMARY }}>mirrors</Link></li>
        <li>Manage Debian repositories grouped in{' '}
          <Link to="/projects" style={{ color: PRIMARY }}>projects and versions</Link></li>
        <li>Manage project dependencies between base mirrors and other projects</li>
        <li>Provide <Link to="/nodes" style={{ color: PRIMARY }}>build nodes</Link> (amd64, arm64) on VMs or bare metal for running sbuild</li>
        <li>
          <Link to="/builds" style={{ color: PRIMARY }}>Build</Link> debianized{' '}
          <Link to="/repos" style={{ color: PRIMARY }}>git repositories</Link> for multiple projects and architectures (i386, amd64, armhf, arm64)
        </li>
        <li>Create project deployments (ISO Installers, VM images, containers, …)</li>
      </ul>

      <h2 style={{ fontSize: 18, fontWeight: 600 }} className="mt-4">Documentation</h2>
      <ul>
        <li>
          <a href="https://github.com/molior-dbs/molior" target="_blank" rel="noreferrer noopener"
             style={{ color: PRIMARY }}>Source code hosted on GitHub</a>
        </li>
        <li>
          <a href="/api/doc" target="_blank" rel="noreferrer noopener"
             style={{ color: PRIMARY }}>REST API Documentation (swagger)</a>
        </li>
      </ul>

      <h2 style={{ fontSize: 18, fontWeight: 600 }} className="mt-4">Versions</h2>
      {error && <div className="alert alert-danger py-2">Failed to load status: {error}</div>}
      <table style={{ borderCollapse: 'collapse', marginTop: 10 }}>
        <tbody>
          <tr>
            <td style={{ paddingRight: 10, paddingBottom: 5 }}>
              <ul style={{ marginTop: 0 }}><li style={{ marginBottom: 0 }}>Molior Server</li></ul>
            </td>
            <td style={{ paddingBottom: 5 }}>
              {status ? status.version_molior_server : <span className="text-muted">—</span>}
            </td>
          </tr>
          <tr>
            <td style={{ paddingRight: 10, paddingBottom: 5 }}>
              <ul style={{ marginTop: 0 }}><li style={{ marginBottom: 0 }}>Aptly Server</li></ul>
            </td>
            <td style={{ paddingBottom: 5 }}>
              {status ? status.version_aptly : <span className="text-muted">—</span>}
            </td>
          </tr>
        </tbody>
      </table>

      <div className="d-flex gap-5 mt-4 flex-wrap">
        {/* APT Repo Public Key */}
        <div style={{ maxWidth: 485 }}>
          <h2 style={{ fontSize: 18, fontWeight: 600 }}>APT Repo Public Key</h2>
          <p>
            Molior apt repositories can be verified with the following{' '}
            {status?.gpgurl
              ? <a href={status.gpgurl} style={{ color: PRIMARY }}>GPG public key</a>
              : 'GPG public key'}
            :
          </p>
          {repoAsc
            ? <pre className="bg-light p-2 rounded" style={{ fontSize: 11, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{repoAsc}</pre>
            : <span className="text-muted" style={{ fontSize: 13 }}>—</span>
          }
        </div>

        {/* SSH Public Key */}
        <div style={{ maxWidth: 400 }}>
          <h2 style={{ fontSize: 18, fontWeight: 600 }}>SSH Public Key</h2>
          <p>Molior needs read permissions on git repositories for the following SSH public key:</p>
          {status?.sshkey
            ? <pre className="bg-light p-2 rounded" style={{ fontSize: 11, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{status.sshkey}</pre>
            : <span className="text-muted" style={{ fontSize: 13 }}>—</span>
          }
        </div>
      </div>
    </div>
  );
}
