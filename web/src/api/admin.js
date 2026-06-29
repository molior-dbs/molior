/**
 * admin.js — API calls for admin, maintenance, retention and token endpoints.
 */
import { apiUrl } from '../lib/base';

async function request(method, url, body) {
  const opts = { method, credentials: 'same-origin' };
  if (body !== undefined) {
    opts.headers = { 'Content-Type': 'application/json' };
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || err.error || String(res.status));
  }
  const text = await res.text();
  return text ? JSON.parse(text) : null;
}

// ── Cleanup job ──────────────────────────────────────────────────────────────
export async function fetchCleanup() {
  return request('GET', apiUrl('/api2/cleanup'));
}

export async function saveCleanup({ cleanupActive, cleanupWeekdays, cleanupTime }) {
  return request('PUT', apiUrl('/api2/cleanup'), {
    cleanup_active:   String(cleanupActive),
    cleanup_weekdays: cleanupWeekdays,  // comma-separated day names
    cleanup_time:     cleanupTime,      // "HH:MM"
  });
}

// ── Maintenance ──────────────────────────────────────────────────────────────
export async function fetchMaintenance() {
  return request('GET', apiUrl('/api2/maintenance'));
}

export async function saveMaintenance({ maintenanceMode, maintenanceMessage }) {
  return request('PUT', apiUrl('/api2/maintenance'), {
    maintenance_mode:    String(maintenanceMode),
    maintenance_message: maintenanceMessage,
  });
}

// ── Retention ────────────────────────────────────────────────────────────────
export async function fetchRetention() {
  return request('GET', apiUrl('/api2/retention'));
}

export async function saveRetention({ retentionSuccessfulBuilds, retentionFailedBuilds }) {
  return request('PUT', apiUrl('/api2/retention'), {
    retention_successful_builds: retentionSuccessfulBuilds,
    retention_failed_builds:     retentionFailedBuilds,
  });
}

// ── Tokens ───────────────────────────────────────────────────────────────────
export async function fetchTokens({ description = '', page = 1, page_size = 20 } = {}) {
  const params = new URLSearchParams({ page, page_size });
  if (description) params.set('description', description);
  return request('GET', apiUrl(`/api2/tokens?${params}`));
}

export async function createToken(description) {
  return request('POST', apiUrl('/api2/tokens'), { description });
}

export async function deleteToken(id) {
  const res = await fetch(apiUrl('/api2/tokens'), {
    method: 'DELETE',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || err.error || String(res.status));
  }
}
