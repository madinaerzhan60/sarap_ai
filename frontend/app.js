import { apiAuthHeaders, completeWorkspace, consumeAuthCallback, db, isSupabaseConfigured, loadWorkspace, onAuthStateChange, resendConfirmation, restoreSession, sendPasswordRecovery, signIn, signOut, signUp, updatePassword } from './supabase-client.js?v=5';

try {
  const embeddedConfig = document.querySelector('#sarap-config')?.textContent;
  if (embeddedConfig) window.SARAP_CONFIG = { ...(window.SARAP_CONFIG || {}), ...JSON.parse(embeddedConfig) };
} catch { /* A malformed optional config falls back to the public endpoint below. */ }

const app = document.querySelector('#app');
const storeKey = 'sarap-mvp-state-v1';

async function loadPublicConfig() {
  if (location.protocol === 'file:') return; 
  if (window.SARAP_CONFIG?.SUPABASE_URL && window.SARAP_CONFIG?.SUPABASE_ANON_KEY) return;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 2500);
  try {
    const response = await fetch('/api/public-config', { signal: controller.signal });
    if (response.ok) {
      const remote = await response.json();
      const configured = Object.fromEntries(Object.entries(remote).filter(([, value]) => value !== '' && value != null));
      window.SARAP_CONFIG = {
  ...(window.SARAP_CONFIG || {}),
  ...configured
};
    }
  } catch { /* Local standalone demo keeps blank config and uses demo auth. */ }
  finally { clearTimeout(timeout); }
}

const icons = {
  overview: '<svg class="icon" viewBox="0 0 24 24" fill="none"><path d="M4 13h6V4H4v9Zm10 7h6V11h-6v9ZM4 20h6v-3H4v3Zm10-13h6V4h-6v3Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/></svg>',
  mentions: '<svg class="icon" viewBox="0 0 24 24" fill="none"><path d="M5 6.5h14M5 11.5h9M5 16.5h6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><path d="M4 3.5h16a1 1 0 0 1 1 1v15l-4-3H4a1 1 0 0 1-1-1v-11a1 1 0 0 1 1-1Z" stroke="currentColor" stroke-width="1.5"/></svg>',
  analytics: '<svg class="icon" viewBox="0 0 24 24" fill="none"><path d="M4 19V9m6 10V5m6 14v-7m4 7H2" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>',
  alerts: '<svg class="icon" viewBox="0 0 24 24" fill="none"><path d="M18 9a6 6 0 1 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9ZM10 21h4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  sources: '<svg class="icon" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="3" stroke="currentColor" stroke-width="1.7"/><path d="M4.2 15.2a8.5 8.5 0 0 1 0-6.4m15.6 0a8.5 8.5 0 0 1 0 6.4M1.7 18.5a13 13 0 0 1 0-13m20.6 0a13 13 0 0 1 0 13" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>',
  discover: '<svg class="icon" viewBox="0 0 24 24" fill="none"><circle cx="11" cy="11" r="7" stroke="currentColor" stroke-width="1.7"/><path d="m16 16 5 5M11 8v6m-3-3h6" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>',
  settings: '<svg class="icon" viewBox="0 0 24 24" fill="none"><path d="M12 15.2a3.2 3.2 0 1 0 0-6.4 3.2 3.2 0 0 0 0 6.4Z" stroke="currentColor" stroke-width="1.7"/><path d="M19 13.2a7.4 7.4 0 0 0 0-2.4l2-1.6-2-3.4-2.5 1a8 8 0 0 0-2-1.2L14 3h-4l-.5 2.6a8 8 0 0 0-2 1.2l-2.5-1-2 3.4 2 1.6a7.4 7.4 0 0 0 0 2.4l-2 1.6 2 3.4 2.5-1a8 8 0 0 0 2 1.2L10 21h4l.5-2.6a8 8 0 0 0 2-1.2l2.5 1 2-3.4-2-1.6Z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>',
  radar: '<svg class="icon" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="8" stroke="currentColor" stroke-width="1.5"/><circle cx="12" cy="12" r="4" stroke="currentColor" stroke-width="1.5"/><path d="M12 12 18 6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><circle cx="12" cy="12" r="1.3" fill="currentColor"/></svg>',
  review: '<svg class="icon" viewBox="0 0 24 24" fill="none"><path d="m12 3 2.6 5.3 5.9.8-4.2 4.1 1 5.8-5.3-2.8L6.7 19l1-5.8-4.2-4.1 5.9-.8L12 3Z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>',
  web: '<svg class="icon" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="1.6"/><path d="M3 12h18M12 3c2.4 2.5 3.6 5.5 3.6 9s-1.2 6.5-3.6 9c-2.4-2.5-3.6-5.5-3.6-9S9.6 5.5 12 3Z" stroke="currentColor" stroke-width="1.4"/></svg>',
  news: '<svg class="icon" viewBox="0 0 24 24" fill="none"><path d="M4 5h13v14H5a1 1 0 0 1-1-1V5Zm13 4h3v9a1 1 0 0 1-1 1h-2" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M7 9h7M7 12h7m-7 3h4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>',
  admin: '<svg class="icon" viewBox="0 0 24 24" fill="none"><path d="M12 3 4.5 6v5.5c0 4.7 3.1 7.8 7.5 9.5 4.4-1.7 7.5-4.8 7.5-9.5V6L12 3Z" stroke="currentColor" stroke-width="1.6"/><path d="M9 12h6M12 9v6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
};

const logo = () => `<span class="brand" aria-label="sarap"><span class="brand-word">sarap<span>.</span></span></span>`;

const INDUSTRIES = ['Restaurants & cafés','Retail','Education','Healthcare','Hospitality','Services','Other'];

function deterministicAliases(name='') {
  const clean=String(name).trim().replace(/\s+/g,' ');
  if(!clean)return [];
  const parts=clean.split(' ').filter(word=>!['university','college','school','company','restaurant','cafe','café','hotel','clinic','shop'].includes(word.toLowerCase()));
  const acronym=(parts.length>1?parts:clean.split(' ')).map(word=>word[0]).join('').toUpperCase();
  const aliases=[clean];
  if(acronym.length>=2)aliases.push(acronym);
  if(/^SDU(?: University)?$/i.test(clean))aliases.push('SDU University','Suleyman Demirel University','СДУ','Сулейман Демирель университеті','Сулейман Демирель университет');
  const transliterated=clean.toLowerCase().replace(/[аә]/g,'a').replace(/[б]/g,'b').replace(/[в]/g,'v').replace(/[гғ]/g,'g').replace(/[д]/g,'d').replace(/[её]/g,'e').replace(/[ж]/g,'zh').replace(/[з]/g,'z').replace(/[иі]/g,'i').replace(/[й]/g,'y').replace(/[кқ]/g,'k').replace(/[л]/g,'l').replace(/[м]/g,'m').replace(/[нң]/g,'n').replace(/[оө]/g,'o').replace(/[п]/g,'p').replace(/[р]/g,'r').replace(/[с]/g,'s').replace(/[т]/g,'t').replace(/[уұү]/g,'u').replace(/[ф]/g,'f').replace(/[хһ]/g,'h').replace(/[ц]/g,'ts').replace(/[ч]/g,'ch').replace(/[шщ]/g,'sh').replace(/[ы]/g,'y').replace(/[э]/g,'e').replace(/[ю]/g,'yu').replace(/[я]/g,'ya').replace(/[ьъ]/g,'');
  if(transliterated!==clean.toLowerCase())aliases.push(transliterated);
  return [...new Set(aliases.map(value=>value.trim()).filter(Boolean))];
}

const demoMentions = [
  { id:'m3', source:'2GIS', type:'review', author:'Aigerim K.', time:'Yesterday', text:'Заказ ждала 40 минут. Персонал даже не объяснил причину, больше не приду.', sentiment:'negative', language:'Russian', risk:76, aspects:[['Wait time','neg'],['Staff','neg']], rating:1, reviewed:false },
];

const demoDiscoveries = [
  { id:'d1', source:'Threads', type:'social', author:'@altyn.ai', time:'18 min ago', text:'Again waited 40 minutes at Coffee Boom Dostyk. Coffee is good, service is not.', sentiment:'negative', language:'English', risk:72, aspects:[['Service','neg'],['Wait time','neg']], reviewed:false },
  { id:'d2', source:'The Village KZ', type:'news', author:'Editorial', time:'Today, 09:20', text:'Coffee Boom opens a new location in Astana with a larger bakery menu.', sentiment:'neutral', language:'English', risk:8, aspects:[['Expansion','pos']], reviewed:false },
  { id:'d3', source:'Reddit', type:'forum', author:'u/almatyfoodie', time:'Yesterday', text:'Қай жерде жақсы кофе? Coffee Boom-дағы атмосфера ұнайды, бірақ кешке кезек көп.', sentiment:'mixed', language:'Mixed KZ/RU', risk:35, aspects:[['Atmosphere','pos'],['Wait time','neg']], reviewed:false },
];

const defaultState = {
  session: null,
  accountUserId: null,
  pendingEmail: '',
  business: { id:'00000000-0000-0000-0000-000000000001', name:'Coffee Boom Test', website:'coffeeboom.kz', industry:'Restaurants & cafés', country:'Kazakhstan', city:'Almaty', locations:3, aliases:['Coffee Boom','Coffeeboom','Кофе Бум'], handle:'@coffeeboom.kz' },
  onboardingStep: 1,
  route: 'landing',
  mentions: demoMentions,
  discoveries: demoDiscoveries,
  sources: [
    { id:'s1', name:'2GIS', kind:'Monitored', method:'Auto · URL fallback', status:'Active', state:'live', description:'Focused monitoring of the public business URL when collection is permitted.', last:'4 min ago', next:'6 min', items:83, errors:0 },
    { id:'s2', name:'Google Business', kind:'Official', method:'Auto · API preferred', status:'API ready', state:'live', description:'Uses the official API after OAuth; URL fallback can be configured separately.', last:'2 min ago', next:'Live events', items:41, errors:0 },
    { id:'s3', name:'Instagram', kind:'Official', method:'API only', status:'Not connected', state:'', description:'Connect with Meta OAuth to monitor account mentions and comments.', last:'—', next:'—', items:0, errors:0 },
    { id:'s4', name:'CSV Import', kind:'Imported', method:'Import', status:'Ready', state:'', description:'Upload historical reviews in CSV or JSON format.', last:'Sep 12', next:'Manual', items:22, errors:0 },
  ],
  alerts: [
    { id:'a1', severity:'High', source:'2GIS', time:'1 hour ago', aspect:'Staff', risk:76, text:'Заказ ждала 40 минут. Персонал даже не объяснил причину.', status:'New' },
    { id:'a2', severity:'High', source:'Threads', time:'3 hours ago', aspect:'Wait time', risk:72, text:'Again waited 40 minutes at Coffee Boom Dostyk.', status:'Viewed' },
    { id:'a3', severity:'Medium', source:'Instagram', time:'Yesterday', aspect:'Delivery', risk:48, text:'Доставканы долго күттім, бірақ дәмі керемет еді.', status:'Resolved' },
  ],
  settings: { telegram:true, email:false, threshold:'High + Critical', tone:'Warm and professional', customAspects:'', retention:'12 months' },
  admin: null,
  analytics: null,
  recommendations: null,
};
const emptyBusiness = {id:null,name:'',website:'',industry:'',country:'Kazakhstan',city:'',locations:1,aliases:[],handle:''};

let state = loadState();
let currentSettingsTab = 'Business profile';
let authReady = false;
let authSubscription = null;
let pendingExtractedReviews = [];
let pendingSourceImport = null;
const syncingSourceIds = new Set();

function loadState() {
  try {
    const saved={ ...structuredClone(defaultState), ...JSON.parse(localStorage.getItem(storeKey) || '{}') };
    saved.mentions=(saved.mentions||[]).filter(item=>!['m1','m4'].includes(item.id));
    return saved;
  }
  catch { return structuredClone(defaultState); }
}
function saveState() { localStorage.setItem(storeKey, JSON.stringify(state)); }
function escapeHtml(value='') { return String(value).replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c])); }
function toast(title, detail='') {
  if(/failed to fetch|networkerror|load failed/i.test(String(detail)))detail='Could not reach SARAP API. Check the server connection and try again.';
  const el = document.createElement('div'); el.className='toast'; el.innerHTML=`<strong>${escapeHtml(title)}</strong><small>${escapeHtml(detail)}</small>`;
  document.querySelector('#toast-region').append(el); setTimeout(()=>el.remove(), 3800);
}
function friendlyError(error) {
  const message=String(error?.message||error||'').trim();
  if(/failed to fetch|networkerror|load failed|api is unavailable/i.test(message))return 'SARAP could not reach the server. Try again in a moment.';
  if(/already|duplicate|unique/i.test(message))return 'This source is already connected.';
  if(/401|403|unauthor|forbidden|token|credential/i.test(message))return 'This connection needs valid access in Source settings → Advanced integration.';
  if(/telegram.{0,80}(not configured|missing)|missing.{0,80}telegram/i.test(message))return 'Telegram monitoring is not configured yet.';
  if(/captcha|verification|robots\.txt|blocked|not allow/i.test(message))return 'The website blocked automatic collection. Try Sync later or connect an advanced integration.';
  if(/timeout|timed out/i.test(message))return 'The source took too long to respond. Try again.';
  if(/playwright|chromium|browsertype|scrapfly|apify|collector returned no structured|collection failed through/i.test(message))return 'Automatic collection is temporarily unavailable. Try Sync again later.';
  return message||'Something went wrong. Check the details and try again.';
}
function setRoute(route) { state.route=['analytics','alerts'].includes(route)?'overview':route; if(location.protocol!=='file:')history.replaceState(null,'',state.route==='admin'?'/admin':'/'); saveState(); render(); window.scrollTo(0,0); if(state.route==='admin')loadAdminData(); if(state.route==='overview')loadAnalyticsData(); }
function initials(name='SARAP User') { return name.split(/\s+/).slice(0,2).map(x=>x[0]).join('').toUpperCase(); }
function sourceIcon(source) { const s=source.toLowerCase(); return s.includes('news')||s.includes('village')?icons.news:s.includes('web')||s.includes('reddit')||s.includes('threads')?icons.web:icons.review; }

function landing() {
  return `<main class="landing-shell landing-minimal"><nav class="landing-nav">${logo()}<div class="nav-actions"><button class="btn btn-secondary" data-action="login">Log in</button><button class="btn btn-primary" data-action="register">Create account</button></div></nav><section class="hero"><h1>Know what people say about your <span>business.</span></h1><p>Reviews, mentions and clear actions in one place.</p><div class="hero-actions"><button class="btn btn-secondary" data-action="login">Log in</button><button class="btn btn-primary" data-action="register">Create account</button></div></section></main>`;
}

function auth(mode='login') {
  const register = mode==='register';
  return `<main class="center-shell"><section class="auth-story"><button class="form-link" data-action="landing">← Back</button><div style="margin-top:25px">${logo()}</div><h1>${register?'Create your account.':'Welcome back.'}</h1><p>${register?'Set up your workspace in a few steps.':'Log in to continue.'}</p></section><form class="form-card glass" data-form="auth"><h2>${register?'Create account':'Log in'}</h2><p>${register?'We will email you a confirmation link.':'Enter your account details.'}</p>${register?'<div class="field-grid"><div class="field"><label>Business name</label><input name="business" required autocomplete="organization" placeholder="Coffee Boom"></div><div class="field"><label>Full name</label><input name="name" required autocomplete="name" placeholder="Aigerim S."></div></div>':''}<div class="field"><label>Email</label><input name="email" type="email" required autocomplete="email" placeholder="you@gmail.com"></div><div class="field"><label>Password</label><input name="password" type="password" minlength="8" required autocomplete="${register?'new-password':'current-password'}" placeholder="At least 8 characters"></div>${register?'<div class="field"><label>Repeat password</label><input name="passwordConfirm" type="password" minlength="8" required autocomplete="new-password" placeholder="Repeat password"></div>':''}${!register?'<button type="button" class="form-link auth-helper" data-action="forgot-password">Forgot password?</button>':''}<div class="form-actions"><button type="button" class="form-link" data-action="${register?'login':'register'}">${register?'Log in instead':'Create account'}</button><button class="btn btn-primary" type="submit">${register?'Create account':'Log in'} →</button></div></form></main>`;
}

function verifyEmail() {
  return `<main class="center-shell single-card"><section class="form-card glass auth-status">${logo()}<div class="mail-orbit">✉</div><h2>Check your email</h2><p>Open the confirmation link sent to <strong>${escapeHtml(state.pendingEmail||'your email')}</strong>, then return here.</p><div class="form-actions stacked"><button class="btn btn-primary" data-action="check-confirmation">I confirmed my email</button><button class="btn btn-secondary" data-action="resend-confirmation">Send again</button><button class="form-link" data-action="login">Back to login</button></div></section></main>`;
}

function forgotPassword() {
  return `<main class="center-shell single-card"><form class="form-card glass" data-form="forgot"><button type="button" class="form-link" data-action="login">← Back to login</button><div class="eyebrow" style="margin-top:26px">Account recovery</div><h2>Reset your password</h2><p>Enter your confirmed email. We will send a secure recovery link.</p><div class="field"><label>Email</label><input name="email" type="email" required autocomplete="email" value="${escapeHtml(state.pendingEmail)}" placeholder="you@gmail.com"></div><div class="form-actions"><span></span><button class="btn btn-primary">Send recovery link</button></div></form></main>`;
}

function resetPassword() {
  return `<main class="center-shell single-card"><form class="form-card glass" data-form="reset-password"><div class="eyebrow">Secure recovery</div><h2>Choose a new password</h2><p>The password must contain at least eight characters.</p><div class="field"><label>New password</label><input name="password" type="password" minlength="8" required autocomplete="new-password"></div><div class="field"><label>Repeat password</label><input name="passwordConfirm" type="password" minlength="8" required autocomplete="new-password"></div><div class="form-actions"><span></span><button class="btn btn-primary">Save new password</button></div></form></main>`;
}

function authLoading() {
  return '<main class="center-shell"><section class="form-card glass"><h2>Opening SARAP…</h2><p>Checking your secure session.</p><div class="skeleton"></div></section></main>';
}

function onboarding() {
  const step=state.onboardingStep;
  const industryOptions=INDUSTRIES.map(value=>`<option ${state.business.industry===value?'selected':''}>${value}</option>`).join('');
  const stepFields = step===1
    ? `<div class="field-grid"><div class="field"><label>Business name</label><input name="name" required value="${escapeHtml(state.business.name)}" placeholder="SDU University"></div><div class="field"><label>Industry</label><select name="industry">${industryOptions}</select></div><div class="field"><label>Country</label><input name="country" required value="${escapeHtml(state.business.country||'Kazakhstan')}"></div><div class="field"><label>City</label><input name="city" required value="${escapeHtml(state.business.city)}" placeholder="Almaty"></div></div><div class="field"><label>Custom industry <span class="muted">(only for Other)</span></label><input name="customIndustry" value="${escapeHtml(state.business.customIndustry||'')}" placeholder="Optional"></div>`
    : step===2
      ? `<div class="setup-summary"><span class="source-icon">${icons.radar}</span><div><strong>We will set up brand matching automatically</strong><p>SARAP creates search aliases from the business name. You can edit them later in Settings → Business profile.</p></div></div><div class="summary"><strong>${escapeHtml(state.business.name)}</strong><br>${escapeHtml(state.business.industry)} · ${escapeHtml(state.business.city)}, ${escapeHtml(state.business.country)}</div>`
      : `<div class="setup-summary"><span class="source-icon">${icons.sources}</span><div><strong>Connect your first sources</strong><p>You can open the workspace now and connect sources later.</p></div></div><div class="onboarding-source-actions"><button type="button" class="btn btn-secondary" data-action="onboarding-add-source">+ Add source</button><button class="btn btn-primary" type="submit">Open workspace →</button></div>`;
  return `<main class="center-shell"><section class="auth-story"><button class="form-link" data-action="logout">← Sign out</button><div style="margin-top:25px">${logo()}</div><h1>Set up your workspace.</h1><p>Only the details SARAP needs to start.</p></section><form class="form-card glass" data-form="onboarding"><div class="eyebrow">Step ${step} of 3</div><h2>${step===1?'Tell us about the business':step===2?'Confirm your workspace':'Connect your first sources'}</h2><p>${step===1?'Add the basic business details.':step===2?'Search aliases will be created automatically.':'Add a source now or continue without one.'}</p><div class="stepper"><i class="step active"></i><i class="step ${step>1?'active':''}"></i><i class="step ${step>2?'active':''}"></i></div>${stepFields}${step<3?`<div class="form-actions">${step>1?'<button type="button" class="btn btn-secondary" data-action="onboarding-back">Back</button>':'<span></span>'}<button class="btn btn-primary" type="submit">Continue →</button></div>`:''}</form></main>`;
}

const navItems = [['overview','Overview'],['mentions','Mentions'],['sources','Sources'],['discover','Discover'],['settings','Settings']];
function topbar() {
  const newAlerts=state.alerts.filter(a=>a.status==='New').length;
  const items=state.session?.role==='admin'?[...navItems,['admin','Admin']]:navItems;
  return `<header class="topbar"><div class="topbar-inner"><div class="topbar-start">${logo()}<button class="workspace-switcher" title="Current workspace"><span>Workspace</span><strong>${escapeHtml(state.business.name||'No workspace')}</strong><i>⌄</i></button></div><nav class="top-nav" aria-label="Main navigation">${items.map(([id,label])=>`<button class="top-link ${state.route===id?'active':''}" data-route="${id}" title="${label}" aria-label="${label}">${icons[id]}<span>${label}</span>${id==='overview'&&newAlerts?`<b class="top-badge">${newAlerts}</b>`:''}</button>`).join('')}</nav><div class="topbar-user"><div class="avatar">${initials(state.session?.name)}</div><div class="user-copy"><strong>${escapeHtml(state.session?.name||'Demo Founder')}</strong><small>${escapeHtml(state.session?.email||'demo@sarap.kz')}</small></div><button class="btn btn-quiet logout-button" title="Log out" data-action="logout">Log out ↗</button></div></div></header>`;
}
function appShell(content) { return `<div class="app-shell">${topbar()}<main class="app-main">${content}</main></div>`; }
function pageHead(title, subtitle, actions='') { return `<header class="page-head"><div><h1>${title}</h1><p>${subtitle}</p></div><div class="head-actions">${actions}</div></header>`; }

function overview() {
  const total=state.mentions.length, positive=state.mentions.filter(m=>m.sentiment==='positive').length, negative=state.mentions.filter(m=>m.sentiment==='negative').length, high=state.mentions.filter(m=>m.risk>=60).length;
  const positiveRate=total?Math.round(positive/total*100):0, negativeRate=total?Math.round(negative/total*100):0, maxRisk=total?Math.max(...state.mentions.map(m=>m.risk)):0;
  return pageHead('Your reputation, in focus.','Analytics, recommendations and active alerts in one place.','<button class="btn btn-secondary" data-action="refresh-recommendations">Refresh AI analysis</button><select class="date-select" aria-label="Date range"><option>Last 7 days</option><option>Last 30 days</option><option>Last 90 days</option></select>')+
  `<section class="grid metric-grid"><article class="metric-card glass"><span class="metric-label">Positive sentiment</span><div class="metric-value good">${positiveRate}%</div><span class="metric-change">${positive} positive mentions</span></article><article class="metric-card glass"><span class="metric-label">Collected mentions</span><div class="metric-value">${total}</div><span class="metric-change">in this workspace</span></article><article class="metric-card glass"><span class="metric-label">Negative rate</span><div class="metric-value warning">${negativeRate}%</div><span class="metric-change">${negative} negative mentions</span></article><article class="metric-card glass"><span class="metric-label">High-risk signals</span><div class="metric-value ${high?'danger':'good'}">${high}</div><span class="metric-change">risk score 60 or higher</span></article></section>
  <section class="signal-card glass risk-widget"><div><span class="section-label">Current SARAP signal</span><h2>${high?'Attention needed':'Reputation is stable'}</h2><p>${high?`${high} high-risk mention${high===1?' requires':'s require'} review.`:'No high-risk mentions are waiting for review.'}</p></div>${riskGauge(maxRisk)}</section>
  ${total?`<section class="grid content-split"><article class="card glass"><div class="card-head"><div><h2>Sentiment mix</h2><p>Current saved mentions</p></div><span class="status live">Workspace data</span></div><div class="sentiment-stack"><i class="positive" style="width:${positiveRate}%"></i><i class="negative" style="width:${negativeRate}%"></i><i class="neutral" style="width:${Math.max(0,100-positiveRate-negativeRate)}%"></i></div><div class="legend"><span><i></i>Positive ${positive}</span><span><i class="neg"></i>Negative ${negative}</span><span>Neutral ${total-positive-negative}</span></div></article><article class="card glass"><div class="card-head"><div><h2>AI executive summary</h2><p>Evidence from this workspace</p></div>${icons.radar}</div><div class="summary">SARAP analyzed <strong>${total}</strong> mention${total===1?'':'s'}. <strong>${positiveRate}%</strong> are positive and <strong>${negativeRate}%</strong> are negative. ${high?`<strong>${high}</strong> item${high===1?'':'s'} crossed the alert threshold.`:'No item crossed the high-risk threshold.'}</div><div class="evidence"><div><strong>${positive}</strong><span>positive</span></div><div><strong>${high}</strong><span>high risk</span></div><div><strong>${state.sources.length}</strong><span>connected sources</span></div></div></article></section>`:emptyState('No reputation data yet','Connect a source or add your first mention. Analytics and alerts will appear here automatically.','connect-source','Connect source')}
  ${overviewAnalytics()}
  ${overviewAlerts()}`;
}

function overviewAnalytics(){
  const data=state.analytics||{total:state.mentions.length,positive:state.mentions.filter(x=>x.sentiment==='positive').length,negative:state.mentions.filter(x=>x.sentiment==='negative').length,neutral:state.mentions.filter(x=>x.sentiment==='neutral'||x.sentiment==='mixed').length,top_keywords:[]};
  const total=data.total||0, positivePct=total?Math.round(data.positive/total*100):0, negativePct=total?Math.round(data.negative/total*100):0, recommendationGroups=state.recommendations?.recommendations||{};
  const keywordMax=Math.max(...(data.top_keywords||[]).map(x=>x.count),1);
  return `<section class="overview-section"><div class="overview-section-head"><div><span class="section-label">Analytics</span><h2>Reputation analysis</h2><p>Live breakdown from the latest saved workspace data.</p></div></div><div class="grid content-split"><article class="card glass"><div class="card-head"><div><h2>Sentiment distribution</h2><p>${data.period_start||'Current'} to ${data.period_end||'now'}</p></div></div><div class="sentiment-donut" style="--positive:${positivePct}%;--negative:${positivePct+negativePct}%"><div><strong>${total}</strong><small>mentions</small></div></div><div class="legend"><span><i></i>Positive ${data.positive||0}</span><span><i class="neg"></i>Negative ${data.negative||0}</span><span>Neutral ${data.neutral||0}</span></div></article><article class="card glass"><div class="card-head"><div><h2>Top topics</h2><p>Repeated meaningful themes in the selected period</p></div></div>${(data.top_keywords||[]).map(item=>progressRow(item.word,item.count,keywordMax,'var(--emerald)')).join('')||'<p class="muted">Topics will appear after reviews are collected.</p>'}</article></div><article class="card glass recommendations-card"><div class="card-head"><div><h2>AI business recommendations</h2><p>Repeated evidence from included mentions</p></div></div><p class="summary">${escapeHtml(state.recommendations?.error?'Recommendations temporarily unavailable.':state.recommendations?.loading?'Loading recommendations...':state.recommendations?.summary||'Not enough data yet')}</p><div class="grid recommendation-grid">${[['urgent_fix','Urgent fix'],['improve','Improve'],['keep_doing','Keep doing']].map(([key,title])=>`<article class="recommendation-item"><h3>${title}</h3><ul>${(recommendationGroups[key]||[]).map(item=>`<li>${escapeHtml(item)}</li>`).join('')||'<li class="muted">Not enough data yet</li>'}</ul></article>`).join('')}</div></article></section>`;
}

function overviewAlerts(){
  const ordered=[...state.alerts].sort((a,b)=>(a.status==='Resolved')-(b.status==='Resolved'));
  return `<section class="overview-section"><div class="overview-section-head"><div><span class="section-label">Alerts</span><h2>Active alerts</h2><p>High-signal events with evidence and a clear status.</p></div><button class="btn btn-secondary" data-action="configure-alerts">Alert settings</button></div>${ordered.length?`<div class="alert-list">${ordered.map(a=>`<article class="mention-card glass"><div class="mention-top"><div class="source-icon warning">${icons.alerts}</div><div class="mention-meta"><strong>${escapeHtml(a.severity)} · ${escapeHtml(a.source)}</strong><small>${escapeHtml(a.time)} · ${escapeHtml(a.aspect)}</small></div><span class="risk-pill">Risk ${a.risk}</span></div><p class="mention-text">“${escapeHtml(a.text)}”</p><div class="mention-actions"><span class="status ${a.status==='New'?'high':a.status==='Resolved'?'live':''}">${escapeHtml(a.status)}</span><button class="btn btn-quiet" data-action="alert-status" data-id="${a.id}">${a.status==='Resolved'?'Reopen':'Mark resolved'}</button><button class="btn btn-quiet" data-route="mentions">Open mention →</button></div></article>`).join('')}</div>`:emptyState('No active alerts','SARAP creates an alert when a saved mention crosses your risk threshold.',null,null)}</section>`;
}

function riskGauge(score=0){const label=score>=80?'Critical':score>=60?'High':score>=30?'Medium':'Low';return `<div class="risk-score"><strong>${score}/100</strong><small>${label} signal risk</small></div>`;}
function emptyState(title,text,action,label){return `<section class="empty glass"><div class="empty-icon">${icons.radar}</div><h3>${title}</h3><p>${text}</p>${action?`<button class="btn btn-primary" data-action="${action}">${label}</button>`:''}</section>`;}

function mentionCard(m) {
  return `<article class="mention-card glass" data-mention="${m.id}"><div class="mention-top"><div class="source-icon">${sourceIcon(m.source)}</div><div class="mention-meta"><strong>${escapeHtml(m.source)} · ${escapeHtml(m.author||'Unknown author')}</strong><small>${escapeHtml(m.time)} · ${escapeHtml(m.language||'Unknown language')}</small></div><span class="risk-pill ${m.risk<30?'low':''}">RISK ${m.risk}</span></div><p class="mention-text">${escapeHtml(m.text)}</p><div class="tags">${m.aspects.map(([a,s])=>`<span class="tag ${s}">${escapeHtml(a)} · ${s==='pos'?'Positive':s==='neg'?'Negative':'Neutral'}</span>`).join('')}<span class="tag">${escapeHtml(m.sentiment||'neutral')}</span><span class="tag">${escapeHtml(m.language||'Unknown')}</span></div><div class="mention-actions"><button class="btn btn-quiet" data-action="reply" data-id="${m.id}">Generate reply</button><button class="btn btn-quiet" data-action="review" data-id="${m.id}">${m.reviewed?'Reviewed ✓':'Mark reviewed'}</button><button class="btn btn-quiet" data-action="escalate" data-id="${m.id}">Escalate</button></div></article>`;
}

function exportMentionsCsv(items){
  const header=['Review','Sentiment','Confidence','Summary'];
  const csv=[header,...items.map(item=>[item.text||'',item.sentiment||'',item.confidence!=null?`${Math.round(item.confidence*100)}%`:'—',item.summary||meaningfulMentionSummary(item)])].map(row=>row.map(value=>`"${String(value||'').replaceAll('"','""')}"`).join(',')).join('\n');
  const link=document.createElement('a');link.href=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));link.download='sarap-mentions.csv';link.click();URL.revokeObjectURL(link.href);
}
function fallbackMentionSummary(item){
  const text=String(item.text||'').replace(/\s+/g,' ').trim();
  if(!text)return 'No text available for analysis.';
  const lower=text.toLowerCase();
  const hasCyrillic=/[А-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІі]/.test(text);
  if(hasCyrillic){
    if(/розыгрыш|выигра.{0,20}абонемент/i.test(lower))return 'Пользователь сомневается в честности розыгрыша годового абонемента.';
    if(/позвон|звон.{0,35}продаж|продажниц/i.test(lower))return 'Пользователь жалуется на нежелательный звонок отдела продаж.';
    if(/не\s+(могу|получается).{0,45}(войти|зайти)|не\s+работ.{0,30}прилож/i.test(lower))return 'Пользователь сообщает о проблеме со входом или работой приложения.';
    if(/обман|мошен|подстав/i.test(lower))return 'Пользователь подозревает обман или несправедливое отношение.';
    if(/приложен.{0,45}(спорт|занят)|(спорт|занят).{0,45}приложен/i.test(lower))return 'Пользователь хвалит приложение для занятий спортом.';
    if(/приложен|сервис|разнообраз/i.test(lower)&&item.sentiment==='positive')return 'Пользователь положительно оценивает приложение, сервис и выбор услуг.';
    return item.sentiment==='positive'?'Пользователь положительно оценивает сервис.':item.sentiment==='negative'?'Пользователь сообщает о негативном опыте с сервисом.':item.sentiment==='mixed'?'Пользователь отмечает преимущества и недостатки сервиса.':'Пользователь делится мнением без однозначной оценки.';
  }
  return item.sentiment==='positive'?'The customer is satisfied with the overall experience.':item.sentiment==='negative'?'The customer reports a problem with the experience.':'The customer shares a general opinion without a clear rating.';
}
function meaningfulMentionSummary(item){
  const summary=String(item.summary||'').trim();
  const text=String(item.text||'').replace(/\s+/g,' ').trim();
  const normalized=summary.replace(/\s+/g,' ').toLowerCase();
  const original=text.toLowerCase();
  const copied=!normalized||normalized===original||original.startsWith(normalized.replace(/…$/,''))||/^(положительный отзыв|проблема|смешанный отзыв|нейтральное упоминание|positive feedback|reported issue):/.test(normalized);
  return copied?fallbackMentionSummary(item):summary;
}
function mentionTableRow(item){
  const sentiment=String(item.sentiment||'neutral').toLowerCase();
  const rawDate =
    item.date_raw ||
    item.metadata?.date_raw ||
    item.metadata?.dateRaw;

  const publishedValue=item.publishedAt||item.published_at;

  const published = rawDate
    ? String(rawDate)
    : publishedValue
      ? new Date(publishedValue).toLocaleDateString('en-GB',{day:'2-digit',month:'short',year:'numeric'})
      : 'Unknown';

  return `<tr data-mention-row="${item.id}" data-action="open-mention" data-id="${item.id}" tabindex="0">
    <td class="mention-review-text">${escapeHtml(item.text||'—')}</td>
    <td>${escapeHtml(item.source||'Unknown')}</td>
    <td><span class="tag">${escapeHtml(item.contentType||item.type||item.source_type||'other')}</span></td>
    <td><span class="sentiment-pill ${sentiment}"><i></i>${escapeHtml(sentiment)}</span></td>
    <td>${item.rating==null?'—':`${item.rating}/5`}</td>
    <td><span class="risk-pill ${item.risk<30?'low':''}">${item.risk}</span></td>
    <td class="mention-date">${escapeHtml(published)}</td>
    <td class="review-cell">
      <strong>${escapeHtml(meaningfulMentionSummary(item))}</strong>
      <small>${escapeHtml(item.author||'Unknown author')}${item.includeInAnalysis?'':' · Ignored author'}</small>
    </td>
  </tr>`;
}

const mentionFilters={search:'',source:'all',type:'all',sentiment:'all',analysis:'all',reply:'all',date:'all',sort:'newest'};
function filteredMentions(){
  const cutoff=mentionFilters.date==='all'?null:Date.now()-Number(mentionFilters.date)*86400000;
  const q=(mentionFilters.search||'').trim().toLowerCase();
  const rows=(state.mentions||[]).filter(item=>{
    if(!item)return false;
    const sourceStr=String(item.source||'').toLowerCase();
    const sourceOk=mentionFilters.source==='all'||sourceStr.includes(mentionFilters.source.toLowerCase());

    const typeStr=String(item.contentType||item.type||item.source_type||'').toLowerCase();
    let typeOk=mentionFilters.type==='all';
    if(!typeOk){
      const target=mentionFilters.type.toLowerCase();
      if(target==='review')typeOk=typeStr.includes('review');
      else if(target==='comment')typeOk=typeStr.includes('comment');
      else if(target==='question')typeOk=typeStr.includes('question');
      else if(target==='post')typeOk=typeStr.includes('post')||typeStr.includes('social');
      else if(target==='news')typeOk=typeStr.includes('news');
      else if(target==='other')typeOk=!['review','comment','question','post','news'].some(t=>typeStr.includes(t));
      else typeOk=typeStr.includes(target);
    }

    const sentStr=String(item.sentiment||'').toLowerCase();
    const sentimentOk=mentionFilters.sentiment==='all'||sentStr===mentionFilters.sentiment.toLowerCase();

    const isIncluded=item.includeInAnalysis!==false&&!item.ignored;
    const analysisOk=mentionFilters.analysis==='all'||
      (mentionFilters.analysis==='included'&&isIncluded)||
      ((mentionFilters.analysis==='ignored'||mentionFilters.analysis==='excluded')&&!isIncluded);

    const isAnswered=item.replyStatus==='answered'||item.reviewed===true||item.replied===true;
    const replyOk=mentionFilters.reply==='all'||
      (mentionFilters.reply==='answered'&&isAnswered)||
      (mentionFilters.reply==='unanswered'&&!isAnswered);

    let dateOk=true;
    if(cutoff){
      const itemTime=item.publishedAt||item.collectedAt?new Date(item.publishedAt||item.collectedAt).getTime():0;
      dateOk=!itemTime||itemTime>=cutoff;
    }

    let searchOk=true;
    if(q){
      const summaryText=meaningfulMentionSummary(item).toLowerCase();
      const text=String(item.text||'').toLowerCase();
      const author=String(item.author||'').toLowerCase();
      const src=sourceStr;
      searchOk=text.includes(q)||author.includes(q)||src.includes(q)||summaryText.includes(q);
    }

    return sourceOk&&typeOk&&sentimentOk&&analysisOk&&replyOk&&dateOk&&searchOk;
  });

  return rows.sort((a,b)=>{
    const timeA=new Date(a.publishedAt||a.collectedAt||0).getTime();
    const timeB=new Date(b.publishedAt||b.collectedAt||0).getTime();
    if(mentionFilters.sort==='oldest')return timeA-timeB;
    if(mentionFilters.sort==='risk')return (b.risk??0)-(a.risk??0);
    if(mentionFilters.sort==='risk-asc')return (a.risk??0)-(b.risk??0);
    if(mentionFilters.sort==='rating-high')return (b.rating??-1)-(a.rating??-1);
    if(mentionFilters.sort==='rating-low')return (a.rating??6)-(b.rating??6);
    return timeB-timeA;
  });
}

function mentions(){
  const all=filteredMentions();
  const totalInWorkspace=(state.mentions||[]).length;
  const activeSecondary=[mentionFilters.analysis,mentionFilters.reply,mentionFilters.date].filter(x=>x!=='all').length;

  const actions=`<input class="search" id="mention-search" type="search" placeholder="Search mentions…" value="${escapeHtml(mentionFilters.search||'')}"><div class="popover-anchor" id="filters-popover-anchor"><button class="btn btn-secondary filter-popover-btn ${activeSecondary?'active':''}" type="button" id="mentions-filters-btn" aria-haspopup="dialog" aria-expanded="false">Filters${activeSecondary?` (${activeSecondary})`:''}</button><div class="filters-popover glass hidden" id="mentions-popover" role="dialog" aria-label="Secondary filters"><div class="popover-title">Filters</div><div class="popover-section"><div class="popover-label">Included / ignored</div><button type="button" class="popover-item ${mentionFilters.analysis==='all'?'active':''}" data-mention-filter="analysis" data-value="all"><span class="check">${mentionFilters.analysis==='all'?'✓':''}</span> All</button><button type="button" class="popover-item ${mentionFilters.analysis==='included'?'active':''}" data-mention-filter="analysis" data-value="included"><span class="check">${mentionFilters.analysis==='included'?'✓':''}</span> Included</button><button type="button" class="popover-item ${mentionFilters.analysis==='ignored'?'active':''}" data-mention-filter="analysis" data-value="ignored"><span class="check">${mentionFilters.analysis==='ignored'?'✓':''}</span> Ignored</button></div><div class="popover-section"><div class="popover-label">Reply status</div><button type="button" class="popover-item ${mentionFilters.reply==='all'?'active':''}" data-mention-filter="reply" data-value="all"><span class="check">${mentionFilters.reply==='all'?'✓':''}</span> All</button><button type="button" class="popover-item ${mentionFilters.reply==='answered'?'active':''}" data-mention-filter="reply" data-value="answered"><span class="check">${mentionFilters.reply==='answered'?'✓':''}</span> Answered</button><button type="button" class="popover-item ${mentionFilters.reply==='unanswered'?'active':''}" data-mention-filter="reply" data-value="unanswered"><span class="check">${mentionFilters.reply==='unanswered'?'✓':''}</span> Unanswered</button></div><div class="popover-section"><div class="popover-label">Date</div><button type="button" class="popover-item ${mentionFilters.date==='all'?'active':''}" data-mention-filter="date" data-value="all"><span class="check">${mentionFilters.date==='all'?'✓':''}</span> Any date</button><button type="button" class="popover-item ${mentionFilters.date==='7'?'active':''}" data-mention-filter="date" data-value="7"><span class="check">${mentionFilters.date==='7'?'✓':''}</span> Last 7 days</button><button type="button" class="popover-item ${mentionFilters.date==='30'?'active':''}" data-mention-filter="date" data-value="30"><span class="check">${mentionFilters.date==='30'?'✓':''}</span> Last 30 days</button><button type="button" class="popover-item ${mentionFilters.date==='90'?'active':''}" data-mention-filter="date" data-value="90"><span class="check">${mentionFilters.date==='90'?'✓':''}</span> Last 90 days</button></div><div class="popover-footer"><button type="button" class="popover-clear-btn" data-action="clear-secondary-filters">Clear filters</button></div></div></div><button class="btn btn-secondary" data-action="export-csv" type="button">Export CSV</button><button class="btn btn-primary" data-action="manual-import" type="button">+ Manual import</button>`;

  const headerFilter=(key,label,values)=>{
    const active=mentionFilters[key]!=='all';
    return `
      <div class="th-filter-anchor">
        <button type="button" class="th-filter-btn ${active?'active':''}" data-toggle-header-filter="${key}">
          ${label}${active?' •':''} ▾
        </button>
        <div class="header-filter-menu glass hidden" data-filter-menu="${key}">
          ${values.map(([val,text])=>{
            const isSelected=mentionFilters[key]===val;
            return `<button type="button" class="menu-item ${isSelected?'active':''}" data-mention-filter="${key}" data-value="${val}"><span class="check">${isSelected?'✓':''}</span><span>${text}</span></button>`;
          }).join('')}
        </div>
      </div>`;
  };

  const sortButton=(label,value)=>{
    let arrow='↕';
    let active=false;
    if(value==='rating'){
      if(mentionFilters.sort==='rating-high'){arrow='↓';active=true;}
      else if(mentionFilters.sort==='rating-low'){arrow='↑';active=true;}
    } else if(value==='risk'){
      if(mentionFilters.sort==='risk'){arrow='↓';active=true;}
      else if(mentionFilters.sort==='risk-asc'){arrow='↑';active=true;}
    } else if(value==='newest'||value==='date'){
      if(mentionFilters.sort==='oldest'){arrow='↑';active=true;}
      else{arrow='↓';active=mentionFilters.sort==='newest';}
    }
    return `<button type="button" class="table-sort ${active?'active':''}" data-mention-sort="${value}">${label} ${arrow}</button>`;
  };

  if(totalInWorkspace===0){
    return pageHead('Mentions','Customer feedback and factual AI summaries.',actions)+emptyState('No matching mentions','Change the filters or import customer feedback.',null,null);
  }

  let tableContent='';
  if(all.length>0){
    tableContent=all.map(mentionTableRow).join('');
  } else {
    const hasSearch=Boolean((mentionFilters.search||'').trim());
    const hasFilters=['source','type','sentiment','analysis','reply','date'].some(k=>mentionFilters[k]!=='all');
    const emptyMsg=hasSearch&&hasFilters
      ?'No mentions match your search and filters.'
      :hasSearch
        ?'No mentions match your search.'
        :'No mentions match these filters.';
    const clearSearchBtn=hasSearch?'<button type="button" class="btn btn-quiet" data-action="clear-search">Clear search</button> ':'';
    const clearFiltersBtn=hasFilters?'<button type="button" class="btn btn-quiet" data-action="clear-filters">Clear filters</button>':'';
    tableContent=`<tr><td colspan="7" class="table-empty-cell"><div class="table-empty-box"><p class="table-empty-text">${emptyMsg}</p><div class="table-empty-actions">${clearSearchBtn}${clearFiltersBtn}</div></div></td></tr>`;
  }

  return pageHead('Mentions','Customer feedback and factual AI summaries.',actions)+
    `<div class="table-wrap mentions-table-wrap glass">
      <table class="mentions-table">
        <thead>
          <tr>
            <th>Review</th>
            <th>${headerFilter('source','Source',[['all','Any source'],['2gis','2GIS'],['google','Google'],['yandex','Yandex'],['youtube','YouTube'],['telegram','Telegram'],['instagram','Instagram'],['manual','Manual']])}</th>
            <th>${headerFilter('type','Type',[['all','Any type'],['review','Review'],['comment','Comment'],['question','Question'],['post','Post'],['news','News'],['other','Other']])}</th>
            <th>${headerFilter('sentiment','Sentiment',[['all','Any sentiment'],['positive','Positive'],['neutral','Neutral'],['negative','Negative']])}</th>
            <th>${sortButton('Rating','rating')}</th>
            <th>${sortButton('Risk','risk')}</th>
            <th>${sortButton('Published date','newest')}</th>
            <th>Summary</th>
          </tr>
        </thead>
        <tbody id="mention-list">${tableContent}</tbody>
      </table>
    </div>`;
}

function progressRow(name,count,total,color){const pct=Math.round(count/Math.max(total,1)*100);return `<div class="progress-row"><div><span>${escapeHtml(name)}</span><strong>${count} · ${pct}%</strong></div><i><b style="width:${pct}%;background:${color}"></b></i></div>`;}

function sources() {
  return pageHead('Sources','Connect pages, upload files, or add individual mentions through one ingestion pipeline.','<button class="btn btn-primary" data-action="connect-source">+ Add source</button>')+(state.sources.length?`<section class="grid source-grid">${state.sources.map(s=>{const syncing=syncingSourceIds.has(s.id);const method=s.ingestionMethod||s.method||s.kind;return `<article class="source-card glass"><div class="source-head"><div class="source-icon">${sourceIcon(s.name)}</div><div><strong>${escapeHtml(s.displayName||s.name)}</strong><small>${escapeHtml(s.name)} · ${escapeHtml(method)}</small></div><span class="status ${syncing?'':s.state}">${escapeHtml(syncing?'Syncing':s.status)}</span></div><p>${escapeHtml(s.description)}</p><div class="source-stats"><div><span>Items</span><strong>${s.items==null?'—':s.items}</strong></div><div><span>Last sync/import</span><strong>${escapeHtml(s.last)}</strong></div></div><div class="source-actions">${s.kind!=='Imported'&&s.ingestionMethod!=='manual'?`<button class="btn btn-secondary" data-action="poll-source" data-id="${escapeHtml(s.id)}" ${syncing?'disabled':''}>${syncing?'Syncing...':'Sync'}</button>`:`<button class="btn btn-secondary" data-action="${s.ingestionMethod==='json'?'upload-json':s.ingestionMethod==='csv'?'upload-csv':'add-manual-source'}">Import again</button>`}<button class="btn btn-quiet" data-route="mentions">View data</button><button class="btn btn-quiet" data-action="edit-source" data-id="${escapeHtml(s.id)}">Edit</button><button class="btn btn-quiet" data-action="delete-source" data-id="${escapeHtml(s.id)}">Delete</button></div></article>`}).join('')}</section>`:emptyState('No sources connected','Add an online source, upload CSV/JSON, or enter one mention manually.','connect-source','Add source'));
}

function discover() {
  return pageHead('Reputation Radar','Search social discussions, media, forums and the open web.','<button class="btn btn-primary" data-action="scan-web">Scan web now</button>')+`<section class="radar-strip glass"><div class="radar-stat"><span>Saved discoveries</span><strong>${state.discoveries.length}</strong></div><div class="radar-stat"><span>Brand aliases</span><strong>${state.business.aliases.length}</strong></div><div class="radar-stat"><span>Search region</span><strong>${escapeHtml(state.business.city||'KZ')}</strong></div><button class="btn btn-secondary" data-action="queries">View search queries</button></section><section class="mention-list" id="discover-list">${state.discoveries.map(mentionCard).join('')||emptyState('No web discoveries yet','Run a scan to search configured free web and news sources.',null,null)}</section>`;
}

function settings() {
  const tabs=['Business profile','Alerts','AI','Data','Account'];
  let content='';
  if(currentSettingsTab==='Business profile'||currentSettingsTab==='Business') content=`<h2>Business profile</h2><p class="muted">Business details and names SARAP uses for search.</p><div class="field-grid"><div class="field"><label>Business name</label><input name="name" value="${escapeHtml(state.business.name)}"></div><div class="field"><label>Industry</label><select name="industry">${INDUSTRIES.map(value=>`<option ${state.business.industry===value?'selected':''}>${value}</option>`).join('')}</select></div><div class="field"><label>Country</label><input name="country" value="${escapeHtml(state.business.country)}"></div><div class="field"><label>City</label><input name="city" value="${escapeHtml(state.business.city)}"></div></div><div class="field"><label>Search aliases</label><textarea name="aliases" placeholder="One name per line">${escapeHtml(state.business.aliases.join('\n'))}</textarea><small>SARAP generated these automatically. Add common Russian, Kazakh or abbreviated names if needed.</small></div>`;
  if(currentSettingsTab==='Alerts') content=`<h2>Telegram alerts</h2><p class="muted">Connect once through the SARAP bot. Your Telegram ID is detected automatically.</p><div class="toggle-row"><div><strong>Telegram bot</strong><small>Press Start in Telegram to connect this workspace.</small></div><button type="button" class="btn btn-secondary" data-action="connect-telegram">Connect Telegram ↗</button></div><div class="field" style="margin-top:15px"><label>Alert threshold</label><select name="threshold"><option ${state.settings.threshold==='Critical only'?'selected':''}>Critical only</option><option ${state.settings.threshold==='High + Critical'?'selected':''}>High + Critical</option><option ${state.settings.threshold==='All negative'?'selected':''}>All negative</option></select></div>`;
  if(currentSettingsTab==='AI') content=`<h2>AI</h2><p class="muted">Business tone, custom aspects and the two-stage model cascade.</p><div class="provider-grid"><div class="provider-card"><span class="status live">Fast pass</span><strong>Groq</strong><small>Every new mention · structured sentiment, language and aspects</small></div><div class="provider-arrow">→</div><div class="provider-card"><span class="status high">Strong pass</span><strong>Gemini</strong><small>Mixed language, low confidence and high-risk content only</small></div></div><div class="field"><label>Reply tone</label><input name="tone" value="${escapeHtml(state.settings.tone)}"></div><div class="field"><label>Custom aspects</label><textarea name="customAspects" placeholder="Parking, menu availability, loyalty program…">${escapeHtml(state.settings.customAspects)}</textarea></div><div class="toggle-row"><div><strong>Cheap-first cascade</strong><small>Groq handles the fast pass; Gemini reviews ambiguous or critical cases.</small></div><span class="status live">Configured on server</span></div><p class="form-note">API keys stay on the server. They are never entered or stored in this browser.</p>`;
  if(currentSettingsTab==='Data') content=`<h2>Data</h2><p class="muted">Export and retention controls.</p><div class="field"><label>Retention</label><select name="retention"><option>6 months</option><option selected>12 months</option><option>24 months</option></select></div><div class="form-actions"><button type="button" class="btn btn-secondary" data-action="export">Export demo JSON</button><span class="muted" style="font-size:11px">External content is sanitized before display.</span></div>`;
  if(currentSettingsTab==='Account') content=`<h2>Account</h2><p class="muted">Owner name and current workspace.</p><div class="field"><label>Owner name</label><input name="fullName" value="${escapeHtml(state.session?.name||'')}"></div><div class="toggle-row"><div><strong>${escapeHtml(state.session?.email||'No email')}</strong><small>Verified account email</small></div><span class="status ${state.session?.verified||state.session?.demo?'live':'high'}">${state.session?.demo?'Demo':state.session?.verified?'Verified':'Unverified'}</span></div><div class="toggle-row"><div><strong>${escapeHtml(state.business.name)}</strong><small>Current workspace</small></div><span class="status live">Active</span></div><div class="form-actions" style="margin-top:20px"><button type="button" class="btn btn-danger" data-action="logout">Log out</button><button class="btn btn-primary" type="submit">Save name</button></div>`;
  return pageHead('Settings','Business identity, alerting, AI and data controls.')+`<section class="grid settings-grid"><nav class="settings-nav glass">${tabs.map(t=>`<button class="${currentSettingsTab===t?'active':''}" data-settings-tab="${t}">${t}</button>`).join('')}</nav><form class="settings-panel glass" data-form="settings">${content}${!['Account','Data'].includes(currentSettingsTab)?'<div class="form-actions"><span></span><button class="btn btn-primary" type="submit">Save changes</button></div>':''}</form></section>`;
}
function toggle(title, subtitle, key) { return `<div class="toggle-row"><div><strong>${title}</strong><small>${subtitle}</small></div><button type="button" class="switch ${state.settings[key]?'on':''}" data-toggle="${key}" aria-label="Toggle ${title}"></button></div>`; }

function admin() {
  if(state.session?.role!=='admin')return emptyState('Administrator access required','This area is available only to a SARAP platform administrator.',null,null);
  if(!state.admin)return pageHead('Platform administration','Server-protected operational controls.')+'<div class="skeleton"></div>';
  const a=state.admin,s=a.summary||{},defaultRisk=a.settings?.find(x=>x.key==='default_risk_threshold')?.value?.value??60,localFallback=a.settings?.find(x=>x.key==='local_analysis_fallback')?.value?.enabled!==false;
  return pageHead('Platform administration','Workspaces, connectors, AI usage, global defaults and audit history.')+`<section class="grid metric-grid"><article class="metric-card glass"><span class="metric-label">Workspaces</span><div class="metric-value">${s.workspaces||0}</div></article><article class="metric-card glass"><span class="metric-label">Active sources</span><div class="metric-value good">${s.active_sources||0}</div></article><article class="metric-card glass"><span class="metric-label">Connector errors</span><div class="metric-value ${s.source_errors?'danger':'good'}">${s.source_errors||0}</div></article><article class="metric-card glass"><span class="metric-label">AI requests</span><div class="metric-value">${s.ai_requests||0}</div><span class="metric-change">$${Number(s.estimated_cost_usd||0).toFixed(4)} estimated</span></article></section>
  <section class="card glass admin-section"><div class="card-head"><div><h2>Workspaces</h2><p>Read-only support overview</p></div></div><div class="table-wrap"><table><thead><tr><th>Business</th><th>Plan</th><th>Sources</th><th>City</th><th>Onboarding</th><th>Last activity</th><th></th></tr></thead><tbody>${(a.businesses||[]).map(b=>`<tr><td><strong>${escapeHtml(b.name)}</strong></td><td>${escapeHtml(b.plan||'starter')}</td><td>${(a.sources||[]).filter(x=>x.business_id===b.id).length}</td><td>${escapeHtml(b.city||'—')}</td><td><span class="status ${b.onboarding_completed?'live':''}">${b.onboarding_completed?'Complete':'Pending'}</span></td><td>${b.last_activity_at?new Date(b.last_activity_at).toLocaleString():'—'}</td><td><button class="btn btn-quiet" data-action="support-view" data-id="${b.id}">Read-only view</button></td></tr>`).join('')||'<tr><td colspan="7">No workspaces</td></tr>'}</tbody></table></div></section>
  <section class="grid content-split"><article class="card glass admin-section"><div class="card-head"><div><h2>Connector health</h2><p>Status and latest errors</p></div></div>${(a.sources||[]).map(x=>`<div class="health-row"><span class="status ${x.error_message?'high':'live'}">${x.error_message?'Error':'Healthy'}</span><div><strong>${escapeHtml(x.source)}</strong><small>${escapeHtml(x.error_message||x.active_collection_method||x.collection_mode)}</small></div></div>`).join('')||'<p class="muted">No connectors configured.</p>'}</article><article class="card glass admin-section"><div class="card-head"><div><h2>Feature flags</h2><p>Global product switches</p></div></div>${(a.flags||[]).map(f=>`<div class="toggle-row"><div><strong>${escapeHtml(f.key.replaceAll('_',' '))}</strong><small>${escapeHtml(f.description||'')}</small></div><button class="switch ${f.enabled?'on':''}" data-action="admin-flag" data-key="${escapeHtml(f.key)}" data-enabled="${f.enabled}" aria-label="Toggle ${escapeHtml(f.key)}"></button></div>`).join('')}</article></section>
  <section class="grid content-split admin-section"><article class="card glass"><div class="card-head"><div><h2>AI usage & cost</h2><p>Recorded provider calls and free-tier guardrail</p></div></div>${['groq','gemini','local'].map(provider=>{const rows=(a.usage||[]).filter(x=>(x.provider||'').toLowerCase().includes(provider));return progressRow(provider,rows.length,Math.max((a.usage||[]).length,1),provider==='gemini'?'var(--amber)':'var(--emerald)')}).join('')}<div class="toggle-row"><div><strong>Local analysis fallback</strong><small>Keep analysis available when provider limits are exhausted.</small></div><button class="switch ${localFallback?'on':''}" data-action="admin-setting" data-key="local_analysis_fallback" data-value='${JSON.stringify({enabled:!localFallback})}'></button></div></article><article class="card glass"><div class="card-head"><div><h2>Risk defaults</h2><p>Applied to newly created workspaces</p></div></div><div class="field"><label>Default alert threshold (0–100)</label><input id="admin-risk-default" type="number" min="0" max="100" value="${defaultRisk}"></div><button class="btn btn-primary" data-action="save-risk-default">Save default</button></article></section>
  <section class="card glass admin-section"><div class="card-head"><div><h2>Audit log</h2><p>Latest protected administrative actions</p></div></div><div class="table-wrap"><table><thead><tr><th>Time</th><th>Action</th><th>Target</th></tr></thead><tbody>${(a.audit||[]).map(x=>`<tr><td>${new Date(x.created_at).toLocaleString()}</td><td>${escapeHtml(x.action)}</td><td>${escapeHtml(x.target_type||'system')} ${escapeHtml(x.target_id||'')}</td></tr>`).join('')||'<tr><td colspan="3">No admin actions yet</td></tr>'}</tbody></table></div></section>`;
}

function render() {
  if(!authReady&&isSupabaseConfigured()){app.innerHTML=authLoading();return;}
  if(state.route==='landing') app.innerHTML=landing();
  else if(state.route==='login'||state.route==='register') app.innerHTML=auth(state.route);
  else if(state.route==='verify-email') app.innerHTML=verifyEmail();
  else if(state.route==='forgot-password') app.innerHTML=forgotPassword();
  else if(state.route==='reset-password') app.innerHTML=resetPassword();
  else if(state.route==='onboarding') app.innerHTML=onboarding();
  else {
    if(!state.session){state.route='login';saveState();app.innerHTML=auth('login');return;}
    if(['analytics','alerts'].includes(state.route)){state.route='overview';saveState();}
    const views={overview,mentions,sources,discover,settings,admin};
    app.innerHTML=appShell((views[state.route]||overview)());
  }
}

function modal(html) { document.body.insertAdjacentHTML('beforeend',`<div class="modal-backdrop" data-modal><section class="modal glass">${html}</section></div>`); }
function closeModal() { document.querySelector('[data-modal]')?.remove(); }
function fieldData(form) { return Object.fromEntries(new FormData(form).entries()); }
function apiPath(path) { return `${(window.SARAP_CONFIG?.API_URL||'').replace(/\/$/,'')}${path}`; }

async function createBackendSource(data) {
  if(location.protocol==='file:') return null;
  const connectionType=data.method==='api'?'official':data.method==='import'?'imported':'monitored';
  const body={business_id:state.business.id,source:data.name,connection_type:connectionType,collection_mode:data.method==='import'?'auto':data.method};
  if(data.url) body.source_url=data.url;
  let response;
  try {
    response=await fetch(apiPath('/api/sources'),{method:'POST',headers:{'Content-Type':'application/json',...(await apiAuthHeaders())},body:JSON.stringify(body)});
  } catch {
    throw new Error('SARAP API is unavailable. Reload the page and try again.');
  }
  if(!response.ok) throw new Error((await response.json()).detail||'Could not create source');
  return response.json();
}

async function pollBackendSource(source) {
  if(!source.backendId){
    const method=source.kind==='Official'?'api':source.kind==='Imported'?'import':source.method==='URL scraper'?'scraper':'auto';
    const backend=await createBackendSource({name:source.name,method,url:source.sourceUrl||''});
    source.backendId=backend?.id||null;
    if(!source.backendId)throw new Error('Run SARAP through FastAPI to test this source');
  }
  const response=await fetch(apiPath(`/api/sources/${source.backendId}/poll`),{method:'POST',headers:await apiAuthHeaders()});
  const body=await response.json();
  if(!response.ok) throw new Error(body.message||body.detail||'Collection failed');
  const collected=Number(body.collected||0),added=Number(body.new||0),duplicates=Number(body.duplicates||0);
  source.items=Number(source.items||0)+added;
  source.last='Just now';
  source.method=body.provider||source.method;
  source.status=body.provider==='discovery'?'Discovery monitoring':added?'Active':'No new items';
  source.state=body.status==='success'?'live':'';
  if(!state.session?.demo){
    try{
      const workspace=await loadWorkspace();
      applyWorkspace(workspace);
      await loadProductData();
      await loadAnalyticsData(true);
    }catch(error){console.warn('Collection succeeded, but workspace refresh failed:',error);}
  }
  saveState(); render();
  if(source.name?.toLowerCase().includes('2gis')){
    const total=Number(body.total_stored_after_sync||source.items||0);
    const suffix=body.mode==='backfill'&&body.historical_complete===false?' More history may remain.':'';
    toast('2GIS sync complete',`${added} new review${added===1?'':'s'}, ${duplicates} duplicate${duplicates===1?'':'s'} skipped. ${total} total stored.${suffix}`);
  }else{
    const provider=body.provider?` via ${body.provider}`:'';
    toast('Collection finished',added?`${added} new item(s) saved${provider}. ${duplicates} duplicate(s) skipped.`:(body.message||'No new reviews'));
  }
}

function mapStoredSource(source, previous=null) {
  const labels={auto:'Automatic',api:'Connected account',scraper:'Public page'};
  const collectorLabels={external_worker:'External worker',youtube_api:'YouTube API',discovery:'Discovery',playwright:'Browser',scrapfly:'Scrapfly',sociavault:'SociaVault',socialcrawl:'SocialCrawl',apify:'Apify'};
  const kind={official:'Official',monitored:'Monitored',provider:'Provider',imported:'Imported'}[source.connection_type]||'Monitored';
  const statuses={active:'Active',no_new_items:'No new items',discovery_monitoring:'Discovery monitoring',collector_unavailable:'Collector unavailable',ready:'Active',oauth_required:'Setup required',setup_required:'Setup required',syncing:'Syncing',error:'Error'};
  const status=statuses[source.status]||source.status||'Active';
  const state=(source.error_message||['error','collector_unavailable'].includes(source.status))?'high':['active','ready','no_new_items','discovery_monitoring'].includes(source.status)?'live':'';
  const isTwoGis=String(source.source||'').toLowerCase().includes('2gis');
  const description=(source.error_message?friendlyError(source.error_message):'')||source.source_url||(isTwoGis?'Add the 2GIS business page URL to test collection.':status==='OAuth required'?'Connect the official account in source settings':'Choose the business page to finish setup');
  const activeCollector=collectorLabels[String(source.active_collection_method||'').toLowerCase()];
  const ingestionMethod=source.active_collection_method||source.ingestion_method||source.collection_mode;
  const method=kind==='Imported'?String(ingestionMethod||'Import').toUpperCase():activeCollector?`Collected by ${activeCollector}`:labels[source.collection_mode]||'Auto';
  return {id:source.id,dbId:source.id,backendId:source.id,name:source.source,displayName:source.display_name||source.source,kind,ingestionMethod,collectionMode:source.collection_mode,method,status,state,description,sourceUrl:source.source_url||'',last:source.last_checked_at?new Date(source.last_checked_at).toLocaleString():'—',next:source.next_check_at?new Date(source.next_check_at).toLocaleString():'—',items:Number.isFinite(source.item_count)?source.item_count:(previous?.items??null),errors:source.error_message?1:0};
}
function uniqueSources(items) {
  const seen=new Set();
  return items.filter(source=>{
    const key=[source.name,source.collectionMode||source.method,source.sourceUrl||''].join('|').toLowerCase();
    if(seen.has(key))return false;
    seen.add(key);
    return true;
  });
}

function sourceUrlProblem(sourceName,url){
  if(!url)return '';
  try{
    const parsed=new URL(url);
    if(String(sourceName).toLowerCase().includes('2gis')){
      if(!(parsed.hostname.startsWith('2gis.')||parsed.hostname.includes('.2gis.')))return 'Use a link from the 2GIS business card.';
      if(!/\/firm\/\d+(?:\/|$)/.test(parsed.pathname))return 'Open the exact company card and copy a link containing /firm/ followed by its numeric company ID.';
    }
    if(sourceName==='Instagram'){
      if(!['instagram.com','www.instagram.com'].includes(parsed.hostname.toLowerCase()))return 'Use a link from instagram.com.';
      const path=parsed.pathname.replace(/^\/+|\/+$/g,'');
      const isPost=/^(?:p|reel)\/[^/]+$/.test(path);
      const isProfile=/^[A-Za-z0-9._]+$/.test(path)&&!['about','accounts','developer','direct','directory','emails','explore','legal','oauth','privacy','reels','stories','web'].includes(path.toLowerCase());
      if(!isPost&&!isProfile)return 'Use an Instagram profile, post or Reel link.';
    }
    if(sourceName==='LinkedIn'&&!/(^|\.)linkedin\.com$/i.test(parsed.hostname))return 'Use a company or page link from linkedin.com.';
  }catch{return 'Paste a valid source URL.';}
  return '';
}

function applyWorkspace(payload) {
  if(payload?.profile) state.session={...state.session,name:payload.profile.full_name||state.session?.name||'SARAP User',email:payload.profile.email||state.session?.email,role:payload.profile.role||'user',workspaceRole:payload.role||null};
  if(!payload?.business)return false;
  const business=payload.business;
  state.business={...state.business,id:business.id,name:business.name,website:business.website||'',industry:business.industry||'',country:business.country||'Kazakhstan',city:business.city||'',locations:business.location_count||1,aliases:payload.aliases||[]};
  if(Array.isArray(payload.sources)){const previous=new Map(state.sources.map(source=>[source.id,source]));state.sources=uniqueSources(payload.sources.map(source=>mapStoredSource(source,previous.get(source.id))));}
  return Boolean(business.onboarding_completed);
}

function mapProcessed(row){const m=row.mention||{},a=row.analysis||{},r=row.risk||{};const item={id:m.id,source:m.source,type:m.source_type||'review',contentType:m.content_type||'review',includeInAnalysis:m.include_in_analysis!==false,author:m.author_name||'Unknown author',publishedAt:m.published_at||null,collectedAt:m.collected_at||null,time:m.published_at?new Date(m.published_at).toLocaleString():'Publication date unknown',url:m.external_url||'',externalId:m.external_id||'',text:m.text||'',summary:a.summary||'',confidence:Number(a.confidence||0),rating:m.rating,language:a.language||m.language||'Unknown',sentiment:a.sentiment||'neutral',risk:r.score||0,aspects:(a.aspects||[]).map(x=>[x.aspect,x.sentiment==='positive'?'pos':x.sentiment==='negative'?'neg':'neutral']),reviewed:Boolean(m.reviewed),replyDraft:m.reply_draft||'',replyGeneratedAt:m.reply_generated_at||null,replyStatus:m.reply_status||'none'};if(!item.summary.trim())item.summary=fallbackMentionSummary(item);return item;}
async function loadProductData(){
  if(state.session?.demo||!state.business?.id)return;
  const headers=await apiAuthHeaders();
  const mentionResponse=await fetch(apiPath(`/api/mentions?business_id=${encodeURIComponent(state.business.id)}`),{headers});
  const mentionText=await mentionResponse.text();
  let mentionPayload;
  try{mentionPayload=mentionText?JSON.parse(mentionText):null;}catch{throw new Error(mentionText.slice(0,240)||'Could not load mentions');}
  if(!mentionResponse.ok)throw new Error(mentionPayload?.detail||'Could not load mentions');
  state.mentions=(mentionPayload||[]).map(mapProcessed);
  state.sources.forEach(source=>{source.items=state.mentions.filter(item=>item.source.toLowerCase()===source.name.toLowerCase()||(source.name==='Manual import'&&item.source.toLowerCase()==='manual')).length;});
  const [alerts,discoveries,settings]=await Promise.all([
    db(`/alerts?business_id=eq.${state.business.id}&select=*&order=created_at.desc`),
    db(`/web_discoveries?business_id=eq.${state.business.id}&select=*&order=discovered_at.desc`),
    db(`/workspace_settings?business_id=eq.${state.business.id}&select=*&limit=1`),
  ]);
  state.alerts=(alerts||[]).map(x=>{const m=state.mentions.find(y=>y.id===x.mention_id)||{};return {id:x.id,severity:x.severity,source:m.source||'Unknown',time:new Date(x.created_at).toLocaleString(),aspect:m.aspects?.find(y=>y[1]==='neg')?.[0]||'Overall',risk:m.risk||0,text:m.text||'Mention removed',status:x.status==='resolved'?'Resolved':x.status==='viewed'?'Viewed':'New'};});
  state.discoveries=(discoveries||[]).map(x=>({id:x.id,source:new URL(x.url).hostname,type:'web',author:'Web discovery',time:new Date(x.discovered_at).toLocaleString(),text:x.snippet||x.title||x.url,sentiment:'neutral',language:'Unknown',risk:0,aspects:[['Relevance','neutral']],reviewed:false,url:x.url}));
  if(settings?.[0])Object.assign(state.settings,{telegram:settings[0].telegram_alerts,email:settings[0].email_alerts,tone:settings[0].reply_tone,customAspects:settings[0].custom_aspects});
  saveState();
}
async function loadAnalyticsData(refresh=false){
  if(state.session?.demo||!state.business?.id)return;
  state.recommendations={...(state.recommendations||{}),loading:true,error:false};if(state.route==='overview')render();
  try{
    const headers=await apiAuthHeaders();
    const analyticsResponse=await fetch(apiPath(`/api/analytics?business_id=${encodeURIComponent(state.business.id)}&days=30`),{headers});
    if(!analyticsResponse.ok)throw new Error('Could not load analytics');
    state.analytics=await analyticsResponse.json();
    const recommendationResponse=await fetch(apiPath(`/api/recommendations?business_id=${encodeURIComponent(state.business.id)}&days=30${refresh?'&refresh=true':''}`),{headers});
    if(!recommendationResponse.ok)throw new Error('Recommendations temporarily unavailable');
    state.recommendations={...(await recommendationResponse.json()),loading:false,error:false};saveState();if(state.route==='overview')render();
  }catch(error){state.recommendations={...(state.recommendations||{}),loading:false,error:true};saveState();if(state.route==='overview')render();toast('Recommendations unavailable','Please try again later.');}
}
async function loadAdminData(){if(state.session?.role!=='admin')return;try{const response=await fetch(apiPath('/api/admin/overview'),{headers:await apiAuthHeaders()});if(!response.ok)throw new Error((await response.json()).detail||'Could not load admin data');state.admin=await response.json();saveState();render();}catch(error){toast('Admin data unavailable',error.message);}}

function clearWorkspaceForUser(userId) {
  if(state.accountUserId===userId)return;
  state.business=structuredClone(emptyBusiness);state.mentions=[];state.discoveries=[];state.alerts=[];state.sources=[];state.admin=null;state.accountUserId=userId;
}

function applyAuthSession(authSession, callback=null) {
  const user=authSession?.user||{};
  clearWorkspaceForUser(user.id||null);
  state.session={name:user.user_metadata?.full_name||'SARAP User',email:user.email||state.pendingEmail,demo:false,verified:Boolean(user.email_confirmed_at||callback)};
  if(user.user_metadata?.business_name)state.business.name=user.user_metadata.business_name;
  return user;
}

async function loadWorkspaceAfterAuth() {
  const workspace=await loadWorkspace();
  const complete=applyWorkspace(workspace);
  state.route=state.session?.role==='admin'&&location.pathname==='/admin'?'admin':complete?'overview':'onboarding';
  if(complete)setTimeout(()=>loadProductData().then(()=>{if(state.route==='overview')render();}).catch(error=>toast('Dashboard data unavailable',error.message)),0);
  if(state.route==='admin')setTimeout(loadAdminData,0);
  if(state.route==='overview')setTimeout(loadAnalyticsData,0);
  return complete;
}

function setupAuthListener() {
  if(authSubscription||!isSupabaseConfigured())return;
  const { data }=onAuthStateChange((event, session)=>{
    if(!authReady)return;
    if(event==='SIGNED_OUT'){
      state.session=null;state.pendingEmail='';state.route='landing';saveState();render();return;
    }
    if(session&&['INITIAL_SESSION','SIGNED_IN','TOKEN_REFRESHED'].includes(event)){
      applyAuthSession(session);
      saveState();
    }
  });
  authSubscription=data?.subscription||data||true;
}

async function initializeAuth() {
  if(!isSupabaseConfigured()){if(!state.session?.demo)state.session=null;authReady=true;saveState();return;}
  setupAuthListener();
  try {
    const callback=consumeAuthCallback();
    const authSession=await restoreSession();
    if(!authSession){state.session=null;authReady=true;saveState();return;}
    applyAuthSession(authSession, callback);
    if(callback?.type==='recovery'){state.route='reset-password';authReady=true;saveState();return;}
    try{
      await loadWorkspaceAfterAuth();
    }catch(error){
      state.route=state.route==='admin'?'admin':'overview';
      setTimeout(()=>toast('Workspace unavailable',friendlyError(error)),0);
    }
  } catch(error) {
    state.session=null;state.route='login';setTimeout(()=>toast('Authentication error',error.message),0);
  }
  authReady=true;saveState();
}

async function authSubmit(form) {
  const data=fieldData(form);
  if(!isSupabaseConfigured()){toast('Account setup is incomplete','Supabase is not connected to this deployment yet.');return;}
  if(state.route==='register'&&data.password!==data.passwordConfirm){toast('Passwords do not match','Enter the same password twice.');return;}
  form.classList.add('loading');
  try {
    if(state.route==='register'){
      const result=await signUp({email:data.email,password:data.password,fullName:data.name,businessName:data.business});
      state.pendingEmail=data.email;state.business.name=data.business;state.onboardingStep=1;
      if(result.session){applyAuthSession(result.session);state.session.name=data.name;state.session.verified=true;state.route='onboarding';}
      else state.route='verify-email';
    }else{
      const session=await signIn({email:data.email,password:data.password});
      if(!session)throw new Error('Could not start a saved session. Please try again.');
      applyAuthSession(session);
      try{await loadWorkspaceAfterAuth();}catch(error){state.route='overview';setTimeout(()=>toast('Workspace unavailable',friendlyError(error)),0);}
      saveState();render();
    }
    saveState();render();
  }catch(error){
    form.classList.remove('loading');
    const message=String(error.message||'');
    const detail=/email not confirmed/i.test(message)
      ? 'Open the confirmation link sent to your email, then try again.'
      : /rate limit|too many requests/i.test(message)
        ? 'Confirmation email limit reached. Wait a few minutes and try again.'
      : /invalid login credentials/i.test(message)
        ? 'Check your email and password, or use Forgot password.'
        : message;
    toast(state.route==='register'?'Could not create account':'Could not sign in',detail);
  }
}
async function onboardingSubmit(form) {
  const data=fieldData(form);
  if(state.onboardingStep===1){
    const industry=data.industry==='Other'&&data.customIndustry?.trim()?data.customIndustry.trim():'Other'===data.industry?'Other':data.industry;
    Object.assign(state.business,{name:data.name.trim(),industry,country:data.country.trim(),city:data.city.trim(),locations:1,website:'',handle:'',aliases:deterministicAliases(data.name)});
    state.onboardingStep=2;
  }else if(state.onboardingStep===2){
    state.business.aliases=deterministicAliases(state.business.name);
    if(!state.session?.demo){
      form.classList.add('loading');
      try{state.business.id=await completeWorkspace(state.business);}catch(error){form.classList.remove('loading');toast('Could not create workspace',friendlyError(error));return;}
    }
    state.onboardingStep=3;
  }else{
    state.route='overview';toast('Workspace ready','You can add sources whenever you are ready.');
  }
  saveState();render();
}

function mentionDetailModal(mention){
  const published=mention.publishedAt?new Date(mention.publishedAt).toLocaleString():'Unknown';
  const collected=mention.collectedAt?new Date(mention.collectedAt).toLocaleString():'Unknown';
  const sourcePage=state.sources.find(source=>source.name.toLowerCase().includes(String(mention.source).toLowerCase()))?.sourceUrl||'';
  const isReviewsPage=/\/tab\/reviews(?:[/?#]|$)/i.test(mention.url||'');
  const link=mention.url?`<a href="${escapeHtml(mention.url)}" target="_blank" rel="noopener">${isReviewsPage?'Open reviews page':'Open original review'} ↗</a>`:sourcePage?`<a href="${escapeHtml(sourcePage)}" target="_blank" rel="noopener">Open reviews page ↗</a>`:'';
  modal(`<div class="modal-head"><div><h2>${escapeHtml(mention.contentType||'Mention')}</h2><p>${escapeHtml(mention.source)} · Published ${escapeHtml(published)}</p></div><button class="close" data-action="close-modal">×</button></div><div class="summary"><strong>AI summary</strong><br>${escapeHtml(meaningfulMentionSummary(mention))}</div><div class="mention-detail-text">${escapeHtml(mention.text)}</div><div class="detail-grid"><div><span>Author</span><strong>${escapeHtml(mention.author)}</strong></div><div><span>Status</span><strong>${mention.includeInAnalysis?'Included':'Ignored author'}</strong></div><div><span>Collected</span><strong>${escapeHtml(collected)}</strong></div><div><span>Rating</span><strong>${mention.rating??'—'}</strong></div><div><span>Sentiment</span><strong>${escapeHtml(mention.sentiment)}</strong></div><div><span>Risk</span><strong>${mention.risk}</strong></div></div>${link?`<p class="form-note">${link}</p>`:''}<div class="tags">${mention.aspects.map(([a,t])=>`<span class="tag ${t}">${escapeHtml(a)}</span>`).join('')}</div>${mention.replyDraft?`<div class="summary"><strong>Reply draft</strong><br>${escapeHtml(mention.replyDraft)}</div>`:''}<div class="form-actions"><button type="button" class="btn btn-secondary" data-action="copy-review" data-id="${mention.id}">Copy review text</button><button type="button" class="btn btn-secondary" data-action="reply" data-id="${mention.id}">Generate reply</button><button type="button" class="btn ${mention.includeInAnalysis?'btn-danger':'btn-primary'}" data-action="ignore-author" data-id="${mention.id}" data-ignored="${mention.includeInAnalysis}">${mention.includeInAnalysis?'Ignore this author':'Restore'}</button></div>`);
}
async function smartReply(id,regenerate=false) {
  let mention=state.mentions.find(m=>m.id===id);if(!mention)return;
  if(!state.session?.demo){
    const response=await fetch(apiPath(`/api/mentions/${encodeURIComponent(id)}/reply`),{method:'POST',headers:{'Content-Type':'application/json',...(await apiAuthHeaders())},body:JSON.stringify({regenerate})});
    const body=await response.json();if(!response.ok)throw new Error(body.detail||'Reply is temporarily unavailable');
    mention=mapProcessed(body);state.mentions=state.mentions.map(item=>item.id===id?mention:item);saveState();
  }else if(!mention.replyDraft||regenerate){mention.replyDraft=mention.sentiment==='positive'?'Спасибо за тёплый отзыв! Рады, что вам понравился опыт.':'Спасибо за обратную связь. Нам жаль, что ваш опыт оказался неудачным. Мы передадим описанную проблему команде для проверки.';mention.replyStatus='draft';}
  closeModal();modal(`<div class="modal-head"><div><h2>Reply draft</h2><p>Edit before copying. SARAP never publishes automatically.</p></div><button class="close" data-action="close-modal">×</button></div><form data-form="reply-draft" data-mention-id="${id}"><div class="field"><label>Editable reply</label><textarea name="replyDraft" class="reply-editor">${escapeHtml(mention.replyDraft)}</textarea></div><div class="form-actions"><button type="button" class="btn btn-secondary" data-action="regenerate-reply" data-id="${id}">Regenerate</button><button type="button" class="btn btn-secondary" data-action="copy-reply" data-text="${escapeHtml(mention.replyDraft)}">Copy</button><button type="button" class="btn btn-secondary" data-action="mark-answered" data-id="${id}">Mark answered</button><button class="btn btn-primary">Save draft</button></div></form>`);
}

function editSourceModal(source){
  modal(`<div class="modal-head"><div><h2>Edit ${escapeHtml(source.name)}</h2><p>Update the page or connect an official API.</p></div><button class="close" data-action="close-modal">×</button></div><form data-form="source-edit" data-source-id="${escapeHtml(source.id)}"><div class="field"><label>Page URL</label><input name="url" type="url" value="${escapeHtml(source.sourceUrl||'')}" placeholder="${escapeHtml(sourcePlaceholder(source.name))}"><small>${escapeHtml(sourceHint(source.name))}</small></div><div class="field"><label>Collection strategy</label><select name="method"><option value="auto" ${source.collectionMode==='auto'?'selected':''}>API + URL fallback</option><option value="scraper" ${source.collectionMode==='scraper'?'selected':''}>Public URL only</option><option value="api" ${source.collectionMode==='api'?'selected':''}>Official API only</option></select></div>${apiCredentialFields(source.name)}<div class="form-actions"><button type="button" class="btn btn-secondary" data-action="close-modal">Cancel</button><button class="btn btn-primary">Save source</button></div></form>`);
}

function addSourceModal() {
  modal(`<div class="modal-head"><div><h2>Add source</h2><p>Connect the page you want SARAP to monitor.</p></div><button class="close" data-action="close-modal">×</button></div><form data-form="source"><input type="hidden" name="method" value="auto"><div class="field"><label>Source</label><select name="name" data-source-select><option>2GIS</option><option>Yandex Maps</option><option>Google Business</option><option>Instagram</option><option>Threads</option><option>LinkedIn</option><option>YouTube</option><option>Telegram</option><option>Website / RSS</option><option>Manual import</option></select></div><div class="field"><label>Business or handle <span class="muted">(optional)</span></label><input name="query" value="${escapeHtml(state.business.name)}" placeholder="Business name or @handle"></div><div class="field"><label>Page URL</label><input name="url" type="url" required placeholder="${escapeHtml(sourcePlaceholder('2GIS'))}"><small data-source-hint>${escapeHtml(sourceHint('2GIS'))}</small></div><div class="form-actions"><button type="button" class="btn btn-secondary" data-action="close-modal">Cancel</button><button class="btn btn-primary">Add source</button></div></form>`);
}

function fileImportModal(kind){
  pendingSourceImport=null;
  const accept=kind==='csv'?'.csv,text/csv':'.json,application/json';
  modal(`<div class="modal-head"><div><h2>Upload ${kind.toUpperCase()}</h2><p>Preview the file, map fields, then import through SARAP analysis.</p></div><button class="close" data-action="close-modal">×</button></div><form data-form="source-import" data-kind="${kind}"><div class="field-grid"><div class="field"><label>What platform is this data from?</label><select name="platform">${importPlatforms.map(value=>`<option>${value}</option>`).join('')}</select></div><div class="field"><label>Display name</label><input name="displayName" placeholder="${kind.toUpperCase()} Import — reviews"></div></div><label class="toggle-inline"><input type="checkbox" name="useSourceFromFile"> Use source from file when mapped</label><div class="field"><label>${kind.toUpperCase()} file</label><input name="file" type="file" accept="${accept}" required data-import-file></div><div data-import-preview class="import-preview-empty">Choose a file to inspect columns and preview rows.</div><div class="form-actions"><button type="button" class="btn btn-secondary" data-action="connect-source">Back</button><button class="btn btn-primary">Import</button></div></form>`);
}

function manualSourceModal(){
  modal(`<div class="modal-head"><div><h2>Add manually</h2><p>Add one mention through the same SARAP pipeline.</p></div><button class="close" data-action="close-modal">×</button></div><form data-form="source-manual"><div class="field-grid"><div class="field"><label>Platform</label><select name="platform">${importPlatforms.map(value=>`<option>${value}</option>`).join('')}</select></div><div class="field"><label>Type</label><select name="contentType"><option value="review">review</option><option value="comment">comment</option><option value="video_comment">video_comment</option><option value="post">post</option><option value="news_article">news_article</option><option value="mention">mention</option></select></div></div><div class="field-grid"><div class="field"><label>Author</label><input name="author"></div><div class="field"><label>Rating optional</label><input name="rating" type="number" min="0" max="5" step="0.1"></div></div><div class="field"><label>Text</label><textarea name="text" required></textarea></div><div class="field-grid"><div class="field"><label>Published date optional</label><input name="published_at" type="datetime-local"></div><div class="field"><label>URL optional</label><input name="source_url" type="url"></div></div><div class="form-actions"><button type="button" class="btn btn-secondary" data-action="connect-source">Back</button><button class="btn btn-primary">Import</button></div></form>`);
}

function sourcePlaceholder(name){
  const values={'2GIS':'https://2gis.kz/almaty/firm/123…','Yandex Maps':'https://yandex.kz/maps/org/…','Google Business':'https://maps.google.com/…','Instagram':'https://instagram.com/brand','Threads':'https://threads.net/@brand','LinkedIn':'https://linkedin.com/company/brand','YouTube':'https://youtube.com/@channel','Telegram':'https://t.me/channel','Website / RSS':'https://example.com/feed.xml'};
  return values[name]||'';
}
function sourceHint(name){
  const values={'2GIS':'Open the company card → Share → Copy link.','Yandex Maps':'Open the organization → Share → Copy link.','Google Business':'Copy the Google Maps business link.','Instagram':'Paste a profile, post or Reel link.','Threads':'Paste the public profile or post link.','LinkedIn':'Paste the company or page link.','YouTube':'Paste a channel or video link.','Telegram':'Paste a public channel link or @username.','Website / RSS':'Paste the website or RSS feed URL.','Manual import':'Add the source, then paste text from Mentions.'};
  return values[name]||'Paste the exact public page URL.';
}
function apiCredentialFields(name=''){
  return `<details class="api-fields"><summary>Official API access <span class="muted">Google Business / Instagram</span></summary><p class="form-note">Saved encrypted for this workspace only.</p><div class="field"><label>Access token</label><input name="accessToken" type="password" autocomplete="off" placeholder="Paste provider access token"></div><div class="field-grid"><div class="field"><label>Google account ID</label><input name="accountId" placeholder="accounts/..."></div><div class="field"><label>Google location ID</label><input name="locationId" placeholder="locations/..."></div></div><div class="field"><label>Instagram user ID</label><input name="instagramUserId" placeholder="Instagram numeric user ID"></div></details>`;
}

async function saveApiCredentials(source,name,data){
  if(!data.accessToken)return;
  if(!['Google Business','Instagram'].includes(name))throw new Error('Official API access is currently available for Google Business and Instagram.');
  const payload={access_token:data.accessToken};
  if(name==='Google Business')Object.assign(payload,{account_id:data.accountId,location_id:data.locationId});
  if(name==='Instagram')payload.instagram_user_id=data.instagramUserId;
  const response=await fetch(apiPath(`/api/sources/${encodeURIComponent(source.id)}/credentials`),{method:'PUT',headers:{'Content-Type':'application/json',...(await apiAuthHeaders())},body:JSON.stringify(payload)});
  const body=await response.json();if(!response.ok)throw new Error(body.detail||'Could not save API access');
}

function providerSearchUrl(provider,query,city){
  const term=`${query||state.business.name} ${city||state.business.city}`.trim();
  const encoded=encodeURIComponent(term);
  if(provider==='2GIS')return `https://2gis.kz/${encodeURIComponent((city||state.business.city||'almaty').toLowerCase())}/search/${encodeURIComponent(query||state.business.name)}`;
  if(provider==='Yandex Maps')return `https://yandex.kz/maps/?text=${encoded}`;
  if(provider==='Google Business')return `https://www.google.com/maps/search/?api=1&query=${encoded}`;
  if(provider==='Instagram')return `https://www.instagram.com/explore/search/keyword/?q=${encodeURIComponent(query||state.business.name)}`;
  if(provider==='Threads')return `https://www.threads.com/search?q=${encoded}`;
  if(provider==='Telegram')return `https://www.google.com/search?q=${encodeURIComponent(`site:t.me ${term}`)}`;
  if(provider==='YouTube')return `https://www.youtube.com/results?search_query=${encoded}`;
  return `https://www.google.com/search?q=${encoded}`;
}
const importPlatforms=['2GIS','Instagram','Facebook','YouTube','Yandex Maps','Google Maps','Other'];
const importFields=['','text','author','rating','published_at','external_id','source_url','content_type','source'];
const fieldAliases={text:['text','review','comment','content','body','review_text'],author:['author','username','user','reviewer','name'],rating:['rating','stars','score'],published_at:['date','created_at','published_at','timestamp'],external_id:['id','review_id','comment_id','external_id'],source_url:['url','link','source_url'],content_type:['content_type','type'],source:['source','platform']};
function parseCsvPreview(text){
  const lines=text.replace(/^\uFEFF/,'').split(/\r?\n/).filter(line=>line.trim());
  if(!lines.length)return {fields:[],rows:[]};
  const split=line=>line.split(',').map(value=>value.trim().replace(/^"|"$/g,''));
  const fields=split(lines[0]);
  return {fields,rows:lines.slice(1,201).map(line=>Object.fromEntries(split(line).map((value,index)=>[fields[index]||`field_${index+1}`,value])))};
}
function parseJsonPreview(text){
  const payload=JSON.parse(text);
  let rows=Array.isArray(payload)?payload:null;
  if(!rows&&payload&&typeof payload==='object')for(const key of ['items','reviews','comments','data'])if(Array.isArray(payload[key]))rows=payload[key];
  rows=(rows||[]).filter(row=>row&&typeof row==='object').slice(0,200);
  const fields=[...new Set(rows.flatMap(row=>Object.keys(row)))];
  return {fields,rows};
}
function guessImportMapping(fields){
  const lower=Object.fromEntries(fields.map(field=>[field.toLowerCase(),field]));
  const result={};
  Object.entries(fieldAliases).forEach(([target,aliases])=>{const hit=aliases.find(alias=>lower[alias]);if(hit)result[target]=lower[hit];});
  return result;
}
function mappingSelect(target,fields,mapping){
  return `<div class="field"><label>${target}${target==='text'?' *':''}</label><select name="map_${target}">${importFields.filter(value=>!value||value===target).map(value=>`<option value="${value}" ${value===target?'selected':''}>${value||'Do not import'}</option>`).join('')}</select><select name="column_${target}"><option value="">Choose column</option>${fields.map(field=>`<option value="${escapeHtml(field)}" ${mapping[target]===field?'selected':''}>${escapeHtml(field)}</option>`).join('')}</select></div>`;
}
function importPreviewHtml(kind,platform,filename,fields,rows,mapping){
  const previewRows=rows.slice(0,5).map(row=>`<tr>${fields.slice(0,6).map(field=>`<td>${escapeHtml(String(row[field]??''))}</td>`).join('')}</tr>`).join('');
  return `<div class="summary"><strong>${rows.length} rows detected</strong><br>${escapeHtml(filename||kind.toUpperCase())} · ${fields.length} fields · ${escapeHtml(platform)}</div><div class="table-wrap import-preview"><table><thead><tr>${fields.slice(0,6).map(field=>`<th>${escapeHtml(field)}</th>`).join('')}</tr></thead><tbody>${previewRows}</tbody></table></div><div class="field-grid">${['text','author','rating','published_at','external_id','source_url','content_type','source'].map(target=>mappingSelect(target,fields,mapping)).join('')}</div>`;
}
function addSourceMethodModal(){
  modal(`<div class="modal-head"><div><h2>Add source</h2><p>How do you want to add data?</p></div><button class="close" data-action="close-modal">×</button></div><div class="source-method-grid"><button class="source-method" data-action="online-source"><strong>Connect online source</strong><small>2GIS, Instagram, Facebook, YouTube, Yandex or another URL</small></button><button class="source-method" data-action="upload-csv"><strong>Upload CSV</strong><small>Preview, map columns, import through SARAP analysis</small></button><button class="source-method" data-action="upload-json"><strong>Upload JSON</strong><small>Arrays or items/reviews/comments/data exports</small></button><button class="source-method" data-action="add-manual-source"><strong>Add manually</strong><small>One review, comment or mention</small></button></div>`);
}
function manualImportModal(){
  modal(`<div class="modal-head"><div><h2>Manual import</h2><p>Paste one customer message or upload a CSV with a text column.</p></div><button class="close" data-action="close-modal">×</button></div><form data-form="manual-import"><div class="field"><label>Paste customer feedback</label><textarea name="text" placeholder="Очень плохое обслуживание..."></textarea></div><div class="field"><label>Upload CSV <span class="muted">text required; author, rating, published_at, source and url optional</span></label><input name="csvFile" type="file" accept=".csv,text/csv"></div><div class="form-actions"><button type="button" class="btn btn-secondary" data-action="close-modal">Cancel</button><button class="btn btn-primary">Import and analyze</button></div></form>`);
}

function addMentionModal() {
  modal(`<div class="modal-head"><div><h2>Add a demo mention</h2><p>Runs normalization, deduplication, aspect analysis and risk scoring.</p></div><button class="close" data-action="close-modal">×</button></div><form data-form="mention"><div class="field-grid"><div class="field"><label>Source</label><select name="source"><option>2GIS</option><option>Google</option><option>Instagram</option><option>Web</option></select></div><div class="field"><label>Rating</label><input name="rating" type="number" min="1" max="5" value="2"></div></div><div class="field"><label>Customer feedback</label><textarea name="text" required placeholder="Кофе күшті, бірақ сервис өте баяу..."></textarea></div><div class="form-actions"><span></span><button class="btn btn-primary">Analyze mention</button></div></form>`);
}

function reviewExtractionModal(initialPlatform='') {
  const platforms=['2GIS','Google Maps','Yandex Maps','Instagram','Threads','TikTok','Telegram','YouTube','News','Forum_Blog'];
  modal(`<div class="modal-head"><div><h2>Extract reviews</h2><p>Copy the visible reviews from the page and paste them below.</p></div><button class="close" data-action="close-modal">×</button></div><form data-form="review-extract"><div class="field-grid"><div class="field"><label>Platform</label><select name="platformHint"><option value="">Detect automatically</option>${platforms.map(x=>`<option ${x===initialPlatform?'selected':''}>${x}</option>`).join('')}</select></div><div class="field"><label>Page URL <span class="muted">(optional)</span></label><input name="sourceUrl" type="url" placeholder="https://..."></div></div><div class="field"><label>Copied reviews</label><textarea class="extraction-input" name="content" required maxlength="120000" placeholder="Paste author, rating, date and review text..."></textarea></div><div class="extraction-rules"><span>✓ Replies stay separate</span><span>✓ Dates are preserved</span><span>✓ Duplicates are removed</span></div><div class="form-actions"><span></span><button class="btn btn-primary">Extract reviews</button></div></form>`);
}

function extractedReviewsModal() {
  const cards=pendingExtractedReviews.map((item,index)=>`<label class="extracted-review"><input type="checkbox" data-extracted-index="${index}" checked><span><strong>${escapeHtml(item.source_platform)} · ${escapeHtml(item.author_name||'Unknown')}</strong><small>${item.rating?`${item.rating}/5 · `:''}${escapeHtml(item.language)} · ${escapeHtml(item.publish_date||item.date_raw||'No date')}</small><p>${escapeHtml(item.review_text)}</p>${item.meta_info?.business_reply?`<em>Business reply: ${escapeHtml(item.meta_info.business_reply)}</em>`:''}</span><b class="status ${item.estimated_sentiment==='negative'?'high':item.estimated_sentiment==='positive'?'live':''}">${escapeHtml(item.estimated_sentiment)}</b></label>`).join('');
  closeModal();
  modal(`<div class="modal-head"><div><h2>${pendingExtractedReviews.length} review${pendingExtractedReviews.length===1?'':'s'} found</h2><p>Review the extracted data before saving it to this workspace.</p></div><button class="close" data-action="close-modal">×</button></div><div class="extracted-list">${cards}</div><div class="form-actions"><button class="btn btn-secondary" data-action="extract-reviews">← Paste again</button><button class="btn btn-primary" data-action="import-extracted">Import selected</button></div>`);
}
function analyzeDemo(text,rating) {
  const negative=/(груб|долго|баяу|дөрекі|жаман|ужас|күту|wait|late|fraud|отрав)/i.test(text); const positive=/(жақсы|керемет|күшті|вкусн|хорош|great|good)/i.test(text);
  const aspects=[]; if(/кофе|еда|дәм|food|product/i.test(text)) aspects.push(['Product',positive?'pos':'neg']); if(/кассир|персонал|груб|дөрекі|staff/i.test(text)) aspects.push(['Staff','neg']); if(/долго|баяу|күту|wait|late/i.test(text)) aspects.push(['Wait time','neg']); if(!aspects.length) aspects.push(['Overall',negative?'neg':'pos']);
  const language=/[әғқңөұүһі]/i.test(text)?(/[а-я]/i.test(text)?'Mixed KZ/RU':'Kazakh'):'Russian';
  const negativeAspects=aspects.filter(a=>a[1]==='neg');
  const risk=Math.min(100,(Number(rating)<=2?20:0)+(negative?15:0)+(negativeAspects.length*12)+(negativeAspects.length?10:0)+(negativeAspects.some(a=>['Staff','Food'].includes(a[0]))?5:0)+5+(language==='Mixed KZ/RU'?5:0)+(/отрав|fraud|мошен/i.test(text)?50:0));
  return {sentiment:negative&&positive?'mixed':negative?'negative':'positive',language,aspects,risk};
}

document.addEventListener('click', async e => {
  const route=e.target.closest('[data-route]')?.dataset.route; if(route){setRoute(route);return;}
  const actionElem = e.target.closest('[data-action]');
  const action = actionElem?.dataset.action;
  if (!action) {
    // Header filter toggle
    const headerBtn = e.target.closest('[data-toggle-header-filter]');
    if (headerBtn) {
      const key = headerBtn.dataset.toggleHeaderFilter;
      const menu = document.querySelector(`[data-filter-menu="${key}"]`);
      document.querySelectorAll('.header-filter-menu').forEach(m => m.classList.add('hidden'));
      if (menu) menu.classList.toggle('hidden');
      return;
    }
    // Mentions filter popover toggle
    if (e.target.id === 'mentions-filters-btn') {
      const pop = document.getElementById('mentions-popover');
      document.querySelectorAll('.filters-popover').forEach(p => p.classList.add('hidden'));
      if (pop) pop.classList.toggle('hidden');
      return;
    }
    // Click outside: close any open popovers
    if (!e.target.closest('.header-filter-menu') && !e.target.closest('.filters-popover') && !e.target.closest('#mentions-filters-btn')) {
      document.querySelectorAll('.header-filter-menu').forEach(m => m.classList.add('hidden'));
      document.querySelectorAll('.filters-popover').forEach(p => p.classList.add('hidden'));
    }
    return;
  }
  const target = actionElem;
  if(['landing','login','register','forgot-password'].includes(action)) setRoute(action);
  if(action==='demo'){state=structuredClone(defaultState);state.session={name:'Demo Founder',email:'demo@sarap.kz',demo:true,verified:true};state.route='overview';saveState();render();}
  if(action==='export-csv')exportMentionsCsv(filteredMentions());
  if(action==='clear-filters'){mentionFilters.source='all';mentionFilters.type='all';mentionFilters.sentiment='all';mentionFilters.analysis='all';mentionFilters.reply='all';mentionFilters.date='all';render();return;}
  if(action==='clear-secondary-filters'){mentionFilters.analysis='all';mentionFilters.reply='all';mentionFilters.date='all';render();return;}
  if(action==='clear-search'){mentionFilters.search='';const searchInp=document.querySelector('#mention-search');if(searchInp)searchInp.value='';render();return;}
  if(action==='refresh-recommendations'){target.disabled=true;await loadAnalyticsData(true);target.disabled=false;}
  if(action==='logout'){if(!state.session?.demo)await signOut();state.session=null;state.pendingEmail='';state.route='landing';saveState();render();}
  if(action==='resend-confirmation'){
    if(!state.pendingEmail){setRoute('register');return;}
    try{await resendConfirmation(state.pendingEmail);toast('Confirmation sent',`A new link was sent to ${state.pendingEmail}.`);}catch(error){toast('Could not resend email',error.message);}
  }
  if(action==='check-confirmation'){
    target.disabled=true;
    try{
      const session=await restoreSession();
      if(!session)throw new Error('Open the link in the email first, then try again.');
      applyAuthSession(session);
      if(!state.session.verified)throw new Error('Email is not confirmed yet.');
      const complete=await loadWorkspaceAfterAuth();if(complete)await loadProductData();saveState();render();
    }catch(error){target.disabled=false;toast('Confirmation not found',error.message);}
  }
  if(action==='onboarding-back'){state.onboardingStep=Math.max(1,state.onboardingStep-1);saveState();render();}
  if(action==='review'){const m=[...state.mentions,...state.discoveries].find(x=>x.id===target.dataset.id);m.reviewed=!m.reviewed;if(!state.session?.demo&&state.mentions.includes(m))await db(`/mentions?id=eq.${m.id}`,{method:'PATCH',body:{reviewed:m.reviewed,reviewed_at:m.reviewed?new Date().toISOString():null}});saveState();render();toast('Mention updated',m.reviewed?'Marked as reviewed.':'Returned to review queue.');}
  if(action==='escalate'){toast('Escalated','The mention was added to the team review queue.');}
  if(action==='open-mention'){const mention=state.mentions.find(item=>item.id===target.dataset.id);if(mention)mentionDetailModal(mention);}
  if(action==='copy-review'){const mention=state.mentions.find(item=>item.id===target.dataset.id);if(mention){await navigator.clipboard?.writeText(mention.text);toast('Copied','Review text copied.');}}
  if(action==='ignore-author'){
    const mention=state.mentions.find(item=>item.id===target.dataset.id);if(!mention)return;
    try{const response=await fetch(apiPath(`/api/mentions/${encodeURIComponent(mention.id)}/ignore-author`),{method:'POST',headers:{'Content-Type':'application/json',...(await apiAuthHeaders())},body:JSON.stringify({ignored:mention.includeInAnalysis})});const body=await response.json();if(!response.ok)throw new Error(body.detail||'Could not update author');state.mentions=body.map(mapProcessed);closeModal();await loadAnalyticsData(true);render();toast(mention.includeInAnalysis?'Author ignored':'Author restored',mention.includeInAnalysis?'Existing and future mentions from this author are excluded from analysis.':'This author is included in analysis again.');}catch(error){toast('Could not update author',friendlyError(error));}
  }
  if(action==='reply'){try{await smartReply(target.dataset.id);}catch(error){toast('Reply unavailable',friendlyError(error));}}
  if(action==='close-modal')closeModal();
  if(action==='copy-reply'){await navigator.clipboard?.writeText(target.dataset.text);toast('Copied','Review the response before sending.');closeModal();}
  if(action==='regenerate-reply'){try{await smartReply(target.dataset.id,true);toast('Reply regenerated','A fresh draft is ready to edit.');}catch(error){toast('Reply unavailable',friendlyError(error));}}
  if(action==='connect-source'||action==='onboarding-add-source')addSourceMethodModal();
  if(action==='online-source'){closeModal();addSourceModal();}
  if(action==='upload-csv'){closeModal();fileImportModal('csv');}
  if(action==='upload-json'){closeModal();fileImportModal('json');}
  if(action==='add-manual-source'){closeModal();manualSourceModal();}
  if(action==='connect-telegram'){
    target.disabled=true;
    try{const response=await fetch(apiPath(`/api/telegram/connect?business_id=${encodeURIComponent(state.business.id)}`),{method:'POST',headers:await apiAuthHeaders()});const body=await response.json();if(!response.ok)throw new Error(body.detail||'Telegram connection is unavailable');window.open(body.url,'_blank','noopener,noreferrer');toast('Telegram opened','Press Start in the SARAP bot. Your chat will connect automatically.');}catch(error){toast('Could not connect Telegram',error.message);}finally{target.disabled=false;}
  }
  if(action==='edit-source'){const source=state.sources.find(item=>item.id===target.dataset.id);if(source)editSourceModal(source);}
  if(action==='delete-source'){
    const source=state.sources.find(item=>item.id===target.dataset.id);if(!source)return;
    const itemCount=source.items==null?'all linked':source.items;
    if(!confirm(`Delete ${source.displayName||source.name}?\n\nThis will remove the source and ${itemCount} collected/imported item${itemCount===1?'':'s'} linked to it. Analytics will update after deletion.`))return;
    try{
      let deletedMentions=source.items||0;
      if(!state.session?.demo){const response=await fetch(apiPath(`/api/sources/${encodeURIComponent(source.id)}`),{method:'DELETE',headers:await apiAuthHeaders()});const body=await response.json();if(!response.ok)throw new Error(body.detail||'Could not delete source');deletedMentions=Number(body.deleted_mentions||0);}
      state.sources=state.sources.filter(item=>item.id!==source.id);saveState();render();
      if(!state.session?.demo){await loadProductData();await loadAnalyticsData(true);render();}
      toast('Source deleted',`${source.name} and ${deletedMentions} linked item${deletedMentions===1?'':'s'} were removed.`);
    }catch(error){toast('Could not delete source',error.message);}
  }
  if(action==='search-provider'){
    const form=target.closest('form');
    const query=form?.querySelector('[name="query"], [name="sourceQuery"]')?.value.trim();
    const city=form?.querySelector('[name="city"], [name="sourceCity"]')?.value.trim();
    const provider=target.dataset.provider==='selected'?form?.querySelector('[name="name"]')?.value:target.dataset.provider;
    if(!query){toast('Business name required','Enter a company name before searching.');return;}
    window.open(providerSearchUrl(provider,query,city),'_blank','noopener,noreferrer');
  }
  if(action==='poll-source'){
    const source=state.sources.find(x=>x.id===target.dataset.id);if(!source)return;
    if(syncingSourceIds.has(source.id))return;
    syncingSourceIds.add(source.id);saveState();render();
    let progress=8;target.disabled=true;target.textContent=`Collecting ${progress}%`;const timer=setInterval(()=>{progress=Math.min(90,progress+Math.max(1,Math.round((92-progress)*.12)));const button=document.querySelector(`[data-action="poll-source"][data-id="${CSS.escape(source.id)}"]`);if(button)button.textContent=`Collecting ${progress}%`;},700);
    try{await pollBackendSource(source);}catch(error){source.errors+=1;source.status='Needs attention';source.state='high';saveState();render();toast('Collection unavailable',error.message);}finally{clearInterval(timer);syncingSourceIds.delete(source.id);render();}
  }
  if(action==='add-mention')addMentionModal();
  if(action==='manual-import')manualImportModal();
  if(action==='mark-answered'){try{const response=await fetch(apiPath(`/api/mentions/${encodeURIComponent(target.dataset.id)}`),{method:'PATCH',headers:{'Content-Type':'application/json',...(await apiAuthHeaders())},body:JSON.stringify({reply_status:'answered'})});const body=await response.json();if(!response.ok)throw new Error(body.detail||'Update failed');state.mentions=state.mentions.map(item=>item.id===target.dataset.id?mapProcessed(body):item);closeModal();render();toast('Marked answered','SARAP recorded the reply status.');}catch(error){toast('Could not update reply',friendlyError(error));}}
  if(action==='extract-reviews'){closeModal();reviewExtractionModal(target.dataset.platform||'');}
  if(action==='import-extracted'){
    const selected=[...document.querySelectorAll('[data-extracted-index]:checked')].map(x=>pendingExtractedReviews[Number(x.dataset.extractedIndex)]).filter(Boolean);
    if(!selected.length){toast('Nothing selected','Select at least one extracted review.');return;}
    if(state.session?.demo){toast('Sign in required','AI extraction imports into a saved workspace.');return;}
    target.disabled=true;target.textContent='Importing…';
    try{
      const response=await fetch(apiPath('/api/reviews/import'),{method:'POST',headers:{'Content-Type':'application/json',...(await apiAuthHeaders())},body:JSON.stringify({business_id:state.business.id,reviews:selected})});
      const body=await response.json();
      if(!response.ok)throw new Error(body.detail||'Import failed');
      const imported=body.filter(x=>!x.duplicate).length;
      const duplicates=body.length-imported;
      pendingExtractedReviews=[];closeModal();await loadProductData();await loadAnalyticsData(imported>0);render();
      toast('Reviews imported',`${imported} saved${duplicates?`, ${duplicates} duplicate${duplicates===1?'':'s'} skipped`:''}.`);
    }catch(error){target.disabled=false;target.textContent='Import selected';toast('Could not import reviews',error.message);}
  }
  if(action==='alert-status'){const a=state.alerts.find(x=>x.id===target.dataset.id);a.status=a.status==='Resolved'?'New':'Resolved';if(!state.session?.demo)await db(`/alerts?id=eq.${a.id}`,{method:'PATCH',body:{status:a.status.toLowerCase(),resolved_at:a.status==='Resolved'?new Date().toISOString():null}});saveState();render();}
  if(action==='configure-alerts'){currentSettingsTab='Alerts';setRoute('settings');}
  if(action==='scan-web'){const list=document.querySelector('#discover-list');target.disabled=true;target.textContent='Scanning 30 days…';if(list)list.innerHTML='<div class="skeleton"></div><div class="skeleton"></div>';try{if(state.session?.demo){setTimeout(()=>{render();toast('Demo scan complete','Sample web discoveries are shown.');},500);}else{const response=await fetch(apiPath('/api/discover'),{method:'POST',headers:{'Content-Type':'application/json',...(await apiAuthHeaders())},body:JSON.stringify({business_id:state.business.id,brand_name:state.business.name,aliases:state.business.aliases,city:state.business.city,country:state.business.country})});const body=await response.json();if(!response.ok)throw new Error(body.detail||'Discovery failed');await loadProductData();render();const providers=(body.providers||[]).map(x=>`${x.provider}: ${x.status}${x.results?` (${x.results})`:''}`).join(' · ');toast(state.discoveries.length?'Web scan complete':'No matching mentions',`${state.discoveries.length?`${state.discoveries.length} relevant discoveries saved. `:'No result contained the configured brand name. '}${providers}`);}}catch(error){render();toast('Web scan unavailable',error.message);}}
  if(action==='admin-flag'){try{const response=await fetch(apiPath(`/api/admin/feature-flags/${encodeURIComponent(target.dataset.key)}`),{method:'PATCH',headers:{'Content-Type':'application/json',...(await apiAuthHeaders())},body:JSON.stringify({enabled:target.dataset.enabled!=='true'})});if(!response.ok)throw new Error((await response.json()).detail||'Update failed');await loadAdminData();}catch(error){toast('Could not update flag',error.message);}}
  if(action==='admin-setting'){try{const response=await fetch(apiPath(`/api/admin/system-settings/${encodeURIComponent(target.dataset.key)}`),{method:'PATCH',headers:{'Content-Type':'application/json',...(await apiAuthHeaders())},body:JSON.stringify({value:JSON.parse(target.dataset.value)})});if(!response.ok)throw new Error((await response.json()).detail||'Update failed');await loadAdminData();}catch(error){toast('Could not update setting',error.message);}}
  if(action==='save-risk-default'){const value=Number(document.querySelector('#admin-risk-default')?.value);if(!Number.isFinite(value)||value<0||value>100){toast('Invalid threshold','Enter a value from 0 to 100.');return;}try{const response=await fetch(apiPath('/api/admin/system-settings/default_risk_threshold'),{method:'PATCH',headers:{'Content-Type':'application/json',...(await apiAuthHeaders())},body:JSON.stringify({value:{value}})});if(!response.ok)throw new Error((await response.json()).detail||'Update failed');await loadAdminData();toast('Default saved',`New workspaces will start at risk ${value}.`);}catch(error){toast('Could not save default',error.message);}}
  if(action==='support-view'){try{const response=await fetch(apiPath(`/api/admin/workspaces/${target.dataset.id}`),{headers:await apiAuthHeaders()});if(!response.ok)throw new Error((await response.json()).detail||'Workspace unavailable');const data=await response.json();modal(`<div class="modal-head"><div><h2>${escapeHtml(data.business.name)}</h2><p>Read-only support view · this access is recorded.</p></div><button class="close" data-action="close-modal">×</button></div><div class="evidence"><div><strong>${data.sources.length}</strong><span>sources</span></div><div><strong>${data.mention_count_sample}</strong><span>recent mentions</span></div><div><strong>${data.recent_alerts.length}</strong><span>recent alerts</span></div></div><div class="summary" style="margin-top:14px">${data.sources.map(s=>`${escapeHtml(s.source)} · ${escapeHtml(s.status)}${s.error_message?` · ${escapeHtml(s.error_message)}`:''}`).join('<br>')||'No sources connected.'}</div>`);await loadAdminData();}catch(error){toast('Could not open workspace',error.message);}}
  if(action==='queries')modal(`<div class="modal-head"><div><h2>Query fan-out</h2><p>Generated from your brand identity and location.</p></div><button class="close" data-action="close-modal">×</button></div><div class="summary mono" style="font-size:11px">“${escapeHtml(state.business.aliases[0])}” отзывы<br>“${escapeHtml(state.business.aliases[0])}” жалоба<br>“${escapeHtml(state.business.aliases[0])}” ${escapeHtml(state.business.city)}<br>“${escapeHtml(state.business.aliases[0])}” сервис<br>“${escapeHtml(state.business.aliases[0])}” site:threads.net<br>“${escapeHtml(state.business.aliases[0])}” Қазақстан</div>`);
  if(action==='export'){const blob=new Blob([JSON.stringify(state,null,2)],{type:'application/json'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='sarap-demo-export.json';a.click();URL.revokeObjectURL(a.href);toast('Export ready','The demo workspace was exported as JSON.');}
  if(action==='reset-demo'){localStorage.removeItem(storeKey);state=structuredClone(defaultState);state.session={name:'Demo Founder',email:'demo@sarap.kz',demo:true};state.route='overview';render();toast('Demo reset','Sample mentions and settings were restored.');}
});

document.addEventListener('click', e => { const t=e.target.closest('[data-settings-tab]'); if(t){currentSettingsTab=t.dataset.settingsTab;render();} const sw=e.target.closest('[data-toggle]'); if(sw){state.settings[sw.dataset.toggle]=!state.settings[sw.dataset.toggle];saveState();render();} });
document.addEventListener('click', e => { const filter=e.target.closest('[data-sentiment-filter]'); if(filter){mentionSentimentFilter=filter.dataset.sentimentFilter;render();} });

document.addEventListener('submit', async e => {
  e.preventDefault(); const form=e.target; const kind=form.dataset.form;
  if(kind==='auth')await authSubmit(form);
  if(kind==='forgot'){const d=fieldData(form);form.classList.add('loading');try{await sendPasswordRecovery(d.email);state.pendingEmail=d.email;state.route='login';saveState();render();toast('Recovery email sent','Open the link in your inbox to choose a new password.');}catch(error){form.classList.remove('loading');toast('Could not send recovery email',error.message);}}
  if(kind==='reset-password'){const d=fieldData(form);if(d.password!==d.passwordConfirm){toast('Passwords do not match','Enter the same password twice.');return;}form.classList.add('loading');try{await updatePassword(d.password);const session=await restoreSession();if(session)applyAuthSession(session);const complete=await loadWorkspaceAfterAuth();if(complete)await loadProductData();saveState();render();toast('Password updated','Your new password is active.');}catch(error){form.classList.remove('loading');toast('Could not update password',error.message);}}
  if(kind==='onboarding')await onboardingSubmit(form);
  if(kind==='review-extract'){
    if(state.session?.demo){toast('Sign in required','AI extraction is available inside a saved workspace.');return;}
    const d=fieldData(form);form.classList.add('loading');
    try{
      const response=await fetch(apiPath('/api/reviews/extract'),{method:'POST',headers:{'Content-Type':'application/json',...(await apiAuthHeaders())},body:JSON.stringify({business_id:state.business.id,content:d.content,platform_hint:d.platformHint||null,source_url:d.sourceUrl||null})});
      const body=await response.json();
      if(!response.ok)throw new Error(body.detail||'Extraction failed');
      pendingExtractedReviews=body;
      if(!body.length){form.classList.remove('loading');toast('No reviews found','SARAP did not find genuine customer reviews in this content.');return;}
      extractedReviewsModal();
    }catch(error){form.classList.remove('loading');toast('Could not extract reviews',error.message);}
  }
  if(kind==='source'){
    const d=fieldData(form);form.classList.add('loading');
    if(!d.method)d.method='auto';
    if(['Google Business','Instagram'].includes(d.name)&&d.method==='auto'&&!d.url)d.method='api';
    if(d.name==='Manual import')d.method='import';
    if(d.method==='scraper'&&!d.url){form.classList.remove('loading');toast('URL required','Paste the public source URL.');return;}
    const urlProblem=sourceUrlProblem(d.name,d.url);
    if(urlProblem){form.classList.remove('loading');toast('Invalid source link',urlProblem);return;}
    const collectionMode=d.method==='import'?'auto':d.method;
    const duplicate=state.sources.some(s=>s.name===d.name&&s.collectionMode===collectionMode&&(s.sourceUrl||'')===(d.url||''));
    if(duplicate){form.classList.remove('loading');toast('Already connected','This source is already connected.');return;}
    try{
      if(state.session?.demo){
        const labels={auto:'Auto · API preferred',api:'API only',scraper:'URL scraper',import:'Import'};
        const needsOAuth=d.method==='api';
        const needsSetup=!d.url&&!needsOAuth&&d.method!=='import';
        const description=d.url||(needsOAuth?'Connect the official account in source settings':needsSetup?'Choose the business page to finish setup':'Manual import is ready');
        state.sources=uniqueSources([...state.sources,{id:crypto.randomUUID(),name:d.name,kind:needsOAuth?'Official':d.method==='import'?'Imported':'Monitored',collectionMode,method:labels[d.method],status:needsOAuth?'OAuth required':needsSetup?'Setup required':'Active',state:needsOAuth||needsSetup?'':'live',description,sourceUrl:d.url||'',last:'—',next:needsOAuth||needsSetup?'—':'15 min',items:0,errors:0}]);
      }else{
        const backend=await createBackendSource(d);await saveApiCredentials(backend,d.name,d);state.sources=uniqueSources([...state.sources,mapStoredSource(backend)]);
      }
    }catch(error){form.classList.remove('loading');toast('Could not add source',friendlyError(error));return;}
    saveState();closeModal();render();toast('Source added',`${d.name} was saved.`);
  }
  if(kind==='source-edit'){
    const data=fieldData(form);const source=state.sources.find(item=>item.id===form.dataset.sourceId);if(!source)return;
    const urlProblem=sourceUrlProblem(source.name,data.url);
    if(urlProblem){toast('Invalid source link',urlProblem);return;}
    try{
      if(state.session?.demo){Object.assign(source,{sourceUrl:data.url,collectionMode:data.method,method:data.method==='scraper'?'URL scraper':data.method==='api'?'API only':'Auto · API preferred',status:'Active',state:'live',description:data.url,last:'—',next:'—',errors:0,backendId:null});closeModal();saveState();render();toast('Source updated','Collection state was reset. Test collection again.');return;}
      const response=await fetch(apiPath(`/api/sources/${encodeURIComponent(source.id)}`),{method:'PATCH',headers:{'Content-Type':'application/json',...(await apiAuthHeaders())},body:JSON.stringify({source_url:data.url,collection_mode:data.method})});
      const body=await response.json();if(!response.ok)throw new Error(body.detail||'Could not update source');
      await saveApiCredentials(body,source.name,data);
      Object.assign(source,{sourceUrl:body.source_url||data.url,collectionMode:body.collection_mode||data.method,method:data.method==='scraper'?'URL scraper':data.method==='api'?'API only':'Auto · API preferred',status:'Active',state:'live',description:body.source_url||data.url,last:'—',next:'—',errors:0,backendId:body.id||source.backendId});
      closeModal();saveState();render();toast('Source updated','Collection state was reset. Test collection again.');
    }catch(error){toast('Could not update source',error.message);}
  }
  if(kind==='source-import'){
    if(!pendingSourceImport){toast('File preview required','Choose a file and confirm the field mapping first.');return;}
    const data=fieldData(form);
    const mapping={};
    ['text','author','rating','published_at','external_id','source_url','content_type','source'].forEach(target=>{const column=data[`column_${target}`];if(column)mapping[target]=column;});
    if(!mapping.text){toast('Text mapping required','Choose the column that contains review or comment text.');return;}
    form.classList.add('loading');
    try{
      const body={business_id:state.business.id,ingestion_method:form.dataset.kind,platform:data.platform,use_source_from_file:Boolean(data.useSourceFromFile),display_name:data.displayName||`${form.dataset.kind.toUpperCase()} Import`,filename:pendingSourceImport.filename,mapping};
      if(form.dataset.kind==='csv')body.csv_content=pendingSourceImport.content;else body.json_content=pendingSourceImport.content;
      const response=await fetch(apiPath('/api/sources/import'),{method:'POST',headers:{'Content-Type':'application/json',...(await apiAuthHeaders())},body:JSON.stringify(body)});
      const result=await response.json();if(!response.ok)throw new Error(result.detail||'Import failed');
      if(result.source)state.sources=uniqueSources([...state.sources,mapStoredSource(result.source)]);
      closeModal();await loadProductData();await loadAnalyticsData(result.inserted>0);render();
      toast('Import complete',`${result.total_read} read · ${result.inserted} inserted · ${result.duplicates} duplicate${result.duplicates===1?'':'s'} skipped · ${result.invalid+result.failed} failed/invalid.`);
    }catch(error){form.classList.remove('loading');toast('Could not import file',friendlyError(error));}
  }
  if(kind==='source-manual'){
    const data=fieldData(form);if(!String(data.text||'').trim()){toast('Text required','Add the mention text before importing.');return;}
    form.classList.add('loading');
    try{
      const item={text:String(data.text).trim(),author:data.author||'',rating:data.rating||'',published_at:data.published_at||'',source_url:data.source_url||'',external_id:`manual-${crypto.randomUUID()}`};
      const response=await fetch(apiPath('/api/sources/import'),{method:'POST',headers:{'Content-Type':'application/json',...(await apiAuthHeaders())},body:JSON.stringify({business_id:state.business.id,ingestion_method:'manual',platform:data.platform,display_name:'Manual entries',manual_item:item,default_content_type:data.contentType,mapping:{text:'text',author:'author',rating:'rating',published_at:'published_at',source_url:'source_url',external_id:'external_id'}})});
      const result=await response.json();if(!response.ok)throw new Error(result.detail||'Import failed');
      if(result.source)state.sources=uniqueSources([...state.sources,mapStoredSource(result.source)]);
      closeModal();await loadProductData();await loadAnalyticsData(result.inserted>0);render();toast('Manual entry imported',`${result.inserted} inserted, ${result.duplicates} duplicate skipped.`);
    }catch(error){form.classList.remove('loading');toast('Could not import entry',friendlyError(error));}
  }
  if(kind==='manual-import'){
    const data=new FormData(form), file=data.get('csvFile'), text=String(data.get('text')||'').trim();let csvContent='';
    if(file instanceof File&&file.size)csvContent=await file.text();
    if(!text&&!csvContent){toast('Feedback required','Paste feedback or choose a CSV file.');return;}
    form.classList.add('loading');
    try{const response=await fetch(apiPath('/api/manual/import'),{method:'POST',headers:{'Content-Type':'application/json',...(await apiAuthHeaders())},body:JSON.stringify({business_id:state.business.id,text:text||null,csv_content:csvContent||null})});const body=await response.json();if(!response.ok)throw new Error(body.detail||'Import failed');closeModal();await loadProductData();await loadAnalyticsData(true);render();toast('Import complete',`${body.filter(item=>!item.duplicate).length} new item(s) analyzed.`);}catch(error){form.classList.remove('loading');toast('Could not import',friendlyError(error));}
  }
  if(kind==='mention-update'){
    const d=fieldData(form),id=form.dataset.mentionId;
    try{const response=await fetch(apiPath(`/api/mentions/${encodeURIComponent(id)}`),{method:'PATCH',headers:{'Content-Type':'application/json',...(await apiAuthHeaders())},body:JSON.stringify({author_type:d.authorType,include_in_analysis:d.analysis==='included'})});const body=await response.json();if(!response.ok)throw new Error(body.detail||'Update failed');state.mentions=state.mentions.map(item=>item.id===id?mapProcessed(body):item);closeModal();await loadAnalyticsData(true);render();toast('Mention updated','Analytics were refreshed.');}catch(error){toast('Could not update mention',friendlyError(error));}
  }
  if(kind==='reply-draft'){
    const d=fieldData(form),id=form.dataset.mentionId;
    try{const response=await fetch(apiPath(`/api/mentions/${encodeURIComponent(id)}`),{method:'PATCH',headers:{'Content-Type':'application/json',...(await apiAuthHeaders())},body:JSON.stringify({reply_draft:d.replyDraft,reply_status:'draft'})});const body=await response.json();if(!response.ok)throw new Error(body.detail||'Save failed');state.mentions=state.mentions.map(item=>item.id===id?mapProcessed(body):item);closeModal();render();toast('Draft saved','The reply remains editable and was not published.');}catch(error){toast('Could not save reply',friendlyError(error));}
  }
  if(kind==='mention'){const d=fieldData(form);const normalized=d.text.trim().replace(/\s+/g,' ');if(state.mentions.some(m=>m.text.toLowerCase()===normalized.toLowerCase())){toast('Duplicate ignored','The normalized content already exists.');return;}if(state.session?.demo){const ai=analyzeDemo(normalized,d.rating);const m={id:crypto.randomUUID(),source:d.source,type:'review',author:'Manual demo entry',time:'Just now',text:normalized,rating:Number(d.rating),reviewed:false,...ai};state.mentions.unshift(m);if(m.risk>=60)state.alerts.unshift({id:crypto.randomUUID(),severity:m.risk>=80?'Critical':'High',source:m.source,time:'Just now',aspect:m.aspects.find(a=>a[1]==='neg')?.[0]||'Overall',risk:m.risk,text:m.text,status:'New'});}else{const response=await fetch(apiPath(`/api/mentions/ingest?business_id=${encodeURIComponent(state.business.id)}`),{method:'POST',headers:{'Content-Type':'application/json',...(await apiAuthHeaders())},body:JSON.stringify({source:d.source,source_type:'review',external_id:`manual-${crypto.randomUUID()}`,author_name:'Manual entry',text:normalized,rating:Number(d.rating),metadata:{origin:'manual'}})});if(!response.ok){toast('Could not analyze mention',(await response.json()).detail||'Request failed');return;}await loadProductData();}saveState();closeModal();render();toast('Mention analyzed','The mention, AI analysis and risk score were saved.');}
  if(kind==='settings'){const d=fieldData(form);if(['Business','Business profile'].includes(currentSettingsTab))Object.assign(state.business,{name:d.name,industry:d.industry,country:d.country,city:d.city,aliases:d.aliases.split('\n').map(x=>x.trim()).filter(Boolean)});if(currentSettingsTab==='Alerts')state.settings.threshold=d.threshold;if(currentSettingsTab==='AI')Object.assign(state.settings,{tone:d.tone,customAspects:d.customAspects});if(currentSettingsTab==='Account'&&d.fullName)state.session.name=d.fullName.trim();if(!state.session?.demo){try{if(['Business','Business profile'].includes(currentSettingsTab))await completeWorkspace(state.business);if(currentSettingsTab==='Account')await db(`/profiles?id=eq.${encodeURIComponent(state.accountUserId)}`,{method:'PATCH',body:{full_name:state.session.name,updated_at:new Date().toISOString()}});if(['Alerts','AI'].includes(currentSettingsTab))await db('/workspace_settings?on_conflict=business_id',{method:'POST',prefer:'resolution=merge-duplicates',body:{business_id:state.business.id,alert_threshold:state.settings.threshold==='Critical only'?80:state.settings.threshold==='All negative'?30:60,reply_tone:state.settings.tone,custom_aspects:state.settings.customAspects,telegram_alerts:true}});}catch(error){toast('Could not save settings',error.message);return;}}saveState();render();toast('Settings saved',state.session?.demo?'Saved in this browser.':'Saved to your SARAP workspace.');}
});


document.addEventListener('input',e=>{if(e.target.id==='mention-search'){const query=e.target.value.toLowerCase();document.querySelectorAll('[data-mention-row]').forEach(row=>row.classList.toggle('hidden',!row.textContent.toLowerCase().includes(query)));}});
document.addEventListener('change',e=>{

  if(e.target.matches('[data-mention-filter]')){mentionFilters[e.target.dataset.mentionFilter]=e.target.value;render();}

  if(e.target.matches('[data-import-file]')){
    const form=e.target.closest('form'), file=e.target.files?.[0], preview=form?.querySelector('[data-import-preview]'), kind=form?.dataset.kind;
    if(!file||!preview)return;
    if(file.size>2_000_000){preview.innerHTML='<p class="form-note">File is larger than the 2 MB import limit.</p>';pendingSourceImport=null;return;}
    file.text().then(content=>{
      try{
        const parsed=kind==='csv'?parseCsvPreview(content):parseJsonPreview(content);
        const mapping=guessImportMapping(parsed.fields);
        pendingSourceImport={kind,filename:file.name,content,fields:parsed.fields,rows:parsed.rows,mapping};
        const platform=form.querySelector('[name="platform"]')?.value||'Other';
        preview.innerHTML=importPreviewHtml(kind,platform,file.name,parsed.fields,parsed.rows,mapping);
      }catch(error){pendingSourceImport=null;preview.innerHTML=`<p class="form-note">${escapeHtml(error.message||'Could not parse file')}</p>`;}
    }).catch(()=>{pendingSourceImport=null;if(preview)preview.innerHTML='<p class="form-note">Could not read this file.</p>';});
  }

  if(e.target.matches('[data-source-select]')){
    const form=e.target.closest('form'), name=e.target.value, url=form?.querySelector('[name="url"]'), hint=form?.querySelector('[data-source-hint]'), method=form?.querySelector('[name="method"]');
    if(url){url.placeholder=sourcePlaceholder(name);url.required=!['Google Business','Manual import'].includes(name);}
    if(hint)hint.textContent=sourceHint(name);
    if(method)method.value=name==='Manual import'?'import':'auto';
  }
});

document.addEventListener('click',e=>{
  const button=e.target.closest('[data-mention-sort]');
  if(!button)return;

  const value=button.dataset.mentionSort;

  mentionFilters.sort=mentionFilters.sort===value
    ? value==='newest'
      ? 'oldest'
      : value==='risk'
        ? 'risk-asc'
        : value==='rating-high'
          ? 'rating-low'
          : value
    : value;

  render();
});

app.innerHTML='<main class="center-shell"><section class="form-card glass"><h2>Opening SARAP…</h2><p>Checking your secure session.</p><div class="skeleton"></div></section></main>';
await loadPublicConfig();
await initializeAuth();
render();
