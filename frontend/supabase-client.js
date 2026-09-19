const sessionKey = 'sarap-auth-session-v1';

function config() {
  return window.SARAP_CONFIG || {};
}

export function isSupabaseConfigured() {
  const value = config();
  return Boolean(value.SUPABASE_URL && value.SUPABASE_ANON_KEY);
}

function authUrl(path) {
  return `${config().SUPABASE_URL.replace(/\/$/, '')}/auth/v1${path}`;
}

function restUrl(path) {
  return `${config().SUPABASE_URL.replace(/\/$/, '')}/rest/v1${path}`;
}

function redirectUrl() {
  if (config().AUTH_REDIRECT_URL) return config().AUTH_REDIRECT_URL.replace(/\/$/, '') + '/';
  if (location.protocol !== 'file:') return `${location.origin}${location.pathname}`;
  return config().API_URL || 'http://127.0.0.1:8000/';
}

function readSession() {
  try { return JSON.parse(localStorage.getItem(sessionKey) || 'null'); }
  catch { return null; }
}

function writeSession(value) {
  if (!value) localStorage.removeItem(sessionKey);
  else localStorage.setItem(sessionKey, JSON.stringify(value));
}

function normalizeSession(payload) {
  if (!payload?.access_token) return null;
  const session = {
    access_token: payload.access_token,
    refresh_token: payload.refresh_token,
    expires_at: payload.expires_at || Math.floor(Date.now() / 1000) + Number(payload.expires_in || 3600),
    token_type: payload.token_type || 'bearer',
    user: payload.user || null,
  };
  writeSession(session);
  return session;
}

async function request(url, options = {}) {
  if (!isSupabaseConfigured()) throw new Error('Supabase is not configured yet');
  const headers = { apikey: config().SUPABASE_ANON_KEY, 'Content-Type': 'application/json', ...(options.headers || {}) };
  const controller = new AbortController();
  let timeout;
  const deadline = new Promise((_, reject) => {
    timeout = setTimeout(() => {
      controller.abort();
      reject(new Error('The secure connection timed out. Please try again.'));
    }, 7000);
  });
  try {
    const response = await Promise.race([fetch(url, { ...options, headers, signal: controller.signal }), deadline]);
    const text = await response.text();
    let payload = null;
    try { payload = text ? JSON.parse(text) : null; } catch { payload = text; }
    if (!response.ok) throw new Error(payload?.msg || payload?.message || payload?.error_description || payload?.error || `Request failed (${response.status})`);
    return payload;
  } catch (error) {
    if (error?.name === 'AbortError') throw new Error('The secure connection timed out. Please try again.');
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

async function refreshSession(session) {
  if (!session?.refresh_token) return null;
  try {
    const payload = await request(authUrl('/token?grant_type=refresh_token'), { method: 'POST', body: JSON.stringify({ refresh_token: session.refresh_token }) });
    return normalizeSession(payload);
  } catch {
    writeSession(null);
    return null;
  }
}

export async function restoreSession() {
  let session = readSession();
  if (!session) return null;
  if (Number(session.expires_at || 0) < Math.floor(Date.now() / 1000) + 60) session = await refreshSession(session);
  if (!session) return null;
  // Supabase already returns the verified user during sign-in. Reuse it until
  // the token is close to expiry instead of making a /user request before
  // every dashboard API call.
  if (session.user?.id) return session;
  try {
    const user = await request(authUrl('/user'), { headers: { Authorization: `Bearer ${session.access_token}` } });
    session.user = user;
    writeSession(session);
    return session;
  } catch (error) {
    if (/timed out|failed to fetch|network|load failed/i.test(String(error?.message || error))) {
      writeSession(null);
      return null;
    }
    return refreshSession(session);
  }
}

export function consumeAuthCallback() {
  const hash = new URLSearchParams(location.hash.replace(/^#/, ''));
  const query = new URLSearchParams(location.search);
  const error = hash.get('error_description') || query.get('error_description');
  if (error) {
    history.replaceState({}, document.title, location.pathname);
    throw new Error(error);
  }
  const accessToken = hash.get('access_token') || query.get('access_token');
  if (!accessToken) return null;
  const session = normalizeSession({
    access_token: accessToken,
    refresh_token: hash.get('refresh_token') || query.get('refresh_token'),
    expires_in: hash.get('expires_in') || query.get('expires_in'),
    token_type: hash.get('token_type') || query.get('token_type'),
  });
  const type = hash.get('type') || query.get('type');
  history.replaceState({}, document.title, location.pathname);
  return { session, type };
}

export async function signUp({ email, password, fullName, businessName }) {
  const url = `${authUrl('/signup')}?redirect_to=${encodeURIComponent(redirectUrl())}`;
  const payload = await request(url, { method: 'POST', body: JSON.stringify({ email, password, data: { full_name: fullName, business_name: businessName } }) });
  return { user: payload?.user || null, session: normalizeSession(payload) };
}

export async function signIn({ email, password }) {
  const payload = await request(authUrl('/token?grant_type=password'), { method: 'POST', body: JSON.stringify({ email, password }) });
  return normalizeSession(payload);
}

export async function resendConfirmation(email) {
  const url = `${authUrl('/resend')}?redirect_to=${encodeURIComponent(redirectUrl())}`;
  return request(url, { method: 'POST', body: JSON.stringify({ type: 'signup', email }) });
}

export async function sendPasswordRecovery(email) {
  const url = `${authUrl('/recover')}?redirect_to=${encodeURIComponent(redirectUrl())}`;
  return request(url, { method: 'POST', body: JSON.stringify({ email }) });
}

export async function updatePassword(password) {
  const session = await restoreSession();
  if (!session) throw new Error('The recovery link has expired. Request a new one.');
  return request(authUrl('/user'), { method: 'PUT', headers: { Authorization: `Bearer ${session.access_token}` }, body: JSON.stringify({ password }) });
}

export async function signOut() {
  const session = readSession();
  if (session?.access_token) {
    try { await request(authUrl('/logout'), { method: 'POST', headers: { Authorization: `Bearer ${session.access_token}` } }); }
    catch { /* The local session must still be cleared. */ }
  }
  writeSession(null);
}

export async function apiAuthHeaders() {
  if (!isSupabaseConfigured()) return {};
  const session = await restoreSession();
  if (!session) throw new Error('Your session has expired. Please log in again.');
  return { Authorization: `Bearer ${session.access_token}` };
}

async function authorizedSession() {
  const session = await restoreSession();
  if (!session) throw new Error('Your session has expired. Please log in again.');
  return session;
}

export async function rpc(name, body = {}) {
  const session = await authorizedSession();
  return request(restUrl(`/rpc/${name}`), {
    method: 'POST',
    headers: { Authorization: `Bearer ${session.access_token}`, Prefer: 'return=representation' },
    body: JSON.stringify(body),
  });
}

export async function db(path, { method = 'GET', body, prefer = 'return=representation' } = {}) {
  const session = await authorizedSession();
  const options = { method, headers: { Authorization: `Bearer ${session.access_token}`, Prefer: prefer } };
  if (body !== undefined) options.body = JSON.stringify(body);
  return request(restUrl(path), options);
}

export async function loadWorkspace() {
  return rpc('get_my_workspace');
}

export async function completeWorkspace(business) {
  return rpc('complete_workspace', {
    p_name: business.name,
    p_website: business.website || null,
    p_industry: business.industry || null,
    p_country: business.country || 'Kazakhstan',
    p_city: business.city || null,
    p_location_count: Number(business.locations || 1),
    p_aliases: business.aliases || [],
  });
}
