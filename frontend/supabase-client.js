import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm';

const legacySessionKey = 'sarap-auth-session-v1';
let client = null;
let legacySessionMigrated = false;

function config() {
  return window.SARAP_CONFIG || {};
}

export function isSupabaseConfigured() {
  const value = config();
  return Boolean(value.SUPABASE_URL && value.SUPABASE_ANON_KEY);
}

function requireConfig() {
  if (!isSupabaseConfigured()) throw new Error('Supabase is not configured yet');
}

function restUrl(path) {
  return `${config().SUPABASE_URL.replace(/\/$/, '')}/rest/v1${path}`;
}

function redirectUrl() {
  if (config().AUTH_REDIRECT_URL) return config().AUTH_REDIRECT_URL.replace(/\/$/, '') + '/';
  if (location.protocol !== 'file:') return `${location.origin}${location.pathname}`;
  return config().API_URL || 'http://127.0.0.1:8000/';
}

function getSupabaseClient() {
  requireConfig();
  if (!client) {
    client = createClient(config().SUPABASE_URL, config().SUPABASE_ANON_KEY, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
      },
    });
  }
  return client;
}

function readLegacySession() {
  try { return JSON.parse(localStorage.getItem(legacySessionKey) || 'null'); }
  catch { return null; }
}

async function migrateLegacySession() {
  if (legacySessionMigrated) return;
  legacySessionMigrated = true;
  const legacy = readLegacySession();
  if (!legacy?.access_token || !legacy?.refresh_token) return;
  const { error } = await getSupabaseClient().auth.setSession({
    access_token: legacy.access_token,
    refresh_token: legacy.refresh_token,
  });
  if (!error) localStorage.removeItem(legacySessionKey);
}

function parseAuthCallback() {
  const hash = new URLSearchParams(location.hash.replace(/^#/, ''));
  const query = new URLSearchParams(location.search);
  const error = hash.get('error_description') || query.get('error_description');
  const type = hash.get('type') || query.get('type');
  const hasAuthParams = Boolean(
    hash.get('access_token') ||
    hash.get('refresh_token') ||
    hash.get('error') ||
    query.get('code') ||
    query.get('error')
  );
  return { error, type, hasAuthParams };
}

function cleanAuthCallbackUrl() {
  if (location.protocol === 'file:') return;
  history.replaceState({}, document.title, location.pathname);
}

async function request(url, options = {}) {
  requireConfig();
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

function ensureSession(payload) {
  const session = payload?.session || payload;
  if (!session?.access_token) return null;
  return session;
}

function authErrorMessage(error) {
  return error?.message || 'Authentication failed. Please try again.';
}

export async function restoreSession() {
  await migrateLegacySession();
  const { data, error } = await getSupabaseClient().auth.getSession();
  if (error) throw new Error(authErrorMessage(error));
  return data?.session || null;
}

export function consumeAuthCallback() {
  const callback = parseAuthCallback();
  if (callback.error) {
    cleanAuthCallbackUrl();
    throw new Error(callback.error);
  }
  return callback.hasAuthParams || callback.type ? { type: callback.type || null } : null;
}

export function onAuthStateChange(handler) {
  return getSupabaseClient().auth.onAuthStateChange((event, session) => handler(event, session));
}

export async function signUp({ email, password, fullName, businessName }) {
  const { data, error } = await getSupabaseClient().auth.signUp({
    email,
    password,
    options: {
      data: { full_name: fullName, business_name: businessName },
      emailRedirectTo: redirectUrl(),
    },
  });
  if (error) throw new Error(authErrorMessage(error));
  return { user: data?.user || null, session: data?.session || null };
}

export async function signIn({ email, password }) {
  const { data, error } = await getSupabaseClient().auth.signInWithPassword({ email, password });
  if (error) throw new Error(authErrorMessage(error));
  return ensureSession(data);
}

export async function resendConfirmation(email) {
  const { error } = await getSupabaseClient().auth.resend({
    type: 'signup',
    email,
    options: { emailRedirectTo: redirectUrl() },
  });
  if (error) throw new Error(authErrorMessage(error));
  return true;
}

export async function sendPasswordRecovery(email) {
  const { error } = await getSupabaseClient().auth.resetPasswordForEmail(email, { redirectTo: redirectUrl() });
  if (error) throw new Error(authErrorMessage(error));
  return true;
}

export async function updatePassword(password) {
  const session = await restoreSession();
  if (!session) throw new Error('The recovery link has expired. Request a new one.');
  const { data, error } = await getSupabaseClient().auth.updateUser({ password });
  if (error) throw new Error(authErrorMessage(error));
  return data;
}

export async function signOut() {
  const supabase = getSupabaseClient();
  const { error } = await supabase.auth.signOut();
  if (error) await supabase.auth.signOut({ scope: 'local' });
  localStorage.removeItem(legacySessionKey);
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
