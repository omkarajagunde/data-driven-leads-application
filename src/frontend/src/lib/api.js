// Every call goes through the dev server's /api proxy, which adds the API key.
const cache = new Map();

export function api(path) {
  if (!cache.has(path)) {
    const request = fetch(`/api${path}`).then((res) => {
      if (!res.ok) throw new Error(`${path} answered ${res.status}`);
      return res.json();
    });
    request.catch(() => cache.delete(path));
    cache.set(path, request);
  }
  return cache.get(path);
}

export async function post(path, body) {
  const res = await fetch(`/api${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Please check the form and try again.');
  return data;
}

// In development the API runs on its own port; in the built page it is the same server.
export const DOCS_URL = import.meta.env.VITE_API_DOCS || (import.meta.env.DEV ? 'http://localhost:8000/docs' : '/docs');
