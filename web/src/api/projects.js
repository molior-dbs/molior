/** Projects API — mirrors ProjectService from the Angular app. */
import { apiUrl } from '../lib/base';

export async function fetchProjects({ q = '', page = 1, page_size = 25 } = {}) {
  const params = new URLSearchParams();
  if (q) params.set('q', q);
  params.set('page', page);
  params.set('page_size', page_size);
  const res = await fetch(apiUrl(`/api/projects?${params}`), { credentials: 'same-origin' });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
  return res.json(); // { total_result_count, results }
}

export async function createProject(name, description) {
  const res = await fetch(apiUrl('/api/projects'), {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, description }),
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
  return res.json();
}

export async function editProject(id, description) {
  const res = await fetch(apiUrl(`/api/projects/${id}`), {
    method: 'PUT', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ description }),
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
}

export async function deleteProject(name) {
  const res = await fetch(apiUrl(`/api2/projectbase/${name}`), { method: 'DELETE', credentials: 'same-origin' });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
}

// ── Permissions ──────────────────────────────────────────────────────────────
export async function fetchProjectPermissions(name, { q = '', role = '', page = 1, page_size = 20 } = {}) {
  const params = new URLSearchParams({ page, page_size });
  if (q)    params.set('filter_name', q);
  if (role) params.set('filter_role', role);
  const res = await fetch(apiUrl(`/api2/projectbase/${name}/permissions?${params}`), { credentials: 'same-origin' });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
  return res.json();
}

export async function fetchPermissionCandidates(name, q = '') {
  const params = new URLSearchParams({ candidates: 'true', q });
  const res = await fetch(apiUrl(`/api2/projectbase/${name}/permissions?${params}`), { credentials: 'same-origin' });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
  return res.json();
}

export async function addProjectPermission(name, username, role) {
  const res = await fetch(apiUrl(`/api2/projectbase/${name}/permissions`), {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, role }),
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
}

export async function editProjectPermission(name, username, role) {
  const res = await fetch(apiUrl(`/api2/projectbase/${name}/permissions`), {
    method: 'PUT', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, role }),
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
}

export async function deleteProjectPermission(name, username) {
  const res = await fetch(apiUrl(`/api2/projectbase/${name}/permissions`), {
    method: 'DELETE', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username }),
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
}

// ── Project tokens ────────────────────────────────────────────────────────────
export async function fetchProjectTokens(name, { q = '', page = 1, page_size = 20 } = {}) {
  const params = new URLSearchParams({ page, page_size });
  if (q) params.set('description', q);
  const res = await fetch(apiUrl(`/api2/projectbase/${name}/tokens?${params}`), { credentials: 'same-origin' });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
  return res.json();
}

export async function createProjectToken(name, description) {
  // Creates a brand-new token and links it to the project
  const res = await fetch(apiUrl(`/api2/projectbase/${name}/token`), {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ description }),
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
  return res.json();
}

export async function linkProjectToken(name, description) {
  // Links an existing (user) token to the project by description
  const res = await fetch(apiUrl(`/api2/projectbase/${name}/token`), {
    method: 'PUT', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ description }),
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
}

export async function deleteProjectToken(name, id) {
  const res = await fetch(apiUrl(`/api2/projectbase/${name}/tokens`), {
    method: 'DELETE', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id }),
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
}
