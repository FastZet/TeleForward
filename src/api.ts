let csrfTokenMemory: string | null = null;
let sessionTokenMemory: string | null = localStorage.getItem('teleroute_session_token');

export function setAuthTokens(csrf: string | null, sessionToken?: string | null) {
  csrfTokenMemory = csrf;
  if (sessionToken !== undefined) {
    sessionTokenMemory = sessionToken;
    if (sessionToken) {
      localStorage.setItem('teleroute_session_token', sessionToken);
    } else {
      localStorage.removeItem('teleroute_session_token');
    }
  }
}

export async function apiRequest<T = any>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const headers = new Headers(options.headers || {});
  if (!headers.has('Content-Type') && options.body) {
    headers.set('Content-Type', 'application/json');
  }
  if (csrfTokenMemory) {
    headers.set('X-CSRF-Token', csrfTokenMemory);
  }
  if (sessionTokenMemory) {
    headers.set('X-Session-Token', sessionTokenMemory);
  }

  const res = await fetch(path, {
    ...options,
    headers,
    credentials: 'include',
  });

  const contentType = res.headers.get('content-type') || '';
  const data = contentType.includes('application/json') ? await res.json() : await res.text();

  if (!res.ok) {
    const message =
      typeof data === 'object' && data !== null && 'message' in data
        ? String((data as any).message)
        : `Request failed with status ${res.status}`;
    throw new Error(message);
  }

  return data as T;
}
