/**
 * PVRepoDetailPage — port of ProjectversionRepoComponent + projectversion-repo-info.html
 *
 * Route: /project/:name/:version/repo/:repoId
 *
 * Shows the detail view for a single source repository within a project version:
 *   - Breadcrumb header: Project / Version / repo / id
 *   - Info card: name, URL, state, architectures, run_lintian
 *   - Actions menu: Edit, Delete (from PV), Build, Trigger, Re-clone
 *
 * Note: The "Post Build Hooks" section existed in the Angular original but the
 * server has no hooks endpoint, so it is intentionally omitted here.
 */
import React, { useState, useEffect } from 'react';
import { useParams, useNavigate, NavLink } from 'react-router-dom';
import {
  fetchPVRepo,
  editRepository,
  removeRepository,
  buildRepository,
  recloneRepository,
  triggerBuild,
} from '../../api/projectversions';
import ConfirmModal from '../build/ConfirmModal';

const PRIMARY = '#571845';

// ── State icon ────────────────────────────────────────────────────────────────
function stateIcon(state) {
  switch (state) {
    case 'ready': return 'bi-check-lg text-success';
    case 'busy':  return 'bi-arrow-repeat rotating text-primary';
    case 'error': return 'bi-x-lg text-danger';
    default:      return 'bi-three-dots text-muted';
  }
}

// ── Edit Repository modal ──────────────────────────────────────────────────────
const ARCH_OPTIONS = ['amd64', 'arm64', 'i386', 'armhf'];

function EditRepoModal({ projectName, versionName, repo, onClose }) {
  const [architectures, setArchitectures] = useState(repo.architectures ?? []);
  const [runLintian,    setRunLintian]    = useState(repo.run_lintian ?? false);
  const [busy,          setBusy]          = useState(false);
  const [error,         setError]         = useState('');

  function toggleArch(arch) {
    setArchitectures(prev =>
      prev.includes(arch) ? prev.filter(a => a !== arch) : [...prev, arch]
    );
  }

  async function handleSave() {
    if (architectures.length === 0) { setError('Select at least one architecture.'); return; }
    setBusy(true); setError('');
    try {
      await editRepository(projectName, versionName, repo.id, architectures, runLintian);
      onClose(true);
    } catch (e) { setError(e.message); setBusy(false); }
  }

  return (
    <div className="modal fade show d-block" tabIndex="-1"
         style={{ backgroundColor: 'rgba(0,0,0,.4)' }}>
      <div className="modal-dialog modal-dialog-centered">
        <div className="modal-content">
          <div className="modal-header">
            <h5 className="modal-title">Edit Source Repository</h5>
            <button className="btn-close" onClick={() => onClose(false)} disabled={busy} />
          </div>
          <div className="modal-body">
            {error && <div className="alert alert-danger py-2">{error}</div>}
            <div className="mb-3">
              <label className="form-label fw-semibold">URL</label>
              <div className="form-control-plaintext text-muted" style={{ fontFamily: 'monospace', fontSize: 13 }}>
                {repo.url}
              </div>
            </div>
            <div className="mb-3">
              <label className="form-label fw-semibold">Architectures</label>
              <div className="d-flex gap-3 flex-wrap">
                {ARCH_OPTIONS.map(arch => (
                  <div key={arch} className="form-check">
                    <input
                      className="form-check-input" type="checkbox" id={`arch-${arch}`}
                      checked={architectures.includes(arch)}
                      onChange={() => toggleArch(arch)}
                    />
                    <label className="form-check-label" htmlFor={`arch-${arch}`}>{arch}</label>
                  </div>
                ))}
              </div>
            </div>
            <div className="form-check">
              <input
                className="form-check-input" type="checkbox" id="run-lintian"
                checked={runLintian}
                onChange={e => setRunLintian(e.target.checked)}
              />
              <label className="form-check-label" htmlFor="run-lintian">Run lintian</label>
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

// ── Trigger Build modal ────────────────────────────────────────────────────────
function TriggerModal({ projectName, versionName, repo, onClose }) {
  const [gitref, setGitref] = useState('');
  const [busy,   setBusy]   = useState(false);
  const [error,  setError]  = useState('');

  async function handleSave() {
    if (!gitref.trim()) return;
    setBusy(true); setError('');
    try {
      await triggerBuild(projectName, versionName, repo.id, gitref.trim());
      onClose(true);
    } catch (e) { setError(e.message); setBusy(false); }
  }

  return (
    <div className="modal fade show d-block" tabIndex="-1"
         style={{ backgroundColor: 'rgba(0,0,0,.4)' }}>
      <div className="modal-dialog modal-dialog-centered">
        <div className="modal-content">
          <div className="modal-header">
            <h5 className="modal-title">Trigger Build</h5>
            <button className="btn-close" onClick={() => onClose(false)} disabled={busy} />
          </div>
          <div className="modal-body">
            {error && <div className="alert alert-danger py-2">{error}</div>}
            <p className="mb-2 text-muted" style={{ fontSize: 13 }}>
              Trigger a CI build for <code>{repo.url}</code>
            </p>
            <label className="form-label fw-semibold">Git Reference</label>
            <p className="text-muted small mb-1">Specify a git tag, branch or commit hash to build:</p>
            <input
              className="form-control" autoFocus
              placeholder="e.g. main, v1.2.3, abc1234"
              value={gitref}
              onChange={e => setGitref(e.target.value)}
            />
          </div>
          <div className="modal-footer">
            <button className="btn btn-secondary" onClick={() => onClose(false)} disabled={busy}>Cancel</button>
            <button className="btn btn-primary" onClick={handleSave} disabled={busy || !gitref.trim()}>
              {busy && <span className="spinner-border spinner-border-sm me-2" />}Trigger
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Root component ─────────────────────────────────────────────────────────────
export default function PVRepoDetailPage() {
  const { name, version, repoId } = useParams();
  const navigate = useNavigate();

  const [repo,      setRepo]      = useState(null);
  const [loadError, setLoadError] = useState('');
  const [modal,     setModal]     = useState(null);

  const pvBase = `/project/${name}/${version}`;

  function loadRepo() {
    fetchPVRepo(name, version, repoId)
      .then(setRepo)
      .catch(e => setLoadError(e.message));
  }

  useEffect(() => { loadRepo(); }, [name, version, repoId]);

  function closeModal(didChange) {
    setModal(null);
    if (didChange) loadRepo();
  }

  return (
    <div className="p-3">

      {/* ── Modals ── */}
      {modal?.type === 'edit' && repo && (
        <EditRepoModal
          projectName={name} versionName={version} repo={repo}
          onClose={closeModal}
        />
      )}
      {modal?.type === 'trigger' && repo && (
        <TriggerModal
          projectName={name} versionName={version} repo={repo}
          onClose={closeModal}
        />
      )}
      {modal?.type === 'delete' && repo && (
        <ConfirmModal
          title="Remove Source Repository"
          body={
            <span>
              Remove <strong>{repo.name}</strong> from{' '}
              <strong>{name}/{version}</strong>? The repository itself will not be deleted.
            </span>
          }
          onConfirm={() => removeRepository(name, version, repo.id)}
          onClose={didChange => {
            setModal(null);
            if (didChange) navigate(`${pvBase}/repos`);
          }}
        />
      )}
      {modal?.type === 'reclone' && repo && (
        <ConfirmModal
          title="Re-clone Source Repository"
          body="The source repository will be re-cloned. Do you want to continue?"
          onConfirm={() => recloneRepository(name, version, repo.id)}
          onClose={closeModal}
        />
      )}

      {/* ── Breadcrumb header ── */}
      {loadError && (
        <div className="alert alert-danger py-2">Failed to load repository: {loadError}</div>
      )}

      <div className="d-flex align-items-center mb-3 gap-2">
        <h1 className="mb-0 d-flex align-items-center gap-1 flex-wrap" style={{ fontSize: 22, fontWeight: 500 }}>
          <i className="bi bi-collection me-1" />
          <NavLink to={`/project/${name}`} style={{ color: 'inherit', textDecoration: 'none' }}>{name}</NavLink>
          <span className="text-muted fw-normal">/</span>
          <NavLink to={`${pvBase}/repos`} style={{ color: 'inherit', textDecoration: 'none' }}>{version}</NavLink>
          <span className="text-muted fw-normal">/repo/</span>
          <span>{repo ? repo.name : `#${repoId}`}</span>
          {repo && (
            <i className={`bi ${stateIcon(repo.state)} ms-1`} title={repo.state} style={{ fontSize: 18 }} />
          )}
        </h1>

        {repo && (
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
                <button className="dropdown-item text-danger" onClick={() => setModal({ type: 'delete' })}>
                  <i className="bi bi-trash me-2" />Delete
                </button>
              </li>
              <li><hr className="dropdown-divider" /></li>
              <li>
                <button className="dropdown-item" onClick={() => buildRepository(name, version, repo.id)}>
                  <i className="bi bi-arrow-repeat me-2" />Check for new builds
                </button>
              </li>
              <li>
                <button className="dropdown-item" onClick={() => setModal({ type: 'trigger' })}>
                  <i className="bi bi-play me-2" />Create CI build
                </button>
              </li>
              <li>
                <button className="dropdown-item" onClick={() => setModal({ type: 'reclone' })}>
                  <i className="bi bi-arrow-down-up me-2" />Re-clone
                </button>
              </li>
            </ul>
          </div>
        )}
      </div>

      {/* ── Info card ── */}
      {repo && (
        <div className="card card-body mb-3 py-2 px-3" style={{ fontSize: 13 }}>
          <table style={{ borderCollapse: 'collapse' }}>
            <tbody>
              <tr>
                <td className="pe-4 py-1"><strong>Name</strong></td>
                <td className="py-1">{repo.name}</td>
              </tr>
              <tr>
                <td className="pe-4 py-1"><strong>URL</strong></td>
                <td className="py-1">
                  <a href={repo.url} target="_blank" rel="noreferrer"
                     style={{ color: PRIMARY, fontFamily: 'monospace', fontSize: 12 }}>
                    {repo.url}
                  </a>
                </td>
              </tr>
              <tr>
                <td className="pe-4 py-1"><strong>State</strong></td>
                <td className="py-1">
                  <i className={`bi ${stateIcon(repo.state)} me-1`} />
                  {repo.state}
                </td>
              </tr>
              <tr>
                <td className="pe-4 py-1"><strong>Architectures</strong></td>
                <td className="py-1">{(repo.architectures ?? []).join(', ') || '—'}</td>
              </tr>
              <tr>
                <td className="pe-4 py-1"><strong>Run Lintian</strong></td>
                <td className="py-1">
                  <i className={`bi ${repo.run_lintian ? 'bi-check-lg text-success' : 'bi-dash text-muted'}`} />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
