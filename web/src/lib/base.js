/**
 * base.js — runtime base-path helpers.
 *
 * When molior is served behind a reverse proxy that adds a prefix (e.g.
 * /molior/), nginx rewrites the <base href> in index.html to that prefix.
 * Everything else — asset loading, React Router routes, fetch() calls and
 * WebSocket URLs — is derived from that single source of truth.
 *
 * When served at the root the <base href> is "./" and all values collapse
 * back to their bare forms (e.g. basePath === '/').
 */

/**
 * The base path as an absolute string with a trailing slash.
 * Examples:
 *   <base href="./">   →  "/"          (served at root)
 *   <base href="/molior/">  →  "/molior/"  (served under /molior/)
 */
export const basePath = (() => {
  const base = document.querySelector('base');
  if (!base) return '/';
  // Resolve the href (which may be relative like "./") against the document
  // origin to get an absolute URL, then return only the pathname.
  const url = new URL(base.getAttribute('href') || './', document.baseURI);
  return url.pathname; // always ends with '/'
})();

/**
 * Prepend the base path to an API path.
 * apiUrl('/api/builds')  →  '/api/builds'        (root)
 *                        →  '/molior/api/builds'  (proxy prefix)
 */
export function apiUrl(path) {
  // basePath ends with '/', path starts with '/' — trim one slash.
  return basePath === '/' ? path : basePath.replace(/\/$/, '') + path;
}

/**
 * Build a WebSocket URL for the given API path, respecting the base path.
 * wsUrl('/api/websocket')  →  'ws://host/api/websocket'
 *                          →  'wss://host/molior/api/websocket'
 */
export function wsUrl(path) {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${proto}://${window.location.host}${apiUrl(path)}`;
}
