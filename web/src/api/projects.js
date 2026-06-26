/** Projects API — mirrors ProjectService from the Angular app. */

export async function fetchProjects({ q = '', page = 1, page_size = 25 } = {}) {
  const params = new URLSearchParams();
  if (q) params.set('q', q);
  params.set('page', page);
  params.set('page_size', page_size);
  const res = await fetch(`/api/projects?${params}`, { credentials: 'same-origin' });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json(); // { total_result_count, results }
}

export async function createProject(name, description) {
  const res = await fetch('/api/projects', {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, description }),
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
  return res.json();
}

export async function editProject(id, description) {
  const res = await fetch(`/api/projects/${id}`, {
    method: 'PUT', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ description }),
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
}

export async function deleteProject(name) {
  const res = await fetch(`/api2/projectbase/${name}`, { method: 'DELETE', credentials: 'same-origin' });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
}
