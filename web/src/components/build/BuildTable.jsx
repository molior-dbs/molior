/**
 * BuildTable — React+Bootstrap port of BuildTableComponent + build-table.html.
 *
 * Features ported from Angular:
 *  - Server-side pagination (page / page_size query params)
 *  - Column filters: name/version search, project, maintainer, commit
 *  - Build-state filter (grouped checkboxes matching the Angular mat-select)
 *  - Per-row context actions: Details / Delete / Abort / Rebuild
 *  - Live runtime ticker for in-progress builds (mirrors updateRuntimes)
 *  - WebSocket build events update the table in real time
 *  - Mouse-wheel page navigation
 *  - Indented tree layout: build → source → deb rows have visual hierarchy
 *
 * Props (all optional — when absent the component shows the global build list):
 *   projectversion  — { project_name, name }  scopes to a project version
 *   repository      — { id }                  scopes to a source repository
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchBuilds, deleteBuild, abortBuild, rebuildBuild, buildLatest } from '../../api/builds';
import ContextMenu from '../common/ContextMenu';
import Pagination from '../common/Pagination';
import { wsUrl } from '../../lib/base';
import {
  buildIcon, buildTypeIcon, buildTypeLabel, buildLabel,
  rowBackground, formatDuration, formatStartTime,
  BUILD_STATE_GROUPS, expandBuildStateGroup,
} from '../../lib/buildUtils';
import ConfirmModal from './ConfirmModal';

const PRIMARY = '#571845';
const TH = { backgroundColor: PRIMARY, color: 'white' };
const PAGE_SIZE = 20;

// Indentation depths for the tree view
const TYPE_INDENT = { build: 0, source: 1, deb: 2, mirror: 0, debootstrap: 0, chroot: 1,
                       copy_projectversion: 0, delete_projectversion: 0, cleanup: 0 };

export default function BuildTable({ projectversion, repository }) {
  const navigate = useNavigate();

  // ── Data ──────────────────────────────────────────────────────────────────
  const [builds, setBuilds]     = useState([]);
  const [total, setTotal]       = useState(null);   // null = loading
  const [error, setError]       = useState('');
  const [page, setPage]         = useState(1);
  const [pageSize]              = useState(PAGE_SIZE);

  // ── Filters ───────────────────────────────────────────────────────────────
  const [search, setSearch]             = useState('');
  const [searchProject, setSearchProject] = useState('');
  const [maintainer, setMaintainer]     = useState('');
  const [commit, setCommit]             = useState('');
  const [selectedStates, setSelectedStates] = useState([]);
  const [stateMenuOpen, setStateMenuOpen]   = useState(false);

  // ── Runtime ticker ────────────────────────────────────────────────────────
  const [tick, setTick] = useState(0);
  const tickRef = useRef(null);

  // ── Action modal ──────────────────────────────────────────────────────────
  const [modal, setModal] = useState(null); // { type, build }
  const [ctxMenu, setCtxMenu] = useState(null); // { x, y, build }

  // ── Load data ─────────────────────────────────────────────────────────────
  const load = useCallback(async (pg = page) => {
    setError('');
    try {
      const expandedStates = selectedStates.flatMap(expandBuildStateGroup);
      const params = {
        page: pg,
        page_size: pageSize,
        buildstate: [...new Set(expandedStates)],
        search, maintainer, commit,
      };
      if (!projectversion) params.search_project = searchProject;
      if (projectversion)  params.project = `${projectversion.project_name}/${projectversion.name}`;
      if (repository)      params.sourcerepository_id = repository.id;

      const data = await fetchBuilds(params);
      setBuilds(data.results);
      setTotal(data.total);
    } catch (e) {
      setError(e.message);
      setTotal(-1);
    }
  }, [page, pageSize, search, searchProject, maintainer, commit, selectedStates, projectversion, repository]);

  const buildsRef = useRef(builds);
  buildsRef.current = builds;

  useEffect(() => { load(page); }, [page]);

  // Re-load from page 1 whenever any filter changes (reset page)
  const prevFiltersRef = useRef({ search, searchProject, maintainer, commit, selectedStates });
  useEffect(() => {
    const prev = prevFiltersRef.current;
    const changed = prev.search !== search || prev.searchProject !== searchProject ||
      prev.maintainer !== maintainer || prev.commit !== commit ||
      JSON.stringify(prev.selectedStates) !== JSON.stringify(selectedStates);
    if (changed) {
      prevFiltersRef.current = { search, searchProject, maintainer, commit, selectedStates };
      setPage(1);
      load(1);
    }
  }, [search, searchProject, maintainer, commit, selectedStates]);

  // ── WebSocket live updates ─────────────────────────────────────────────────
  useEffect(() => {
    const scoped = !!(projectversion || repository);

    const inScope = (data) => {
      if (projectversion) {
        const pid = projectversion.id;
        if (data.projectversion_id != null) return data.projectversion_id === pid;      // deb/chroot
        if (Array.isArray(data.projectversion_ids)) return data.projectversion_ids.includes(pid); // build/source
        // fallback for deb rows when no id is available in the payload
        return !!data.project &&
          data.project.name === projectversion.project_name &&
          data.project.version === projectversion.name;
      }
      if (repository) return data.sourcerepository_id === repository.id;
      return true; // global table — everything is in scope
    };

    const insertRow = (prev, data) => {
      if (prev.some(b => b.id === data.id)) return prev; // already shown
      if (data.parent_id != null) {
        const parentIdx = prev.findIndex(b => b.id === data.parent_id);
        if (parentIdx === -1) return prev; // parent not visible — skip
        const next = [...prev];
        next.splice(parentIdx + 1, 0, data);
        return next.slice(0, pageSize);
      }
      return [data, ...prev].slice(0, pageSize);
    };

    const ws = new WebSocket(wsUrl('/api/websocket'));

    ws.onmessage = (evt) => {
      let msg;
      try { msg = JSON.parse(evt.data); } catch { return; }
      if (msg.subject !== 7) return; // subject 7 = build
      const data = msg.data || {};
      if (data.id == null) return;

      const rows = buildsRef.current;
      const known = rows.some(b => b.id === data.id);

      if (msg.event === 3) {
        if (!known) return;
        setBuilds(prev => prev.filter(b => b.id !== data.id));
        setTotal(t => (t != null && t > 0 ? t - 1 : t));
        return;
      }

      if (msg.event === 2 && known) {
        setBuilds(prev => prev.map(b => b.id === data.id ? { ...b, ...data } : b));
        return;
      }

      if (page !== 1 || known || !inScope(data)) return;
      if (msg.event === 2 && !scoped) return;
      if (data.parent_id != null && !rows.some(b => b.id === data.parent_id)) return;

      setBuilds(prev => insertRow(prev, data));
      setTotal(t => (t ?? 0) + 1);
    };

    return () => ws.close();
  }, [page, pageSize, projectversion, repository]);

  // ── Runtime ticker — re-renders every second when builds are in progress ──
  useEffect(() => {
    const hasActive = builds.some(b =>
      !['new', 'build_failed', 'publish_failed', 'successful', 'already_exists', 'nothing_done'].includes(b.buildstate)
    );
    if (hasActive) {
      tickRef.current = setInterval(() => setTick(t => t + 1), 1000);
    }
    return () => clearInterval(tickRef.current);
  }, [builds]);

  // ── Live runtime for in-progress builds ───────────────────────────────────
  function liveRuntime(build) {
    if (!build.startstamp) return null;
    const terminalStates = ['new','build_failed','publish_failed','successful','already_exists','nothing_done'];
    if (terminalStates.includes(build.buildstate)) return null;
    const interval = (Date.now() - new Date(build.startstamp)) / 1000;
    const mins = Math.floor(interval / 60);
    let secs = String(Math.floor(interval % 60));
    if (mins > 0) {
      secs = secs.padStart(2, '0');
      return `${mins}'${secs}''`;
    }
    return `${secs}''`;
  }

  // ── Modal helpers ─────────────────────────────────────────────────────────
  function closeModal(reloadNeeded) {
    setModal(null);
    if (reloadNeeded) load(page);
  }

  // ── State filter toggle ───────────────────────────────────────────────────
  function toggleState(value) {
    setSelectedStates(prev =>
      prev.includes(value) ? prev.filter(s => s !== value) : [...prev, value]
    );
  }

  // ── Pagination ────────────────────────────────────────────────────────────
  const totalPages = total > 0 ? Math.ceil(total / pageSize) : 1;
  const pageStart  = total > 0 ? (page - 1) * pageSize + 1 : 0;
  const pageEnd    = total > 0 ? Math.min(page * pageSize, total) : 0;

  const showProject = !projectversion;

  return (
    <div>
      {/* ── Modal overlay ── */}
      {modal?.type === 'delete' && (
        <ConfirmModal
          title="Delete Build"
          body="The build will be deleted. This operation cannot be undone."
          onConfirm={() => deleteBuild(modal.build.id)}
          onClose={closeModal}
        />
      )}
      {modal?.type === 'abort' && (
        <ConfirmModal
          title="Abort Build"
          body={<span>Abort building <strong>{modal.build.sourcename}</strong>{modal.build.buildvariant ? ` ${modal.build.buildvariant.name}` : ''}?</span>}
          onConfirm={() => abortBuild(modal.build.id)}
          onClose={closeModal}
        />
      )}
      {modal?.type === 'rebuild' && (
        <ConfirmModal
          title="Retry Build"
          body={<span>Retry building <strong>{modal.build.sourcename}</strong>{modal.build.buildvariant ? ` ${modal.build.buildvariant.name}` : ''}?</span>}
          onConfirm={() => rebuildBuild(modal.build.id)}
          onClose={closeModal}
        />
      )}
      {modal?.type === 'trigger' && (
        <ConfirmModal
          title="Trigger Build"
          body={<span>Trigger a new build for <strong>{modal.build.sourcename}</strong>?</span>}
          onConfirm={() => buildLatest(modal.build.sourcerepository_id)}
          onClose={closeModal}
        />
      )}

      {/* ── Context menu (right-click on row) ── */}
      {ctxMenu && (
        <ContextMenu x={ctxMenu.x} y={ctxMenu.y} onClose={() => setCtxMenu(null)}>
          <li><button className="dropdown-item" onClick={() => { navigate(`/build/${ctxMenu.build.id}`); setCtxMenu(null); }}><i className="bi bi-list me-2" />Details</button></li>
          <li><button className="dropdown-item" onClick={() => { setModal({ type: 'delete', build: ctxMenu.build }); setCtxMenu(null); }}><i className="bi bi-trash me-2" />Delete</button></li>
          <li><button className="dropdown-item" onClick={() => { setModal({ type: 'abort', build: ctxMenu.build }); setCtxMenu(null); }}><i className="bi bi-slash-circle me-2" />Abort Build</button></li>
          <li><button className="dropdown-item" onClick={() => { setModal({ type: 'rebuild', build: ctxMenu.build }); setCtxMenu(null); }}><i className="bi bi-arrow-counterclockwise me-2" />Retry Build</button></li>
          {ctxMenu.build.sourcerepository_id && <li><hr className="dropdown-divider" /></li>}
          {ctxMenu.build.sourcerepository_id && <li><button className="dropdown-item" onClick={() => { buildLatest(ctxMenu.build.sourcerepository_id); setCtxMenu(null); }}><i className="bi bi-arrow-repeat me-2" />Check for new builds</button></li>}
          {ctxMenu.build.sourcerepository_id && <li><button className="dropdown-item" onClick={() => { setModal({ type: 'trigger', build: ctxMenu.build }); setCtxMenu(null); }}><i className="bi bi-play me-2" />Trigger build</button></li>}
        </ContextMenu>
      )}

      {/* ── Pagination (above table) ── */}
      <Pagination page={page} totalPages={totalPages} total={total} pageSize={pageSize}
                  onPageChange={setPage} label={`build${total !== 1 ? 's' : ''}`} />

      {/* ── Table ── */}
      <div>
        <table className="table table-sm table-hover align-middle mb-0" style={{ fontSize: '13px' }}>
          <thead>
            <tr>
              {/* Build state filter */}
              <th style={{ ...TH, width: 44 }}>
                <div className="dropdown" style={{ position: 'relative' }}>
                  <button
                    className="btn btn-sm p-0 border-0"
                    style={{ color: 'white' }}
                    onClick={() => setStateMenuOpen(o => !o)}
                    title="Filter by state"
                  >
                    <i className="bi bi-funnel-fill" />
                    {selectedStates.length > 0 && (
                      <span className="badge rounded-pill bg-warning text-dark ms-1" style={{ fontSize: 9 }}>
                        {selectedStates.length}
                      </span>
                    )}
                  </button>
                  {stateMenuOpen && (
                    <div className="dropdown-menu show p-2" style={{ minWidth: 210, zIndex: 1050 }}>
                      {BUILD_STATE_GROUPS.map(g => (
                        <div key={g.value} className="form-check">
                          <input
                            className="form-check-input" type="checkbox" id={`bs-${g.value}`}
                            checked={selectedStates.includes(g.value)}
                            onChange={() => toggleState(g.value)}
                          />
                          <label className="form-check-label d-flex align-items-center gap-1" htmlFor={`bs-${g.value}`}>
                            <i className={`bi ${g.icon.replace(' rotating', '')}`} />
                            {g.label}
                          </label>
                        </div>
                      ))}
                      {selectedStates.length > 0 && (
                        <button className="btn btn-sm btn-link p-0 mt-1" onClick={() => setSelectedStates([])}>
                          Clear
                        </button>
                      )}
                    </div>
                  )}
                </div>
              </th>

              {/* Name / Version */}
              <th style={TH}>
                <input
                  className="form-control form-control-sm"
                  placeholder="Name / Version"
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  style={{ minWidth: 200, '::placeholder': { color: 'rgba(255,255,255,.6)' } }}
                />
              </th>

              {/* Project (only on global build list) */}
              {showProject && (
                <th style={TH}>
                  <input
                    className="form-control form-control-sm"
                    placeholder="Project"
                    value={searchProject}
                    onChange={e => setSearchProject(e.target.value)}
                    style={{ minWidth: 140 }}
                  />
                </th>
              )}

              {/* Maintainer */}
              <th style={TH}>
                <input
                  className="form-control form-control-sm"
                  placeholder="Maintainer"
                  value={maintainer}
                  onChange={e => setMaintainer(e.target.value)}
                  style={{ minWidth: 120 }}
                />
              </th>

              {/* Commit */}
              <th style={TH}>
                <input
                  className="form-control form-control-sm"
                  placeholder="Commit"
                  value={commit}
                  onChange={e => setCommit(e.target.value)}
                  style={{ minWidth: 120 }}
                />
              </th>

              <th style={{ ...TH, whiteSpace: 'nowrap' }}>Start</th>
              <th style={{ ...TH, whiteSpace: 'nowrap' }}>Duration</th>
              <th style={TH} />
            </tr>
          </thead>

          <tbody>
            {total === null && (
              <tr><td colSpan={showProject ? 8 : 7} className="text-center py-3 text-muted">Loading…</td></tr>
            )}
            {total === -1 && (
              <tr><td colSpan={showProject ? 8 : 7} className="text-center py-3 text-danger">Unable to load data ({error})</td></tr>
            )}
            {total === 0 && (
              <tr><td colSpan={showProject ? 8 : 7} className="text-center py-3 text-muted">No entries found</td></tr>
            )}

            {builds.map(build => {
              const label    = buildLabel(build);
              const duration = formatDuration(build) || liveRuntime(build) || build.runtime || '';
              const startTime = formatStartTime(build);
              const indent    = (TYPE_INDENT[build.buildtype] ?? 0) * 16;
              const bg        = rowBackground(build.buildtype);

              return (
                <tr
                  key={build.id}
                  style={{ cursor: 'pointer', backgroundColor: bg }}
                  onClick={e => { if (!e.target.closest('.dropdown')) navigate(`/build/${build.id}`); }}
                  onContextMenu={e => { e.preventDefault(); setCtxMenu({ x: e.clientX, y: e.clientY, build }); }}
                >
                  {/* Build state icon */}
                  <td className="text-center" onClick={e => e.stopPropagation()}>
                    <i
                      className={`bi ${buildIcon(build.buildstate)}`}
                      title={build.buildstate}
                      style={{ fontSize: 16 }}
                    />
                  </td>

                  {/* Build type + name */}
                  <td>
                    <div className="d-flex align-items-center" style={{ paddingLeft: indent }}>
                      <i
                        className={`bi ${buildTypeIcon(build.buildtype)} me-2 text-secondary`}
                        title={buildTypeLabel(build.buildtype)}
                        style={{ fontSize: 15, flexShrink: 0 }}
                      />
                      <span>
                        {label.bold
                          ? <strong>{label.text}</strong>
                          : label.text}
                        {label.suffix && <span className="text-muted">{label.suffix}</span>}
                      </span>
                      {build.progress != null &&
                       (build.buildstate === 'building' || build.buildstate === 'publishing') && (
                        <span className="ms-auto text-muted" style={{ fontFamily: 'monospace', fontSize: 12 }}>
                          {Math.round(build.progress)}%
                        </span>
                      )}
                    </div>
                  </td>

                  {/* Project link */}
                  {showProject && (
                    <td onClick={e => e.stopPropagation()}>
                      {build.project && (
                        <a
                          href={`/project/${build.project.name}/${build.project.version}/info`}
                          onClick={e => { e.preventDefault(); navigate(`/project/${build.project.name}/${build.project.version}/info`); }}
                          style={{ fontWeight: 'bold', color: 'inherit', textDecoration: 'none' }}
                        >
                          {build.project.name}/{build.project.version}
                        </a>
                      )}
                    </td>
                  )}

                  {/* Maintainer */}
                  <td title={build.maintainer_email || ''}>
                    {(build.buildtype === 'build' || build.buildtype === 'mirror') && (
                      <strong>{build.maintainer}</strong>
                    )}
                  </td>

                  {/* Commit */}
                  <td style={{ fontFamily: 'monospace', fontSize: 12 }}>
                    {build.buildtype === 'build' && (build.git_ref || '').slice(0, 12)}
                  </td>

                  {/* Start time */}
                  <td title={formatStartTime(build, true) || ''} style={{ whiteSpace: 'nowrap' }}>
                    {startTime}
                  </td>

                  {/* Duration */}
                  <td style={{ whiteSpace: 'nowrap' }}>{duration}</td>

                  {/* Actions dropdown */}
                  <td className="text-end">
                    <div className="dropdown">
                      <button
                        className="btn btn-sm btn-link p-0 text-secondary"
                        data-bs-toggle="dropdown" aria-expanded="false"
                        onClick={e => e.stopPropagation()}
                      >
                        <i className="bi bi-three-dots-vertical" />
                      </button>
                      <ul className="dropdown-menu dropdown-menu-end">
                        <li>
                          <button className="dropdown-item" onClick={() => navigate(`/build/${build.id}`)}>
                            <i className="bi bi-list me-2" />Details
                          </button>
                        </li>
                        <li>
                          <button className="dropdown-item" onClick={() => setModal({ type: 'delete', build })}>
                            <i className="bi bi-trash me-2" />Delete
                          </button>
                        </li>
                        <li>
                          <button className="dropdown-item" onClick={() => setModal({ type: 'abort', build })}>
                            <i className="bi bi-slash-circle me-2" />Abort Build
                          </button>
                        </li>
                        <li>
                          <button className="dropdown-item" onClick={() => setModal({ type: 'rebuild', build })}>
                            <i className="bi bi-arrow-counterclockwise me-2" />Retry Build
                          </button>
                        </li>
                        {build.sourcerepository_id && <li><hr className="dropdown-divider" /></li>}
                        {build.sourcerepository_id && (
                          <li>
                            <button className="dropdown-item" onClick={() => buildLatest(build.sourcerepository_id)}>
                              <i className="bi bi-arrow-repeat me-2" />Check for new builds
                            </button>
                          </li>
                        )}
                        {build.sourcerepository_id && (
                          <li>
                            <button className="dropdown-item" onClick={() => setModal({ type: 'trigger', build })}>
                              <i className="bi bi-play me-2" />Trigger build
                            </button>
                          </li>
                        )}
                      </ul>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>


    </div>
  );
}
