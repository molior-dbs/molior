/**
 * BuildInfoPage — port of BuildInfoComponent + build-info.html.
 *
 * Features:
 *  - Build metadata table (source name, version, state, project, parent/children,
 *    base mirror, architecture, progress)
 *  - Action menu: Delete · Retry Build · Check for new builds
 *  - Build log panel:
 *      · ANSI colour rendering via ansi_up
 *      · Live streaming via WebSocket (subject 8, action 4/5)
 *      · WebSocket build-change events update state / progress in real time
 *      · Blinking cursor row while building
 *      · Auto-scroll "follow" mode (toggled by checkbox or manual scroll)
 *      · Error-line detection + "Find Error" navigation (mirrors ErrorPatterns)
 *      · Jump anchors: buildstart / lintian
 *      · Log search (≥3 chars): highlights rows, prev/next navigation
 *      · URL fragment #line-N scrolls to and highlights that line on load
 *  - Pagination strip showing visible line range / total
 */
import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate, useLocation, Link } from 'react-router-dom';
import { AnsiUp } from 'ansi_up';
import { fetchBuild, deleteBuild, rebuildBuild, buildLatest } from '../../api/builds';
import { buildIcon, buildTypeLabel, formatDuration, formatStartTime } from '../../lib/buildUtils';
import ConfirmModal from './ConfirmModal';

// ---------------------------------------------------------------------------
// Error-pattern detection — exact port from build-info.ts
// ---------------------------------------------------------------------------
const ErrorPatterns = [
  [/\S*(error|ERROR|Error)(:| in) /i, [
    [/dpkg-buildpackage: error: debian\/rules build subprocess returned exit status \d+$/],
    [/sbuild command failed/],
    [/dpkg-buildpackage/, /exit status \d+/],
  ]],
  [/^[^/(]*[^;]\berror\b[^:]/i, [
    [/gpgv: keyblock resource/, /General error$/],
    [/error\.\S+$/],
    [/dpkg-buildpackage/, /exit status \d+/],
    [/: warning: unused parameter/],
  ]],
  [/^(\x1b[^m]+m)*E:/, [
    [/dpkg-buildpackage died/],
    [/Error building source package/],
    [/Package build dependencies not satisfied; skipping/],
    [/Is \/dev\/pts mounted\?/],
  ]],
  [/^(\x1b[^m]+m)*make.+No rule to make target.*Stop/, []],
  [/dh_install: missing files, aborting/, []],
  [/\/bin\/sh:.+not found/, []],
  [/: No such file or directory/, [
    [/head: cannot open/, /certs\/java\/cacerts/],
    [/aclocal: warning: couldn't open directory 'm4'/],
  ]],
  [/Target "[^"]+" does not exist in the project/, []],
  [/\.py:\d+:\d+: [FW]\d+ /, []],
  [/dh_systemd_enable: Could not handle all of the requested services/, []],
  [/unsat-dependency: /, []],
  [/: Permission denied/, []],
  [/: error :/, []],
  [/: error CS\d+:/, []],
  [/:\d+:\d+: E\d+/, []],
];

function isErrorLine(line) {
  for (const [pattern, falsePositives] of ErrorPatterns) {
    if (pattern.test(line)) {
      let isFP = false;
      for (const fps of falsePositives) {
        if (fps.every(fp => fp.test(line))) { isFP = true; break; }
      }
      if (!isFP) return true;
    }
  }
  return false;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
const ACTIVE_STATES = new Set(['new', 'needs_build', 'building', 'needs_publish', 'publishing']);
const LIVE_STATES   = new Set(['building', 'needs_publish', 'publishing']);

const PRIMARY = '#571845';

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export default function BuildInfoPage() {
  const { id } = useParams();
  const buildId = parseInt(id, 10);
  const navigate = useNavigate();
  const location = useLocation();

  // ── Build metadata ────────────────────────────────────────────────────────
  const [build, setBuild]   = useState(null);
  const [error, setError]   = useState('');
  const [modal, setModal]   = useState(null);

  // ── Log state (DOM-mutated directly for perf, like Angular) ───────────────
  const tbodyRef          = useRef(null);   // <tbody id="buildlog">
  const logScrollRef      = useRef(null);   // scrollable container
  const ansiup            = useRef(new AnsiUp());
  const loglinesRef       = useRef(0);
  const incompleteRef     = useRef('');
  const followRef         = useRef(true);
  const [follow, setFollowState] = useState(true);   // for checkbox UI sync
  const buildstartLineRef = useRef(-1);
  const lintianLineRef    = useRef(-1);
  const lastRowRef        = useRef(null);
  const wsRef             = useRef(null);
  const aliveRef          = useRef(false);    // component mounted

  // ── Error finder ──────────────────────────────────────────────────────────
  const [totalErr,   setTotalErr]   = useState(0);
  const [currentErr, setCurrentErr] = useState(0);

  // ── Search ────────────────────────────────────────────────────────────────
  const [searchQuery, setSearchQuery]       = useState('');
  const [totalSearch,   setTotalSearch]     = useState(0);
  const [currentSearch, setCurrentSearch]   = useState(0);
  const searchQueryRef = useRef('');

  // ── Pagination (visible line range) ──────────────────────────────────────
  const [visRange, setVisRange] = useState({ start: 0, end: 0 });
  const [logLineCount, setLogLineCount] = useState(0);

  // ── Highlight from URL fragment ───────────────────────────────────────────
  const selectedLineRef = useRef(null);

  // Track whether the last scroll was programmatic (so we don't unfollow on it)
  const programmaticScrollRef = useRef(false);

  // ---------------------------------------------------------------------------
  // Scroll helper (mirrors scrollToLog)
  // ---------------------------------------------------------------------------
  function scrollToLog(element) {
    const scroll = logScrollRef.current;
    if (!scroll || !element) return;
    const offsetPosition = element.getBoundingClientRect().top
      - scroll.getBoundingClientRect().top
      + scroll.scrollTop - 42;
    programmaticScrollRef.current = true;
    scroll.scrollTo({ top: offsetPosition, behavior: 'smooth' });
  }

  // ---------------------------------------------------------------------------
  // Line-range tracker (mirrors updatePaginator)
  // ---------------------------------------------------------------------------
  function updateVisRange() {
    const scroll = logScrollRef.current;
    if (!scroll) return;
    const viewBottom = scroll.scrollTop + scroll.getBoundingClientRect().height - 16;
    let h = 0, start = null, end = null;
    for (let i = 1; i <= loglinesRef.current; i++) {
      const row = document.getElementById(`row-${i}`);
      if (!row) break;
      h += row.getBoundingClientRect().height;
      if (start === null && h > scroll.scrollTop) start = i;
      if (end === null   && h > viewBottom)        end   = i;
    }
    if (start !== null) {
      setVisRange({ start, end: end ?? loglinesRef.current });
    }

    // Only update follow state for real user-initiated scrolls
    if (programmaticScrollRef.current) {
      programmaticScrollRef.current = false;
      return;
    }

    const atBottom = scroll.scrollTop + scroll.clientHeight >= scroll.scrollHeight - 4;
    if (atBottom) {
      if (!followRef.current) { followRef.current = true;  setFollowState(true);  }
    } else {
      if (followRef.current)  { followRef.current = false; setFollowState(false); }
    }
  }

  // ---------------------------------------------------------------------------
  // DOM log-line writers (mirrors addLogLine / replaceLogLine)
  // ---------------------------------------------------------------------------
  function addLogLine(line, buildstate) {
    const tbody = tbodyRef.current;
    if (!tbody) return;
    const nr  = loglinesRef.current + 1;
    const row = tbody.insertRow(loglinesRef.current);
    row.id    = `row-${nr}`;

    const linenrCell = row.insertCell(0);
    linenrCell.innerHTML = `<a href="#line-${nr}" id="line-${nr}" class="build-lognr-link">${nr}</a>`;
    linenrCell.className = 'build-lognr';

    const loglineCell = row.insertCell(1);
    loglineCell.innerHTML = ansiup.current.ansi_to_html(line);
    loglineCell.className = 'build-logline';

    if (line === 'dpkg-buildpackage') buildstartLineRef.current = nr;
    if (/Building tag database\.\.\./.test(line)) lintianLineRef.current = nr;

    if (buildstate !== 'successful' && isErrorLine(line)) {
      row.className = 'build-errorline';
    }

    loglinesRef.current = nr;
    lastRowRef.current  = row;
    setLogLineCount(nr);
  }

  function replaceLogLine(line) {
    const row = document.getElementById(`row-${loglinesRef.current}`);
    if (row) row.children[1].innerHTML = ansiup.current.ansi_to_html(line);
  }

  // ---------------------------------------------------------------------------
  // Chunk processor (mirrors the while-loop in the Angular subscription)
  // ---------------------------------------------------------------------------
  function processChunk(chunk, buildstate) {
    let data = chunk;
    if (incompleteRef.current) {
      data = incompleteRef.current + data;
      incompleteRef.current = '';
    }
    lastRowRef.current = null;
    while (data.length && aliveRef.current) {
      const cr = data.indexOf('\r');
      const lf = data.indexOf('\n');
      if (cr !== -1 && lf !== -1) {
        if (cr < lf) { replaceLogLine(data.slice(0, cr)); data = data.slice(cr + 1); }
        else         { addLogLine(data.slice(0, lf), buildstate); data = data.slice(lf + 1); }
      } else if (cr !== -1) {
        replaceLogLine(data.slice(0, cr)); data = data.slice(cr + 1);
      } else if (lf !== -1) {
        addLogLine(data.slice(0, lf), buildstate); data = data.slice(lf + 1);
      } else {
        incompleteRef.current = data; break;
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Highlight a line by number (fragment navigation + auto-find-error)
  // ---------------------------------------------------------------------------
  function highlightLine(lineNum) {
    if (!lineNum) return;
    const line = document.getElementById(`line-${lineNum}`);
    if (!line) return;
    scrollToLog(line);
    const row = document.getElementById(`row-${lineNum}`);
    if (row) row.style.background = '#4967a2';
  }

  // ---------------------------------------------------------------------------
  // findError — exact port
  // ---------------------------------------------------------------------------
  const currentErrRef = useRef(0);
  function findError() {
    const errors = document.getElementsByClassName('build-errorline');
    const total  = errors.length;
    setTotalErr(total);
    if (total === 0) return;
    if (currentErrRef.current >= total) currentErrRef.current = 0;
    scrollToLog(errors[currentErrRef.current]);
    currentErrRef.current++;
    setCurrentErr(currentErrRef.current);
  }

  // ---------------------------------------------------------------------------
  // Search — port of search / searchNext / searchPrev
  // ---------------------------------------------------------------------------
  function removeSearchHighlight(node) {
    const childs = node.childNodes;
    for (let j = childs.length - 1; j >= 0; j--) {
      const child = childs[j];
      if (child.nodeType === 1) {
        if (child.className === 'build-searchhighlight') {
          node.replaceChild(child.childNodes[0], child);
        } else {
          removeSearchHighlight(child);
        }
      }
    }
  }

  function doSearch(query) {
    searchQueryRef.current = query;
    // Clear old results
    const prev = Array.from(document.getElementsByClassName('build-searchresult'));
    prev.forEach(el => { removeSearchHighlight(el); el.classList.remove('build-searchresult'); });
    setTotalSearch(0); setCurrentSearch(0);
    if (query.length < 3) return;

    const qlen = query.length;
    const escaped = query.replace(/[.()*+[\]/$^|~\\]/g, c => `\\${c}`);
    const r = new RegExp(`(${escaped})(?![^<]*>)`, 'gi');
    const tbody = tbodyRef.current;
    if (!tbody) return;
    for (const row of tbody.children) {
      const log = row.children[1];
      if (!log) continue;
      let first = true;
      let match = r.exec(log.innerHTML);
      while (match !== null) {
        if (first) { first = false; log.classList.add('build-searchresult'); }
        const pos = match.index;
        const pre = log.innerHTML.slice(0, pos);
        const hit = log.innerHTML.slice(pos, pos + qlen);
        const post = log.innerHTML.slice(pos + qlen);
        log.innerHTML = `${pre}<span class="build-searchhighlight">${hit}</span>${post}`;
        r.lastIndex += 37;
        match = r.exec(log.innerHTML);
      }
    }
    const results = document.getElementsByClassName('build-searchresult');
    setTotalSearch(results.length);
    if (results.length > 0) { scrollToLog(results[0]); setCurrentSearch(1); }
  }

  const searchCurrentRef = useRef(0);
  function searchNext() {
    const results = document.getElementsByClassName('build-searchresult');
    if (!results.length) return;
    searchCurrentRef.current = (searchCurrentRef.current % results.length) + 1;
    setCurrentSearch(searchCurrentRef.current);
    scrollToLog(results[searchCurrentRef.current - 1]);
  }
  function searchPrev() {
    const results = document.getElementsByClassName('build-searchresult');
    if (!results.length) return;
    if (searchCurrentRef.current <= 1) searchCurrentRef.current = results.length;
    else searchCurrentRef.current--;
    setCurrentSearch(searchCurrentRef.current);
    scrollToLog(results[searchCurrentRef.current - 1]);
  }

  // ---------------------------------------------------------------------------
  // toggleFollow
  // ---------------------------------------------------------------------------
  function toggleFollow() {
    const newVal = !followRef.current;
    followRef.current = newVal;
    setFollowState(newVal);
    if (newVal) {
      const endRow = document.getElementById(`row-${loglinesRef.current}`);
      if (endRow) {
        programmaticScrollRef.current = true;
        endRow.scrollIntoView();
      }
    }
  }

  // ---------------------------------------------------------------------------
  // fetchLogs — starts WS stream, mirrors fetchLogs() + ngOnInit()
  // ---------------------------------------------------------------------------
  const fetchLogs = useCallback((bid, buildObj) => {
    // Clear log DOM
    const tbody = tbodyRef.current;
    if (tbody) tbody.innerHTML = '';
    loglinesRef.current   = 0;
    setLogLineCount(0);
    incompleteRef.current = '';
    followRef.current     = true;
    setFollowState(true);
    buildstartLineRef.current = -1;
    lintianLineRef.current    = -1;
    currentErrRef.current = 0;
    setTotalErr(0); setCurrentErr(0);
    setTotalSearch(0); setCurrentSearch(0);
    searchCurrentRef.current = 0;

    // Close previous WS if any
    if (wsRef.current) {
      try { wsRef.current.close(); } catch {}
      wsRef.current = null;
    }

    // Add blinking cursor if build is in active state
    if (tbody && ACTIVE_STATES.has(buildObj.buildstate)) {
      const cursor = tbody.insertRow(0);
      cursor.id = 'row-cursor';
      const nr = cursor.insertCell(0);
      nr.className  = 'build-lognr build-blinking-cursor';
      nr.innerHTML  = '▁';
      cursor.insertCell(1).className = 'build-logline';
    }

    // Open WS
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${proto}://${window.location.host}/api/websocket`);
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify({ subject: 8, action: 4, data: { build_id: bid } }));
    };

    ws.onmessage = (evt) => {
      let msg;
      try { msg = JSON.parse(evt.data); } catch { return; }

      // Build change events (subject 7 = build)
      if (msg.subject === 7 && msg.event === 2 && msg.data?.id === bid) {
        setBuild(prev => prev ? { ...prev, ...msg.data } : prev);
        return;
      }

      // Buildlog events (subject 8)
      if (msg.subject !== 8) return;

      // done (event 5)
      if (msg.event === 5) {
        const cursor = document.getElementById('row-cursor');
        if (cursor) cursor.parentNode?.removeChild(cursor);

        // scroll to end if following
        const endRow = document.getElementById(`row-${loglinesRef.current}`);
        if (endRow && followRef.current) {
          programmaticScrollRef.current = true;
          endRow.scrollIntoView();
        }

        // count errors
        const errors = document.getElementsByClassName('build-errorline');
        const errCount = errors.length;
        setTotalErr(errCount);

        // highlight fragment line
        if (selectedLineRef.current) {
          highlightLine(selectedLineRef.current);
        } else if (buildObj.buildstate === 'build_failed') {
          // auto-jump to first error like Angular does
          currentErrRef.current = 0;
          findError();
        }
        updateVisRange();
        return;
      }

      // data chunk (event 1)
      if (msg.event === 1 && typeof msg.data === 'string') {
        processChunk(msg.data, buildObj.buildstate);
        const tbody2 = tbodyRef.current;
        if (lastRowRef.current && aliveRef.current && LIVE_STATES.has(buildObj.buildstate)) {
          if (followRef.current) {
            programmaticScrollRef.current = true;
            lastRowRef.current.scrollIntoView();
          }
          updateVisRange();
        }
      }
    };
  }, []);

  // ---------------------------------------------------------------------------
  // Mount / unmount
  // ---------------------------------------------------------------------------
  useEffect(() => {
    aliveRef.current = true;

    // Parse fragment
    const frag = window.location.hash;
    if (frag && frag.startsWith('#line-')) {
      selectedLineRef.current = parseInt(frag.slice(6), 10);
    }

    // Fetch build info, then stream logs
    fetchBuild(buildId)
      .then(b => { setBuild(b); fetchLogs(buildId, b); })
      .catch(e => setError(e.message));

    return () => {
      aliveRef.current = false;
      if (wsRef.current) {
        try {
          wsRef.current.send(JSON.stringify({ subject: 8, action: 5 }));
          wsRef.current.close();
        } catch {}
        wsRef.current = null;
      }
    };
  }, [buildId]);

  // Keep fetchLogs in sync when build state changes via WS
  const prevBuildstateRef = useRef('');
  useEffect(() => {
    if (!build) return;
    if (build.buildstate !== prevBuildstateRef.current) {
      prevBuildstateRef.current = build.buildstate;
    }
  }, [build?.buildstate]);

  // ---------------------------------------------------------------------------
  // Render helpers
  // ---------------------------------------------------------------------------
  function parentLabel(buildtype) {
    switch (buildtype) {
      case 'source': return 'build';
      case 'deb':    return 'source';
      case 'chroot': return 'mirror';
      default:       return 'parent';
    }
  }
  function childLabel(buildtype) {
    switch (buildtype) {
      case 'build':   return 'source';
      case 'source':  return 'deb';
      case 'mirror':  return 'chroot';
      default:        return 'child';
    }
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------
  if (error) return (
    <div className="p-4 text-danger">Failed to load build {buildId}: {error}</div>
  );
  if (!build) return (
    <div className="p-4 text-muted">Loading…</div>
  );

  const proj    = build.project;
  const bv      = build.buildvariant;
  const dur     = formatDuration(build);
  const started = formatStartTime(build);

  return (
    <div className="d-flex flex-column" style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>

      {/* ── Modals ── */}
      {modal?.type === 'delete' && (
        <ConfirmModal
          title="Delete Build"
          body="The build will be deleted. This operation cannot be undone."
          onConfirm={() => deleteBuild(build.id)}
          onClose={ok => { setModal(null); if (ok) navigate('/builds'); }}
        />
      )}
      {modal?.type === 'rebuild' && (
        <ConfirmModal
          title="Retry Build"
          body={<span>Retry building <strong>{build.sourcename}</strong>?</span>}
          onConfirm={() => rebuildBuild(build.id)}
          onClose={ok => {
            setModal(null);
            if (ok) {
              fetchBuild(buildId).then(b => { setBuild(b); fetchLogs(buildId, b); }).catch(() => {});
            }
          }}
        />
      )}

      {/* ── Header: Build N: name version ── */}
      <div className="px-3 pt-3 pb-1 d-flex align-items-center gap-2" style={{ flexShrink: 0 }}>
        <i className="bi bi-journals" style={{ fontSize: 20 }} />
        <h1 style={{ fontSize: 20, fontWeight: 500, margin: 0 }}>
          Build {build.id}: {build.sourcename} {build.version}
        </h1>
      </div>

      {/* ── Info table ── */}
      <div className="mx-3 mb-2 border rounded d-flex" style={{ flexShrink: 0, fontSize: 13 }}>
        <table style={{ borderCollapse: 'collapse', flex: 1 }}>
          <tbody>
            <tr>
              <td className="px-2 py-1"><strong>Source Name</strong></td>
              <td className="px-2 py-1">{build.sourcename}</td>

              {proj?.version && (<>
                <td className="px-2 py-1">
                  <strong>{proj.is_mirror ? 'Mirror' : 'Project'}</strong>
                </td>
                <td className="px-2 py-1">
                  {proj.is_mirror
                    ? <Link to={`/mirror/${proj.name}/${proj.version.name}`} style={{ color: PRIMARY }}>{proj.name}/{proj.version.name}</Link>
                    : <Link to={`/project/${proj.name}/${proj.version.name}`} style={{ color: PRIMARY }}>{proj.name}/{proj.version.name}</Link>
                  }
                </td>
              </>)}

              {build.parent_id && (<>
                <td className="px-2 py-1"><strong>Parent Build</strong></td>
                <td className="px-2 py-1">
                  <Link to={`/build/${build.parent_id}`} style={{ color: PRIMARY }}>
                    {parentLabel(build.buildtype)}
                  </Link>
                </td>
              </>)}
            </tr>

            {build.version && (
              <tr>
                <td className="px-2 py-1"><strong>Version</strong></td>
                <td className="px-2 py-1">{build.version}</td>

                {build.children?.length > 0 && (<>
                  <td className="px-2 py-1"><strong>Children Build(s)</strong></td>
                  <td className="px-2 py-1">
                    {build.children.map((child, i) => (
                      <span key={child.id}>
                        <Link to={`/build/${child.id}`} style={{ color: PRIMARY }}>
                          {childLabel(build.buildtype)}
                        </Link>
                        {i < build.children.length - 1 ? ', ' : ''}
                      </span>
                    ))}
                  </td>
                </>)}

                {bv?.base_mirror?.name && (<>
                  <td className="px-2 py-1"><strong>Base Mirror</strong></td>
                  <td className="px-2 py-1">
                    <Link to={`/mirror/${bv.base_mirror.name}/${bv.base_mirror.version}`} style={{ color: PRIMARY }}>
                      {bv.base_mirror.name}/{bv.base_mirror.version}
                    </Link>
                  </td>
                </>)}
              </tr>
            )}

            <tr>
              <td className="px-2 py-1"><strong>State</strong></td>
              <td className="px-2 py-1 d-flex align-items-center gap-1">
                <i className={`bi ${buildIcon(build.buildstate)}`} title={build.buildstate} style={{ fontSize: 16 }} />
                {build.progress != null && (build.buildstate === 'building' || build.buildstate === 'publishing') && (
                  <span className="text-muted ms-1" style={{ fontFamily: 'monospace', fontSize: 12 }}>
                    {Math.round(build.progress)}%
                  </span>
                )}
              </td>

              {build.architecture && (<>
                <td className="px-2 py-1"><strong>Architecture</strong></td>
                <td className="px-2 py-1">{build.architecture}</td>
              </>)}

              {started && (<>
                <td className="px-2 py-1"><strong>Started</strong></td>
                <td className="px-2 py-1" title={formatStartTime(build, true) || ''}>{started}</td>
              </>)}

              {dur && (<>
                <td className="px-2 py-1"><strong>Duration</strong></td>
                <td className="px-2 py-1">{dur}</td>
              </>)}
            </tr>
          </tbody>
        </table>

        {/* Action menu */}
        <div className="p-2" style={{ flexShrink: 0 }}>
          <div className="dropdown">
            <button className="btn btn-sm btn-outline-secondary" data-bs-toggle="dropdown">
              <i className="bi bi-three-dots-vertical" />
            </button>
            <ul className="dropdown-menu dropdown-menu-end">
              <li>
                <button className="dropdown-item" onClick={() => setModal({ type: 'delete' })}>
                  <i className="bi bi-trash me-2" />Delete
                </button>
              </li>
              <li>
                <button className="dropdown-item" onClick={() => setModal({ type: 'rebuild' })}>
                  <i className="bi bi-arrow-counterclockwise me-2" />Retry Build
                </button>
              </li>
              {build.sourcerepository?.id && (
                <li>
                  <button className="dropdown-item" onClick={() => buildLatest(build.sourcerepository.id)}>
                    <i className="bi bi-arrow-left-right me-2" />Check for new builds
                  </button>
                </li>
              )}
            </ul>
          </div>
        </div>
      </div>

      {/* ── Log toolbar ── */}
      <div className="px-3 d-flex align-items-center gap-2 mb-1" style={{ flexShrink: 0, fontSize: 13 }}>
        <h2 style={{ fontSize: 16, fontWeight: 600, margin: 0, flex: 1 }}>Build Log</h2>

        {/* Jump links */}
        {buildstartLineRef.current >= 0 && (
          <button className="btn btn-sm btn-link p-0" style={{ color: PRIMARY }}
            onClick={() => highlightLine(buildstartLineRef.current)}>
            buildstart
          </button>
        )}
        {lintianLineRef.current >= 0 && (
          <button className="btn btn-sm btn-link p-0" style={{ color: PRIMARY }}
            onClick={() => highlightLine(lintianLineRef.current)}>
            lintian
          </button>
        )}

        {/* Search */}
        <input
          className="form-control form-control-sm"
          placeholder="Search…"
          value={searchQuery}
          style={{ width: 130 }}
          onChange={e => { setSearchQuery(e.target.value); doSearch(e.target.value); }}
        />
        {totalSearch > 0 && (
          <span className="d-flex align-items-center gap-1">
            <button className="btn btn-sm btn-link p-0" style={{ color: PRIMARY }} onClick={searchPrev}>prev</button>
            <span>{currentSearch}/{totalSearch}</span>
            <button className="btn btn-sm btn-link p-0" style={{ color: PRIMARY }} onClick={searchNext}>next</button>
          </span>
        )}

        {/* Follow checkbox (only while building) */}
        {ACTIVE_STATES.has(build.buildstate) && (
          <div className="form-check mb-0 d-flex align-items-center gap-1">
            <input className="form-check-input mt-0" type="checkbox" id="followChk"
              checked={follow} onChange={toggleFollow} />
            <label className="form-check-label" htmlFor="followChk">follow</label>
          </div>
        )}

        {/* Find Error button */}
        {build.buildstate === 'build_failed' && totalErr > 0 && (
          <button className="btn btn-sm btn-outline-danger" onClick={findError}>
            Find Error ({currentErr}/{totalErr})
          </button>
        )}

        {/* Top / Bottom buttons */}
        {logLineCount > 0 && (
          <>
            <button className="btn btn-sm btn-link p-0" style={{ color: PRIMARY }} title="Scroll to top"
              onClick={() => {
                programmaticScrollRef.current = true;
                logScrollRef.current?.scrollTo({ top: 0 });
              }}>
              <i className="bi bi-arrow-up-circle" />
            </button>
            <button className="btn btn-sm btn-link p-0" style={{ color: PRIMARY }} title="Scroll to bottom"
              onClick={() => {
                programmaticScrollRef.current = true;
                logScrollRef.current?.scrollTo({ top: logScrollRef.current.scrollHeight });
              }}>
              <i className="bi bi-arrow-down-circle" />
            </button>
          </>
        )}

        {/* Line range display */}
        {logLineCount > 0 && (
          <span className="text-muted" style={{ fontFamily: 'monospace', fontSize: 12, whiteSpace: 'nowrap' }}>
            {visRange.start}–{visRange.end} / {logLineCount}
          </span>
        )}
      </div>

      {/* ── Log panel ── */}
      <div className="mx-3 mb-2 rounded build-log-wrapper" style={{ flex: 1, minHeight: 0 }}>
        <div
          ref={logScrollRef}
          className="build-log-scroll"
          tabIndex={0}
          onScroll={updateVisRange}
        >
          <table className="build-log-table">
            <tbody ref={tbodyRef} id="buildlog" />
          </table>
        </div>
      </div>
    </div>
  );
}
