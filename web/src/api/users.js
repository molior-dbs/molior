/** Users API — mirrors UserService from the Angular app. */
import { apiUrl } from '../lib/base';

export async function fetchUsers({ name = '', email = '', admin = false, page = 1, page_size = 25 } = {}) {
  const params = new URLSearchParams({ page, page_size });
  if (name)  params.set('name', name);
  if (email) params.set('email', email);
  if (admin) params.set('admin', 'true');
  const res = await fetch(apiUrl(`/api/users?${params}`), { credentials: 'same-origin' });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json(); // { total_result_count, results: [{ id, username, email, is_admin }] }
}

export async function fetchUser(username) {
  const res = await fetch(apiUrl(`/api2/user/${username}`), { credentials: 'same-origin' });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json(); // { id, username, email, is_admin }
}

export async function createUser({ name, email, password, is_admin = false }) {
  const res = await fetch(apiUrl('/api/users'), {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, email, password, is_admin }),
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
}

export async function editUser(id, { email, password, is_admin }) {
  const body = { is_admin };
  if (email)    body.email    = email;
  if (password) body.password = password;
  const res = await fetch(apiUrl(`/api/users/${id}`), {
    method: 'PUT', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
}

export async function deleteUser(id) {
  const res = await fetch(apiUrl(`/api/users/${id}`), { method: 'DELETE', credentials: 'same-origin' });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || res.status); }
}

export async function fetchStatus() {
  const res = await fetch(apiUrl('/api/status'), { credentials: 'same-origin' });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json(); // { version_molior_server, version_aptly, sshkey, gpgurl, ... }
}
