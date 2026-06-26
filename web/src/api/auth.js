/**
 * Auth API — mirrors the Angular AuthService.
 *
 * All API calls go to the same origin (the nginx reverse-proxy forwards
 * /api/* → molior:9999).  Credentials (the httpOnly molior_session cookie)
 * are sent automatically because `credentials: 'same-origin'` is used.
 *
 * The session state is kept in localStorage under 'currentUser', exactly as
 * the old Angular app did, so the key is identical if both apps ever coexist
 * during a migration.
 */

const STORAGE_KEY = 'currentUser';

export function getStoredUser() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY));
  } catch {
    return null;
  }
}

export function storeUser(user) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(user));
}

export function clearUser() {
  localStorage.removeItem(STORAGE_KEY);
}

/**
 * POST /api/login
 * Server sets the httpOnly `molior_session` cookie on success.
 * Returns the username on success, throws an Error on failure.
 */
export async function apiLogin(username, password) {
  const res = await fetch('/api/login', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: username.trim(), password }),
  });

  if (!res.ok) {
    // FastAPI returns {"detail": "Login failed"} on 400
    let detail = 'Login failed';
    try {
      const json = await res.json();
      detail = json.detail || detail;
    } catch { /* ignore */ }
    throw new Error(detail);
  }

  return username.trim().toLowerCase();
}

/**
 * GET /api/userinfo
 * Returns { username, user_id, is_admin } or throws on 401.
 */
export async function apiGetUserInfo() {
  const res = await fetch('/api/userinfo', { credentials: 'same-origin' });
  if (!res.ok) throw new Error('Not authenticated');
  return res.json();
}

/**
 * POST /api/logout
 * Server clears the cookie.
 */
export async function apiLogout() {
  await fetch('/api/logout', { method: 'POST', credentials: 'same-origin' });
  clearUser();
}
