/** Repos API — mirrors RepositoryService from the Angular app. */
import { apiUrl } from '../lib/base';

export async function fetchRepos({ q = '', filter_url = '', page = 1, page_size = 25 } = {}) {
  const params = new URLSearchParams({ page, page_size });
  if (q)          params.set('q', q);
  if (filter_url) params.set('filter_url', filter_url);
  const res = await fetch(apiUrl(`/api2/repositories?${params}`), { credentials: 'same-origin' });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json(); // { total_result_count, results }
}

export async function fetchRepo(id) {
  const res = await fetch(apiUrl(`/api2/repository/${id}`), { credentials: 'same-origin' });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

export async function fetchRepoDependents(id, { q = '', page = 1, page_size = 25 } = {}) {
  const params = new URLSearchParams({ page, page_size });
  if (q) params.set('filter_name', q);
  const res = await fetch(apiUrl(`/api2/repository/${id}/dependents?${params}`), { credentials: 'same-origin' });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json(); // { total_result_count, results }
}

export async function fetchRepoDependentProjectVersions(id, { unlocked = false } = {}) {
  const params = new URLSearchParams();
  if (unlocked) params.set('unlocked', 'true');
  const res = await fetch(apiUrl(`/api2/repository/${id}/dependents?${params}`), { credentials: 'same-origin' });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

export async function editRepoUrl(id, url) {
  const res = await fetch(apiUrl(`/api2/repository/${id}`), {
    method: 'PUT', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
}

export async function deleteRepo(id) {
  const res = await fetch(apiUrl(`/api2/repository/${id}`), { method: 'DELETE', credentials: 'same-origin' });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
}

export async function buildRepo(id) {
  const res = await fetch(apiUrl(`/api/repositories/${id}/build`), { method: 'POST', credentials: 'same-origin' });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
}

export async function recloneRepo(id) {
  const res = await fetch(apiUrl(`/api/repositories/${id}/clone`), { method: 'POST', credentials: 'same-origin' });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
}

export async function mergeRepo(originalId, duplicateId) {
  const res = await fetch(apiUrl(`/api2/repository/${originalId}/merge`), {
    method: 'PUT', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ duplicate: duplicateId }),
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
}

export async function triggerBuild(repoUrl, gitref, targets = [], forceCI = true) {
  const res = await fetch(apiUrl('/api/build'), {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ repository: repoUrl, git_ref: gitref, force_ci: forceCI, targets }),
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
}
