/** Mirrors API — mirrors MirrorService from the Angular app. */

export async function fetchMirrors({ q = '', q_basemirror = '', page = 1, page_size = 25, basemirror = false } = {}) {
  const params = new URLSearchParams();
  if (q)            params.set('q', q);
  if (q_basemirror) params.set('q_basemirror', q_basemirror);
  if (basemirror)   params.set('basemirror', 'true');
  params.set('page', page);
  params.set('page_size', page_size);
  const res = await fetch(`/api/mirrors?${params}`, { credentials: 'same-origin' });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json(); // { total_result_count, results }
}

export async function createMirror(body) {
  const res = await fetch('/api2/mirror', {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
}

export async function editMirror(name, version, body) {
  const res = await fetch(`/api2/mirror/${name}/${version}`, {
    method: 'PUT', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
}

export async function deleteMirror(name, version) {
  const res = await fetch(`/api2/mirror/${name}/${version}`, { method: 'DELETE', credentials: 'same-origin' });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
}

export async function updateMirror(id) {
  const res = await fetch(`/api/mirror/${id}/update`, { method: 'POST', credentials: 'same-origin' });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
}

export async function fetchMirror(name, version) {
  const res = await fetch(`/api2/mirror/${name}/${version}`, { credentials: 'same-origin' });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

export async function fetchMirrorDependents(name, version, q = '', page = 1, page_size = 25) {
  const params = new URLSearchParams({ page, page_size });
  if (q) params.set('filter_name', q);
  const res = await fetch(`/api2/mirror/${name}/${version}/dependents?${params}`, { credentials: 'same-origin' });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json(); // { total_result_count, results }
}

export async function fetchMirrorAptSources(name, version) {
  const res = await fetch(`/api2/mirror/${name}/${version}/aptsources`, { credentials: 'same-origin' });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.text();
}
