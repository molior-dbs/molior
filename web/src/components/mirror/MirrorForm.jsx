/**
 * MirrorForm — port of MirrorDialogComponent / mirror-form.html.
 * Used for both Create and Edit. Also used (with copyFrom) for Copy.
 *
 * The Angular form used a 4-step MatStepper; here we use Bootstrap nav-tabs.
 * Steps: Mirror Info → Mirror Source → Mirror Keys → Advanced Options
 */
import React, { useState, useEffect } from 'react';
import { fetchMirrors, createMirror, editMirror } from '../../api/mirrors';
import { rules, fieldClass, fieldError } from '../../lib/validate';

const ARCHITECTURES = ['amd64', 'i386', 'arm64', 'armhf'];

const EMPTY = {
  // step 0
  mirrorurl: '', mirrorname: '', mirrorversion: '',
  mirrortype: '1', basemirror: '', external_repo: false, dependencylevel: 'strict',
  // step 1
  mirrorsrc: false, mirrorinst: false, mirrordist: '', mirrorcomponents: 'main',
  architectures: ['amd64', 'i386', 'arm64', 'armhf'],
  // step 2
  mirrorkeytype: '1', mirrorkeyurl: '', mirrorkeyids: '', mirrorkeyserver: 'hkp://keyserver.ubuntu.com:80',
  // step 3
  mirrorfilter: '',
};

function mirrorToForm(m, isCopy = false) {
  let keytype = '1';
  if (m.mirrorkeyurl)  keytype = '1';
  else if (m.mirrorkeyids) keytype = '2';
  return {
    mirrorurl: m.url, mirrorname: m.name,
    mirrorversion: isCopy ? m.version + '-copy' : m.version,
    mirrortype: m.is_basemirror ? '1' : '2',
    basemirror: m.basemirror_name || '', external_repo: m.external_repo,
    dependencylevel: m.dependency_policy || 'strict',
    mirrorsrc: m.with_sources, mirrorinst: m.with_installer,
    mirrordist: m.distribution, mirrorcomponents: m.components,
    architectures: m.architectures || [],
    mirrorkeytype: keytype,
    mirrorkeyurl: m.mirrorkeyurl || '',
    mirrorkeyids: (m.mirrorkeyids || '').split(/[, ]/).join(' '),
    mirrorkeyserver: m.mirrorkeyserver || 'hkp://keyserver.ubuntu.com:80',
    mirrorfilter: m.mirrorfilter || '',
  };
}

const TABS = ['Mirror Info', 'Mirror Source', 'Mirror Keys', 'Advanced Options'];

export default function MirrorForm({ mirror, copyFrom, onClose }) {
  const isEdit = !!mirror && !copyFrom;
  const isCopy = !!copyFrom;
  const source = mirror || copyFrom;

  const [form, setForm]         = useState(source ? mirrorToForm(source, isCopy) : { ...EMPTY });
  const [tab, setTab]           = useState(0);
  const [busy, setBusy]         = useState(false);
  const [error, setError]       = useState('');
  const [basemirrors, setBM]    = useState([]);
  const [mirrorUrls, setUrls]   = useState([]);
  const [urlSug, setUrlSug]     = useState(false);
  const [bmSug, setBmSug]       = useState(false);
  const [touched, setTouched]   = useState({});
  const touch = f => setTouched(t => ({ ...t, [f]: true }));

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  const errors = {
    mirrorurl:     rules.httpUrl(form.mirrorurl),
    mirrorname:    isEdit ? '' : rules.name(form.mirrorname),
    mirrorversion: isEdit ? '' : rules.version(form.mirrorversion),
    mirrordist:    rules.required(form.mirrordist, 1, 'Distribution'),
  };

  useEffect(() => {
    fetchMirrors({ basemirror: true, page_size: 200 })
      .then(r => setBM((r.results || []).map(m => ({ name: `${m.name}/${m.version}`, architectures: m.architectures }))))
      .catch(() => {});
    fetchMirrors({ page_size: 200 })
      .then(r => setUrls([...new Set((r.results || []).map(m => m.url))]))
      .catch(() => {});
  }, []);

  function toggleArch(arch) {
    set('architectures', form.architectures.includes(arch)
      ? form.architectures.filter(a => a !== arch)
      : [...form.architectures, arch]);
  }

  function valid() {
    if (!form.mirrorurl || !form.mirrorname || !form.mirrorversion) return false;
    if (form.mirrortype === '2' && !form.basemirror) return false;
    if (!form.mirrordist) return false;
    if (!form.architectures.length) return false;
    if (form.mirrorkeytype === '1' && !form.mirrorkeyurl) return false;
    if (form.mirrorkeytype === '2' && (!form.mirrorkeyids || !form.mirrorkeyserver)) return false;
    return true;
  }

  function buildBody() {
    return {
      mirrorname: form.mirrorname.trim(), mirrorversion: form.mirrorversion.trim(),
      mirrortype: form.mirrortype, basemirror: form.basemirror,
      external: form.external_repo, mirrorurl: form.mirrorurl.trim(),
      dependencylevel: form.dependencylevel,
      mirrordist: form.mirrordist.trim(), mirrorcomponents: form.mirrorcomponents.trim(),
      architectures: form.architectures, mirrorsrc: form.mirrorsrc, mirrorinst: form.mirrorinst,
      mirrorkeytype: form.mirrorkeytype,
      mirrorkeyurl: form.mirrorkeytype === '1' ? form.mirrorkeyurl.trim() : '',
      mirrorkeyids: form.mirrorkeytype === '2' ? form.mirrorkeyids.trim() : '',
      mirrorkeyserver: form.mirrorkeytype === '2' ? form.mirrorkeyserver.trim() : '',
      mirrorfilter: form.mirrorfilter.trim(),
    };
  }

  async function save() {
    setBusy(true); setError('');
    try {
      if (isEdit) await editMirror(mirror.name, mirror.version, buildBody());
      else        await createMirror(buildBody());
      onClose(true);
    } catch (e) { setError(e.message); setBusy(false); }
  }

  const title = isEdit ? `Edit Mirror: ${mirror.name}/${mirror.version}`
              : isCopy ? `Copy Mirror from ${copyFrom.name}/${copyFrom.version}`
              : 'Create Debian Mirror';

  return (
    <div className="modal fade show d-block" tabIndex="-1" style={{ backgroundColor: 'rgba(0,0,0,.4)' }}>
      <div className="modal-dialog modal-xl modal-dialog-centered">
        <div className="modal-content">

          <div className="modal-header">
            <h5 className="modal-title d-flex align-items-center gap-2">
              <i className="bi bi-folder-symlink" />{title}
            </h5>
            <button className="btn-close" onClick={() => onClose(false)} disabled={busy} />
          </div>

          <div className="modal-body" style={{ minHeight: 420 }}>
            {error && <div className="alert alert-danger py-2">{error}</div>}

            {/* Tabs */}
            <ul className="nav nav-tabs mb-3">
              {TABS.map((t, i) => (
                <li key={i} className="nav-item">
                  <button className={`nav-link${tab === i ? ' active' : ''}`} onClick={() => setTab(i)}>{t}</button>
                </li>
              ))}
            </ul>

            {/* ── Step 0: Mirror Info ── */}
            {tab === 0 && (
              <div>
                {/* URL */}
                <div className="mb-3 position-relative">
                  <label className="form-label fw-semibold">Mirror URL</label>
                  <input className={fieldClass(touched.mirrorurl && errors.mirrorurl)}
                    value={form.mirrorurl}
                    onChange={e => { set('mirrorurl', e.target.value); setUrlSug(true); }}
                    onBlur={() => { touch('mirrorurl'); setTimeout(() => setUrlSug(false), 150); }} />
                  {touched.mirrorurl && errors.mirrorurl && <div className="invalid-feedback">{errors.mirrorurl}</div>}
                  {urlSug && mirrorUrls.filter(u => u.includes(form.mirrorurl) && u !== form.mirrorurl).length > 0 && (
                    <ul className="list-group position-absolute w-100" style={{ zIndex: 1060, top: '100%' }}>
                      {mirrorUrls.filter(u => u.includes(form.mirrorurl)).slice(0, 8).map(u => (
                        <li key={u} className="list-group-item list-group-item-action py-1"
                          style={{ cursor: 'pointer' }} onMouseDown={() => { set('mirrorurl', u); setUrlSug(false); }}>
                          {u}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                {/* Name + Version (not shown when editing) */}
                {!isEdit && (
                  <div className="row mb-3">
                    <div className="col">
                      <label className="form-label fw-semibold">Name</label>
                      <input className={fieldClass(touched.mirrorname && errors.mirrorname)}
                        value={form.mirrorname}
                        onChange={e => set('mirrorname', e.target.value)}
                        onBlur={() => touch('mirrorname')} />
                      {touched.mirrorname && errors.mirrorname && <div className="invalid-feedback">{errors.mirrorname}</div>}
                    </div>
                    <div className="col">
                      <label className="form-label fw-semibold">Version</label>
                      <input className={fieldClass(touched.mirrorversion && errors.mirrorversion)}
                        value={form.mirrorversion}
                        onChange={e => set('mirrorversion', e.target.value)}
                        onBlur={() => touch('mirrorversion')} />
                      {touched.mirrorversion && errors.mirrorversion && <div className="invalid-feedback">{errors.mirrorversion}</div>}
                    </div>
                  </div>
                )}

                {/* Mirror Type */}
                <div className="mb-3">
                  <label className="form-label fw-semibold">Mirror Type</label>
                  <div className="form-check">
                    <input className="form-check-input" type="radio" name="mtype" id="mt1" value="1"
                      checked={form.mirrortype === '1'} onChange={() => set('mirrortype', '1')} />
                    <label className="form-check-label" htmlFor="mt1">
                      <strong>Debian Base Mirror</strong> — Official Debian repository containing a full distribution
                    </label>
                  </div>
                  <div className="form-check mt-2">
                    <input className="form-check-input" type="radio" name="mtype" id="mt2" value="2"
                      checked={form.mirrortype === '2'} onChange={() => set('mirrortype', '2')} />
                    <label className="form-check-label" htmlFor="mt2">
                      <strong>APT Repository Mirror</strong> — Additional repository for a specific distribution
                    </label>
                  </div>

                  {form.mirrortype === '2' && (
                    <div className="ms-4 mt-2 position-relative">
                      <label className="form-label">Base Mirror</label>
                      <input className="form-control" placeholder="-- Select Base Mirror --"
                        value={form.basemirror}
                        onChange={e => { set('basemirror', e.target.value); setBmSug(true); }}
                        onBlur={() => setTimeout(() => setBmSug(false), 150)} />
                      {bmSug && basemirrors.filter(b => b.name.includes(form.basemirror)).length > 0 && (
                        <ul className="list-group position-absolute w-100" style={{ zIndex: 1060, top: '100%' }}>
                          {basemirrors.filter(b => b.name.includes(form.basemirror)).slice(0, 10).map(b => (
                            <li key={b.name} className="list-group-item list-group-item-action py-1"
                              style={{ cursor: 'pointer' }}
                              onMouseDown={() => { set('basemirror', b.name); setBmSug(false); }}>
                              {b.name} ({(b.architectures || []).join(', ')})
                            </li>
                          ))}
                        </ul>
                      )}

                      {/* Dependency policy */}
                      <label className="form-label mt-2">Dependency Policy</label>
                      <select className="form-select" value={form.dependencylevel}
                        onChange={e => set('dependencylevel', e.target.value)}>
                        <option value="strict">strict — Use in {form.basemirror} based projects</option>
                        <option value="distribution">dist — Use in {form.basemirror.split('/')[0]} based projects</option>
                        <option value="any">any — Use with any base mirror based projects</option>
                      </select>
                    </div>
                  )}
                </div>

                {/* External Repo */}
                <div className="form-check">
                  <input className="form-check-input" type="checkbox" id="extrepo"
                    checked={form.external_repo} onChange={e => set('external_repo', e.target.checked)} />
                  <label className="form-check-label fw-semibold" htmlFor="extrepo">External Repo</label>
                </div>
              </div>
            )}

            {/* ── Step 1: Mirror Source ── */}
            {tab === 1 && (
              <div>
                <div className="mb-3 d-flex gap-4">
                  <div className="form-check">
                    <input className="form-check-input" type="checkbox" id="mirrorsrc"
                      checked={form.mirrorsrc} onChange={e => set('mirrorsrc', e.target.checked)} />
                    <label className="form-check-label" htmlFor="mirrorsrc">Mirror source packages</label>
                  </div>
                  {form.mirrortype === '1' && (
                    <div className="form-check">
                      <input className="form-check-input" type="checkbox" id="mirrorinst"
                        checked={form.mirrorinst} onChange={e => set('mirrorinst', e.target.checked)} />
                      <label className="form-check-label" htmlFor="mirrorinst">Mirror installer &amp; udebs</label>
                    </div>
                  )}
                </div>
                <div className="mb-3">
                  <label className="form-label fw-semibold">Distribution</label>
                  <input className={fieldClass(touched.mirrordist && errors.mirrordist)}
                    value={form.mirrordist}
                    onChange={e => set('mirrordist', e.target.value)}
                    onBlur={() => touch('mirrordist')} />
                  {touched.mirrordist && errors.mirrordist && <div className="invalid-feedback">{errors.mirrordist}</div>}
                </div>
                <div className="mb-3">
                  <label className="form-label fw-semibold">Components</label>
                  <input className="form-control" value={form.mirrorcomponents} onChange={e => set('mirrorcomponents', e.target.value)} />
                </div>
                <div className="mb-3">
                  <label className="form-label fw-semibold">Architectures</label>
                  <div className="d-flex gap-3">
                    {ARCHITECTURES.map(arch => (
                      <div key={arch} className="form-check">
                        <input className="form-check-input" type="checkbox" id={`arch-${arch}`}
                          checked={form.architectures.includes(arch)} onChange={() => toggleArch(arch)} />
                        <label className="form-check-label" htmlFor={`arch-${arch}`}>{arch}</label>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* ── Step 2: Mirror Keys ── */}
            {tab === 2 && (
              <div>
                <div className="form-check mb-3">
                  <input className="form-check-input" type="radio" name="keytype" id="kt1"
                    checked={form.mirrorkeytype === '1'} onChange={() => set('mirrorkeytype', '1')} />
                  <label className="form-check-label fw-semibold" htmlFor="kt1">Download key file</label>
                </div>
                {form.mirrorkeytype === '1' && (
                  <div className="mb-3 ms-4">
                    <label className="form-label">URL</label>
                    <input className="form-control" value={form.mirrorkeyurl}
                      onChange={e => set('mirrorkeyurl', e.target.value)} />
                  </div>
                )}
                <div className="form-check mb-3">
                  <input className="form-check-input" type="radio" name="keytype" id="kt2"
                    checked={form.mirrorkeytype === '2'} onChange={() => set('mirrorkeytype', '2')} />
                  <label className="form-check-label fw-semibold" htmlFor="kt2">Download key from server</label>
                </div>
                {form.mirrorkeytype === '2' && (
                  <div className="ms-4">
                    <div className="mb-3">
                      <label className="form-label">Key IDs</label>
                      <input className="form-control" value={form.mirrorkeyids}
                        onChange={e => set('mirrorkeyids', e.target.value)} />
                    </div>
                    <div className="mb-3">
                      <label className="form-label">Key Server</label>
                      <input className="form-control" value={form.mirrorkeyserver}
                        onChange={e => set('mirrorkeyserver', e.target.value)} />
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* ── Step 3: Advanced ── */}
            {tab === 3 && (
              <div>
                <div className="mb-2">
                  <label className="form-label fw-semibold">Exclude Filter <span className="text-muted fw-normal">(optional)</span></label>
                  <input className="form-control" value={form.mirrorfilter}
                    onChange={e => set('mirrorfilter', e.target.value)} />
                </div>
                <small className="text-muted">Example: !(Name (= dotnet-sdk-5.0), Version (= 5.0.202-1))</small>
              </div>
            )}
          </div>

          <div className="modal-footer">
            <button className="btn btn-secondary" onClick={() => onClose(false)} disabled={busy}>Cancel</button>
            {tab > 0 && (
              <button className="btn btn-outline-secondary" onClick={() => setTab(t => t - 1)} disabled={busy}>Back</button>
            )}
            {tab < TABS.length - 1 && (
              <button className="btn btn-primary" onClick={() => setTab(t => t + 1)} disabled={busy}>Next</button>
            )}
            {tab === TABS.length - 1 && (
              <button className="btn btn-primary" onClick={save} disabled={busy || !valid()}>
                {busy && <span className="spinner-border spinner-border-sm me-2" />}OK
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
