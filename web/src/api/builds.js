/**
 * Builds API — mirrors BuildService from the Angular app.
 * All endpoints match the original Angular service exactly.
 */

export async function fetchBuilds(params) {
  const q = new URLSearchParams();
  if (params.buildstate?.length)    q.set('buildstate', params.buildstate.join(','));
  if (params.search)                q.set('search', params.search);
  if (params.search_project)        q.set('search_project', params.search_project);
  if (params.maintainer)            q.set('maintainer', params.maintainer);
  if (params.project)               q.set('project', params.project);
  if (params.sourcerepository_id)   q.set('sourcerepository_id', params.sourcerepository_id);
  if (params.commit)                q.set('commit', params.commit);
  if (params.page)                  q.set('page', params.page);
  if (params.page_size)             q.set('page_size', params.page_size);

  const res = await fetch(`/api/builds?${q}`, { credentials: 'same-origin' });
  if (!res.ok) throw new Error(`${res.status}`);
  const data = await res.json(); // { results: Build[], total_result_count: number }
  return {
    results: data.results ?? data,
    total:   data.total_result_count ?? data.total ?? (data.results ?? data).length,
  };
}

export async function fetchBuild(id) {
  const res = await fetch(`/api2/build/${id}`, { credentials: 'same-origin' });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

export async function buildLatest(repositoryId) {
  const res = await fetch(`/api/repositories/${repositoryId}/build`, {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' }, body: '{}',
  });
  if (!res.ok) throw new Error(`${res.status}`);
}

export async function deleteBuild(id) {
  const res = await fetch(`/api2/build/${id}`, { method: 'DELETE', credentials: 'same-origin' });
  if (!res.ok) throw new Error(`${res.status}`);
}

export async function abortBuild(id) {
  const res = await fetch(`/api2/build/${id}/abort`, { method: 'POST', credentials: 'same-origin' });
  if (!res.ok) throw new Error(`${res.status}`);
}

export async function rebuildBuild(id) {
  const res = await fetch(`/api2/build/${id}`, { method: 'PUT', credentials: 'same-origin', body: '{}',
    headers: { 'Content-Type': 'application/json' } });
  if (!res.ok) throw new Error(`${res.status}`);
}
