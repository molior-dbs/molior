/** Project Versions API — mirrors ProjectVersionService from the Angular app. */
import { apiUrl } from '../lib/base';

export async function fetchProject(projectName) {
  const res = await fetch(apiUrl(`/api2/projectbase/${projectName}`), { credentials: 'same-origin' });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json(); // { id, name, description }
}

export async function fetchProjectVersions(projectName, { q = '', page = 1, page_size = 25 } = {}) {
  const params = new URLSearchParams();
  if (q) params.set('q', q);
  params.set('page', page);
  params.set('page_size', page_size);
  const res = await fetch(apiUrl(`/api2/projectbase/${projectName}/versions?${params}`), { credentials: 'same-origin' });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json(); // { total_result_count, results }
}

export async function createProjectVersion(projectName, body) {
  const res = await fetch(apiUrl(`/api2/projectbase/${projectName}/versions`), {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
  return res.json();
}

export async function editProjectVersion(projectName, versionName, body) {
  // PUT /api2/project/{project_id}/{projectversion_id} — accepts description, dependency_policy, cibuilds, retention_*
  const res = await fetch(apiUrl(`/api2/project/${projectName}/${versionName}`), {
    method: 'PUT', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
}

export async function deleteProjectVersion(projectName, versionName) {
  const res = await fetch(apiUrl(`/api2/project/${projectName}/${versionName}`), {
    method: 'DELETE', credentials: 'same-origin',
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
}

export async function lockProjectVersion(projectName, versionName) {
  const res = await fetch(apiUrl(`/api2/project/${projectName}/${versionName}/lock`), {
    method: 'POST', credentials: 'same-origin',
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
}

export async function exportProjectVersion(projectName, versionName) {
  const res = await fetch(apiUrl(`/api2/project/${projectName}/${versionName}/export`), { credentials: 'same-origin' });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
  return res.json();
}

export async function importProjectVersion(formData) {
  const res = await fetch(apiUrl('/api2/projectbase/projectversion/import'), {
    method: 'POST', credentials: 'same-origin',
    body: formData,
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
  return res.json(); // { projectversion, sourcerepositories }
}

// ─── Project version detail ─────────────────────────────────────────────────

export async function fetchProjectVersion(projectName, versionName) {
  const res = await fetch(apiUrl(`/api2/project/${projectName}/${versionName}`), { credentials: 'same-origin' });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

export async function copyProjectVersion(projectName, versionName, body) {
  const res = await fetch(apiUrl(`/api2/project/${projectName}/${versionName}/copy`), {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
  return res.json();
}

// ─── Dependencies ─────────────────────────────────────────────────────────────

export async function fetchDependencies(projectName, versionName, q = '', page = 1, page_size = 25) {
  const params = new URLSearchParams({ page, page_size });
  if (q) params.set('filter_name', q);
  const res = await fetch(apiUrl(`/api2/project/${projectName}/${versionName}/dependencies?${params}`),
                          { credentials: 'same-origin' });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json(); // { total_result_count, results }
}

export async function addDependency(projectName, versionName, dependency, use_cibuilds = false) {
  const res = await fetch(apiUrl(`/api2/project/${projectName}/${versionName}/dependencies`), {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ dependency, use_cibuilds }),
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
}

export async function removeDependency(projectName, versionName, depProjectName, depVersionName) {
  const res = await fetch(
    apiUrl(`/api2/project/${projectName}/${versionName}/dependency/${depProjectName}/${depVersionName}`),
    { method: 'DELETE', credentials: 'same-origin' }
  );
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
}

// ─── Dependents ───────────────────────────────────────────────────────────────

export async function fetchDependents(projectName, versionName, q = '', page = 1, page_size = 25) {
  const params = new URLSearchParams({ page, page_size });
  if (q) params.set('filter_name', q);
  const res = await fetch(apiUrl(`/api2/project/${projectName}/${versionName}/dependents?${params}`),
                          { credentials: 'same-origin' });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

// ─── Source Repositories ──────────────────────────────────────────────────────

export async function fetchRepositories(projectName, versionName, q = '', page = 1, page_size = 25) {
  const params = new URLSearchParams({ page, page_size });
  if (q) params.set('filter_url', q);
  const res = await fetch(apiUrl(`/api2/project/${projectName}/${versionName}/repositories?${params}`),
                          { credentials: 'same-origin' });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

export async function addRepository(projectName, versionName, url, architectures, run_lintian = false) {
  const res = await fetch(apiUrl(`/api2/project/${projectName}/${versionName}/repositories`), {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, architectures, run_lintian }),
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
  return res.json();
}

export async function editRepository(projectName, versionName, repoId, architectures, run_lintian) {
  const res = await fetch(apiUrl(`/api2/project/${projectName}/${versionName}/repository/${repoId}`), {
    method: 'PUT', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ architectures, run_lintian }),
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
}

export async function removeRepository(projectName, versionName, repoId) {
  const res = await fetch(apiUrl(`/api2/project/${projectName}/${versionName}/repository/${repoId}`), {
    method: 'DELETE', credentials: 'same-origin',
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
}

export async function buildRepository(projectName, versionName, repoId) {
  const res = await fetch(apiUrl(`/api/repositories/${repoId}/build`), {
    method: 'POST', credentials: 'same-origin',
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
}

export async function triggerBuild(projectName, versionName, repoId, gitRef) {
  const body = {};
  if (gitRef) body.git_ref = gitRef;
  const res = await fetch(apiUrl(`/api2/project/${projectName}/${versionName}/repository/${repoId}/trigger`), {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
}

export async function recloneRepository(projectName, versionName, repoId) {
  const res = await fetch(apiUrl(`/api2/project/${projectName}/${versionName}/repository/${repoId}/reclone`), {
    method: 'POST', credentials: 'same-origin',
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
}

// ─── APT Sources ──────────────────────────────────────────────────────────────

export async function fetchAptSources(projectName, versionName, ci = false) {
  const params = new URLSearchParams();
  if (ci) params.set('ci', 'true');
  const res = await fetch(apiUrl(`/api2/project/${projectName}/${versionName}/aptsources?${params}`),
                          { credentials: 'same-origin' });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.text();
}

// ─── Base Mirrors ─────────────────────────────────────────────────────────────

export async function fetchBaseMirrors(q = '') {
  const params = new URLSearchParams();
  if (q) params.set('q', q);
  const res = await fetch(apiUrl(`/api/mirrors?isbasemirror=true&${params}`), { credentials: 'same-origin' });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json(); // { results: [{ name, version, architectures }, ...] }
}



// ─── External Build Upload ─────────────────────────────────────────────────────

export async function uploadExternalBuild(projectName, versionName, files) {
  const formData = new FormData();
  Array.from(files).forEach(file => formData.append(file.name, file));
  const res = await fetch(apiUrl(`/api2/project/${projectName}/${versionName}/extbuild`), {
    method: 'POST',
    credentials: 'same-origin',
    body: formData,
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || `Server error ${res.status}`); }
}

// ─── S3 Publish ───────────────────────────────────────────────────────────────

export async function publishS3(projectName, versionName, { publish_s3, s3_endpoint, s3_path }) {
  const res = await fetch(apiUrl(`/api2/project/${projectName}/${versionName}/s3`), {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ publish_s3, s3_endpoint, s3_path }),
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || `Server error ${res.status}`); }
}
