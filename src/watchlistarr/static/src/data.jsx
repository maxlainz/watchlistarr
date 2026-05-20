// API client + pure helpers shared with the React pages.

const formatRelative = (input) => {
  if (!input) return null;
  const d = input instanceof Date ? input : new Date(input);
  const seconds = (Date.now() - d.getTime()) / 1000;
  if (seconds < 60) return `${Math.max(0, Math.floor(seconds))}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
};

const formatDateShort = (input) => {
  if (!input) return '';
  const d = input instanceof Date ? input : new Date(input);
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  return `${months[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}`;
};

async function request(method, url, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const resp = await fetch(url, opts);
  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`;
    try {
      const j = await resp.json();
      if (j && j.detail) detail = j.detail;
    } catch (_) {}
    const err = new Error(detail);
    err.status = resp.status;
    throw err;
  }
  if (resp.status === 204) return null;
  return resp.json();
}

window.API = {
  bootstrap: () => request('GET', '/api/v1/bootstrap'),
  dashboard: () => request('GET', '/api/v1/dashboard'),
  listUsers: () => request('GET', '/api/v1/users'),
  addUser: (username) => request('POST', '/api/v1/users', { username }),
  deleteUser: (username) => request('DELETE', `/api/v1/users/${encodeURIComponent(username)}`),
  toggleList: (username, listId) =>
    request('POST', `/api/v1/users/${encodeURIComponent(username)}/lists/${listId}/toggle`),
  saveListSettings: (username, listId, body) =>
    request('POST', `/api/v1/users/${encodeURIComponent(username)}/lists/${listId}/settings`, body),
  listCustomLists: () => request('GET', '/api/v1/custom-lists'),
  getCustomList: (slug) => request('GET', `/api/v1/custom-lists/${encodeURIComponent(slug)}`),
  createCustomList: (body) => request('POST', '/api/v1/custom-lists', body),
  updateCustomList: (slug, body) =>
    request('PUT', `/api/v1/custom-lists/${encodeURIComponent(slug)}`, body),
  deleteCustomList: (slug) =>
    request('DELETE', `/api/v1/custom-lists/${encodeURIComponent(slug)}`),
  previewCustomList: (body) => request('POST', '/api/v1/custom-lists/preview', body),
  activity: (since = 0, level = null) => {
    const params = new URLSearchParams({ since: String(since) });
    if (level && level !== 'All') params.set('level', level);
    return request('GET', `/api/v1/activity?${params.toString()}`);
  },
  activityDownloadUrl: () => '/api/v1/activity/download',
};

window.MOCK = {
  formatRelative,
  formatDateShort,
};
