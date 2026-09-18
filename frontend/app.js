import { apiAuthHeaders, completeWorkspace, consumeAuthCallback, db, isSupabaseConfigured, loadWorkspace, resendConfirmation, restoreSession, sendPasswordRecovery, signIn, signOut, signUp, updatePassword } from './supabase-client.js';

const app = document.querySelector('#app');
const storeKey = 'sarap-mvp-state-v1';

async function loadPublicConfig() {
  if (location.protocol === 'file:') return;
  try {
    const response = await fetch('/api/public-config');
    if (response.ok) window.SARAP_CONFIG = { ...(window.SARAP_CONFIG || {}), ...(await response.json()) };
  } catch { /* Local standalone demo keeps blank config and uses demo auth. */ }
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
let currentSettingsTab = 'Business';
let authReady = false;
let pendingExtractedReviews = [];

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
  const el = document.createElement('div'); el.className='toast'; el.innerHTML=`<strong>${escapeHtml(title)}</strong><small>${escapeHtml(detail)}</small>`;
  document.querySelector('#toast-region').append(el); setTimeout(()=>el.remove(), 3800);
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

function onboarding() {
  const step=state.onboardingStep;
  const stepFields = step===1 ? `<div class="field-grid"><div class="field"><label>Business name</label><input name="name" required value="${escapeHtml(state.business.name)}"></div><div class="field"><label>Website</label><input name="website" value="${escapeHtml(state.business.website)}"></div><div class="field"><label>Industry</label><select name="industry"><option>Restaurants & cafés</option><option>Retail</option><option>Healthcare</option><option>Hospitality</option><option>Services</option></select></div><div class="field"><label>Country</label><input name="country" value="Kazakhstan"></div><div class="field"><label>City</label><input name="city" value="${escapeHtml(state.business.city)}"></div><div class="field"><label>Number of locations</label><input name="locations" type="number" min="1" value="${state.business.locations}"></div></div>` : step===2 ? `<div class="field"><label>Primary brand name</label><input name="primary" required value="${escapeHtml(state.business.aliases[0]||state.business.name)}"></div><div class="field"><label>Alternative spellings, Russian / Kazakh spelling, abbreviations</label><textarea name="aliases" placeholder="One alias per line">${escapeHtml(state.business.aliases.slice(1).join('\n'))}</textarea></div><div class="field-grid"><div class="field"><label>Instagram handle</label><input name="handle" value="${escapeHtml(state.business.handle)}"></div><div class="field"><label>Website domain</label><input name="domain" value="${escapeHtml(state.business.website)}"></div></div>` : `<div class="source-search-panel"><div class="field-grid"><div class="field"><label>Business name</label><input name="sourceQuery" value="${escapeHtml(state.business.name)}" placeholder="Search business"></div><div class="field"><label>City</label><input name="sourceCity" value="${escapeHtml(state.business.city)}" placeholder="Almaty"></div></div><p class="form-note">Find your business, then add its page.</p></div><div class="source-choice onboarding-sources"><label><input type="checkbox" name="connect2gis" checked><span><strong>2GIS</strong><small>Business page</small></span><button type="button" class="btn btn-quiet" data-action="search-provider" data-provider="2GIS">Find</button><input name="twoGis" type="url" placeholder="Business page URL"></label><label><input type="checkbox" name="connectYandex"><span><strong>Yandex Maps</strong><small>Business page</small></span><button type="button" class="btn btn-quiet" data-action="search-provider" data-provider="Yandex Maps">Find</button><input name="yandexUrl" type="url" placeholder="Business page URL"></label><label><input type="checkbox" name="connectGoogle"><span><strong>Google Business</strong><small>Connect account later</small></span><button type="button" class="btn btn-quiet" data-action="search-provider" data-provider="Google Business">Find</button></label><label><input type="checkbox" name="connectInstagram"><span><strong>Instagram</strong><small>Connect account later</small></span><button type="button" class="btn btn-quiet" data-action="search-provider" data-provider="Instagram">Find</button></label></div>`;
  return `<main class="center-shell"><section class="auth-story"><button class="form-link" data-action="logout">← Sign out</button><div style="margin-top:25px">${logo()}</div><h1>Set up your workspace.</h1><p>Three short steps and you are ready.</p></section><form class="form-card glass" data-form="onboarding"><div class="eyebrow">Step ${step} of 3</div><h2>${step===1?'Tell us about the business':step===2?'Define the brand identity':'Connect your first sources'}</h2><p>${step===1?'Add the basic business details.':step===2?'Add names people may use online.':'Choose where to collect feedback.'}</p><div class="stepper"><i class="step active"></i><i class="step ${step>1?'active':''}"></i><i class="step ${step>2?'active':''}"></i></div>${stepFields}<div class="form-actions">${step>1?'<button type="button" class="btn btn-secondary" data-action="onboarding-back">Back</button>':'<span></span>'}<button class="btn btn-primary" type="submit">${step===3?'Open workspace':'Continue'} →</button></div></form></main>`;
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
  const total=data.total||0, positivePct=total?Math.round(data.positive/total*100):0, negativePct=total?Math.round(data.negative/total*100):0, score=Number(state.recommendations?.score||0), label=score<5?'Needs attention':score<8?'Good':'Excellent', recommendationGroups=state.recommendations?.recommendations||{};
  const keywordMax=Math.max(...(data.top_keywords||[]).map(x=>x.count),1);
  return `<section class="overview-section"><div class="overview-section-head"><div><span class="section-label">Analytics</span><h2>Reputation analysis</h2><p>Live breakdown from the latest saved workspace data.</p></div></div><div class="grid content-split"><article class="card glass"><div class="card-head"><div><h2>Sentiment distribution</h2><p>${data.period_start||'Current'} to ${data.period_end||'now'}</p></div></div><div class="sentiment-donut" style="--positive:${positivePct}%;--negative:${positivePct+negativePct}%"><div><strong>${total}</strong><small>mentions</small></div></div><div class="legend"><span><i></i>Positive ${data.positive||0}</span><span><i class="neg"></i>Negative ${data.negative||0}</span><span>Neutral ${data.neutral||0}</span></div></article><article class="card glass"><div class="card-head"><div><h2>Top keywords</h2><p>Frequent words in the selected period</p></div></div>${(data.top_keywords||[]).map(item=>progressRow(item.word,item.count,keywordMax,'var(--emerald)')).join('')||'<p class="muted">Keywords will appear after reviews are collected.</p>'}</article></div><article class="card glass recommendations-card"><div class="card-head"><div><h2>AI business recommendations</h2><p>Generated from the latest analyzed mentions</p></div><div class="risk-score"><strong>${score.toFixed(1)}/10</strong><small>${label}</small></div></div><p class="summary">${escapeHtml(state.recommendations?.summary||'Refresh the AI analysis after collecting reviews.')}</p><div class="grid recommendation-grid">${[['urgent_fix','Urgent fix'],['improve','Improve'],['keep_doing','Keep doing']].map(([key,title])=>`<article class="recommendation-item"><h3>${title}</h3><ul>${(recommendationGroups[key]||[]).map(item=>`<li>${escapeHtml(item)}</li>`).join('')||'<li class="muted">No items yet.</li>'}</ul></article>`).join('')}</div></article></section>`;
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

let mentionSentimentFilter='all';
function exportMentionsCsv(items){
  const header=['Review','Sentiment','Confidence','Summary'];
  const csv=[header,...items.map(item=>[item.text,item.sentiment,`${Math.round(item.confidence*100)}%`,item.summary])].map(row=>row.map(value=>`"${String(value||'').replaceAll('"','""')}"`).join(',')).join('\n');
  const link=document.createElement('a');link.href=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));link.download='sarap-mentions.csv';link.click();URL.revokeObjectURL(link.href);
}
function mentionTableRow(item){const confidence=Math.round(item.confidence*100);return `<tr data-mention-row="${item.id}"><td><strong title="${escapeHtml(item.text)}">${escapeHtml(item.text.slice(0,120))}${item.text.length>120?'…':''}</strong></td><td><span class="tag ${item.sentiment==='positive'?'pos':item.sentiment==='negative'?'neg':''}">${escapeHtml(item.sentiment)}</span></td><td><div class="progress-row"><div><span></span><strong>${confidence}%</strong></div><i><b style="width:${confidence}%"></b></i></div></td><td>${escapeHtml(item.summary||'Summary unavailable')}</td></tr>`;}
function mentions(){
  const all=state.mentions.filter(item=>mentionSentimentFilter==='all'||item.sentiment===mentionSentimentFilter);
  const actions='<button class="btn btn-secondary" data-action="export-csv">Export CSV</button><button class="btn btn-secondary" data-action="extract-reviews">Paste text / HTML</button><button class="btn btn-primary" data-action="add-mention">+ Add mention</button>';
  const pills=['all','positive','negative','neutral'].map(value=>`<button class="btn btn-quiet ${mentionSentimentFilter===value?'active':''}" data-sentiment-filter="${value}">${value[0].toUpperCase()+value.slice(1)}</button>`).join('');
  return pageHead('Mentions','Every review, post, article and discussion in one normalized feed.',actions)+(all.length?`<div class="toolbar"><div class="nav-actions">${pills}</div><input class="search" id="mention-search" type="search" placeholder="Search text, source or author…"></div><div class="table-wrap"><table><thead><tr><th>Review</th><th>Sentiment</th><th>Confidence</th><th>Summary</th></tr></thead><tbody id="mention-list">${all.map(mentionTableRow).join('')}</tbody></table></div>`:emptyState('No mentions collected','Paste copied page content or add one mention manually. SARAP will extract, normalize and analyze it.','extract-reviews','Paste text / HTML'));
}

function progressRow(name,count,total,color){const pct=Math.round(count/Math.max(total,1)*100);return `<div class="progress-row"><div><span>${escapeHtml(name)}</span><strong>${count} · ${pct}%</strong></div><i><b style="width:${pct}%;background:${color}"></b></i></div>`;}

function sources() {
  return pageHead('Sources','Connect pages and check them for new public content.','<button class="btn btn-primary" data-action="connect-source">+ Connect source</button>')+(state.sources.length?`<section class="grid source-grid">${state.sources.map(s=>`<article class="source-card glass"><div class="source-head"><div class="source-icon">${sourceIcon(s.name)}</div><div><strong style="font-size:13px">${escapeHtml(s.name)}</strong><small class="muted" style="display:block;font-size:9px">${escapeHtml(s.kind)} · ${escapeHtml(s.method||'Automatic')}</small></div><span class="status ${s.state}">${escapeHtml(s.status)}</span></div><h3>${s.name.toLowerCase().includes('youtube')?'Public channel videos':s.name.toLowerCase().includes('2gis')?'Public review monitoring':s.kind==='Official'?'Connected account':s.kind==='Monitored'?'Public page monitoring':'Historical data import'}</h3><p>${escapeHtml(s.description)}</p><div class="source-stats"><div><span>Last sync</span><strong>${escapeHtml(s.last)}</strong></div><div><span>Next sync</span><strong>${escapeHtml(s.next)}</strong></div><div><span>Items</span><strong>${s.items}</strong></div><div><span>Errors</span><strong>${s.errors}</strong></div></div>${s.kind!=='Imported'?`<div class="form-actions"><button class="btn btn-quiet" data-action="edit-source" data-id="${escapeHtml(s.id)}">Edit</button><button class="btn btn-quiet" data-action="delete-source" data-id="${escapeHtml(s.id)}">Delete</button><button class="btn btn-secondary" data-action="poll-source" data-id="${escapeHtml(s.id)}">Test collection</button></div>`:''}</article>`).join('')}</section>`:emptyState('No sources connected','Add a public page, connected account or import source.','connect-source','Connect first source'));
}

function discover() {
  return pageHead('Reputation Radar','Search social discussions, media, forums and the open web.','<button class="btn btn-primary" data-action="scan-web">Scan web now</button>')+`<section class="radar-strip glass"><div class="radar-stat"><span>Saved discoveries</span><strong>${state.discoveries.length}</strong></div><div class="radar-stat"><span>Brand aliases</span><strong>${state.business.aliases.length}</strong></div><div class="radar-stat"><span>Search region</span><strong>${escapeHtml(state.business.city||'KZ')}</strong></div><button class="btn btn-secondary" data-action="queries">View search queries</button></section><section class="mention-list" id="discover-list">${state.discoveries.map(mentionCard).join('')||emptyState('No web discoveries yet','Run a scan to search configured free web and news sources.',null,null)}</section>`;
}

function settings() {
  const tabs=['Business','Brand identity','Alerts','AI','Data','Account'];
  let content='';
  if(currentSettingsTab==='Business') content=`<h2>Business</h2><p class="muted">Used for entity matching and local analytics.</p><div class="field-grid"><div class="field"><label>Business name</label><input name="name" value="${escapeHtml(state.business.name)}"></div><div class="field"><label>Industry</label><input name="industry" value="${escapeHtml(state.business.industry)}"></div><div class="field"><label>City</label><input name="city" value="${escapeHtml(state.business.city)}"></div><div class="field"><label>Locations</label><input name="locations" type="number" value="${state.business.locations}"></div></div>`;
  if(currentSettingsTab==='Brand identity') content=`<h2>Brand identity</h2><p class="muted">Aliases help SARAP reject unrelated search results.</p><div class="field"><label>Website</label><input name="website" value="${escapeHtml(state.business.website)}"></div><div class="field"><label>Social handle</label><input name="handle" value="${escapeHtml(state.business.handle)}"></div><div class="field"><label>Aliases</label><textarea name="aliases">${escapeHtml(state.business.aliases.join('\n'))}</textarea></div>`;
  if(currentSettingsTab==='Alerts') content=`<h2>Alerts</h2><p class="muted">Control when SARAP contacts your team.</p>${toggle('Telegram alerts','Send high-risk alerts to the connected chat','telegram')}${toggle('Email alerts','Send a copy to the workspace owner','email')}<div class="field" style="margin-top:15px"><label>Alert threshold</label><select name="threshold"><option ${state.settings.threshold==='Critical only'?'selected':''}>Critical only</option><option ${state.settings.threshold==='High + Critical'?'selected':''}>High + Critical</option><option ${state.settings.threshold==='All negative'?'selected':''}>All negative</option></select></div>`;
  if(currentSettingsTab==='AI') content=`<h2>AI</h2><p class="muted">Business tone, custom aspects and the two-stage model cascade.</p><div class="provider-grid"><div class="provider-card"><span class="status live">Fast pass</span><strong>Groq</strong><small>Every new mention · structured sentiment, language and aspects</small></div><div class="provider-arrow">→</div><div class="provider-card"><span class="status high">Strong pass</span><strong>Gemini</strong><small>Mixed language, low confidence and high-risk content only</small></div></div><div class="field"><label>Reply tone</label><input name="tone" value="${escapeHtml(state.settings.tone)}"></div><div class="field"><label>Custom aspects</label><textarea name="customAspects" placeholder="Parking, menu availability, loyalty program…">${escapeHtml(state.settings.customAspects)}</textarea></div><div class="toggle-row"><div><strong>Cheap-first cascade</strong><small>Groq handles the fast pass; Gemini reviews ambiguous or critical cases.</small></div><span class="status live">Configured on server</span></div><p class="form-note">API keys stay on the server. They are never entered or stored in this browser.</p>`;
  if(currentSettingsTab==='Data') content=`<h2>Data</h2><p class="muted">Export and retention controls.</p><div class="field"><label>Retention</label><select name="retention"><option>6 months</option><option selected>12 months</option><option>24 months</option></select></div><div class="form-actions"><button type="button" class="btn btn-secondary" data-action="export">Export demo JSON</button><span class="muted" style="font-size:11px">External content is sanitized before display.</span></div>`;
  if(currentSettingsTab==='Account') content=`<h2>Account</h2><p class="muted">Email and current workspace.</p><div class="toggle-row"><div><strong>${escapeHtml(state.session?.email||'No email')}</strong><small>Account email</small></div><span class="status ${state.session?.verified||state.session?.demo?'live':'high'}">${state.session?.demo?'Demo':state.session?.verified?'Verified':'Unverified'}</span></div><div class="toggle-row"><div><strong>${escapeHtml(state.business.name)}</strong><small>${escapeHtml(state.session?.role||'Owner')}</small></div><span class="status live">Active</span></div><div class="form-actions" style="margin-top:20px"><button type="button" class="btn btn-danger" data-action="logout">Log out</button>${state.session?.demo?'<button type="button" class="btn btn-secondary" data-action="reset-demo">Reset demo data</button>':''}</div>`;
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
  if(!response.ok) throw new Error(body.detail||'Collection failed');
  source.items+=body.length;
  source.last='Just now';
  source.status=body.length?`${body.length} new`:'No new items';
  source.state=body.length?'live':'';
  if(!state.session?.demo){try{await loadProductData();}catch(error){console.warn('Collection succeeded, but workspace refresh failed:',error);}}
  saveState(); render();
  toast(body.length?'Collection finished':'No new reviews',body.length?`${body.length} review(s) collected and analyzed.`:'The source was reachable, but no new structured reviews were found.');
}

function mapStoredSource(source) {
  const labels={auto:'Automatic',api:'Connected account',scraper:'Public page'};
  const kind={official:'Official',monitored:'Monitored',provider:'Provider',imported:'Imported'}[source.connection_type]||'Monitored';
  const statuses={active:'Active',ready:'Ready',oauth_required:'OAuth required',setup_required:'Setup required',syncing:'Syncing',error:'Error'};
  const status=statuses[source.status]||source.status||'Active';
  const state=(source.error_message||source.status==='error')?'high':(source.status==='active'||source.status==='ready')?'live':'';
  const isTwoGis=String(source.source||'').toLowerCase().includes('2gis');
  const description=source.error_message||source.source_url||(isTwoGis?'Add the 2GIS business page URL to test collection.':status==='OAuth required'?'Connect the official account in source settings':'Choose the business page to finish setup');
  return {id:source.id,dbId:source.id,backendId:source.id,name:source.source,kind,collectionMode:source.collection_mode,method:kind==='Imported'?'Import':labels[source.collection_mode]||'Auto',status,state,description,sourceUrl:source.source_url||'',last:source.last_checked_at?new Date(source.last_checked_at).toLocaleString():'—',next:source.next_check_at?new Date(source.next_check_at).toLocaleString():'—',items:0,errors:source.error_message?1:0};
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

function applyWorkspace(payload) {
  if(payload?.profile) state.session={...state.session,name:payload.profile.full_name||state.session?.name||'SARAP User',email:payload.profile.email||state.session?.email,role:payload.profile.role||'user',workspaceRole:payload.role||null};
  if(!payload?.business)return false;
  const business=payload.business;
  state.business={...state.business,id:business.id,name:business.name,website:business.website||'',industry:business.industry||'',country:business.country||'Kazakhstan',city:business.city||'',locations:business.location_count||1,aliases:payload.aliases||[]};
  if(Array.isArray(payload.sources)) state.sources=uniqueSources(payload.sources.map(mapStoredSource));
  return Boolean(business.onboarding_completed);
}

function mapProcessed(row){const m=row.mention||{},a=row.analysis||{},r=row.risk||{};return {id:m.id,source:m.source,type:m.source_type==='social_post'||m.source_type==='social_comment'?'social':m.source_type==='news_article'?'news':m.source_type||'review',author:m.author_name||'Unknown author',time:m.published_at?new Date(m.published_at).toLocaleString():new Date(m.collected_at).toLocaleString(),text:m.text||'',summary:a.summary||'',confidence:Number(a.confidence||0),rating:m.rating,language:a.language||m.language||'Unknown',sentiment:a.sentiment||'neutral',risk:r.score||0,aspects:(a.aspects||[]).map(x=>[x.aspect,x.sentiment==='positive'?'pos':x.sentiment==='negative'?'neg':'neutral']),reviewed:Boolean(m.reviewed)};}
async function loadProductData(){
  if(state.session?.demo||!state.business?.id)return;
  const headers=await apiAuthHeaders();
  const mentionResponse=await fetch(apiPath(`/api/mentions?business_id=${encodeURIComponent(state.business.id)}`),{headers});
  const mentionText=await mentionResponse.text();
  let mentionPayload;
  try{mentionPayload=mentionText?JSON.parse(mentionText):null;}catch{throw new Error(mentionText.slice(0,240)||'Could not load mentions');}
  if(!mentionResponse.ok)throw new Error(mentionPayload?.detail||'Could not load mentions');
  state.mentions=(mentionPayload||[]).map(mapProcessed);
  state.sources.forEach(source=>{source.items=state.mentions.filter(item=>item.source.toLowerCase()===source.name.toLowerCase()).length;});
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
  try{
    const headers=await apiAuthHeaders();
    const [analyticsResponse,recommendationResponse]=await Promise.all([
      fetch(apiPath(`/api/analytics?business_id=${encodeURIComponent(state.business.id)}&days=30`),{headers}),
      fetch(apiPath(`/api/recommendations?business_id=${encodeURIComponent(state.business.id)}&days=30${refresh?'&refresh=true':''}`),{headers}),
    ]);
    if(!analyticsResponse.ok||!recommendationResponse.ok)throw new Error('Could not load analytics');
    state.analytics=await analyticsResponse.json();
    state.recommendations=await recommendationResponse.json();
    saveState();
    if(state.route==='overview')render();
  }catch(error){toast('Analytics unavailable',error.message);}
}
async function loadAdminData(){if(state.session?.role!=='admin')return;try{const response=await fetch(apiPath('/api/admin/overview'),{headers:await apiAuthHeaders()});if(!response.ok)throw new Error((await response.json()).detail||'Could not load admin data');state.admin=await response.json();saveState();render();}catch(error){toast('Admin data unavailable',error.message);}}

async function initializeAuth() {
  if(!isSupabaseConfigured()){if(!state.session?.demo)state.session=null;authReady=true;saveState();return;}
  try {
    const callback=consumeAuthCallback();
    const authSession=await restoreSession();
    if(!authSession){state.session=null;authReady=true;saveState();return;}
    const user=authSession.user||{};
    if(state.accountUserId!==user.id){state.business=structuredClone(emptyBusiness);state.mentions=[];state.discoveries=[];state.alerts=[];state.sources=[];state.admin=null;state.accountUserId=user.id;}
    state.session={name:user.user_metadata?.full_name||'SARAP User',email:user.email||state.pendingEmail,demo:false,verified:Boolean(user.email_confirmed_at||callback)};
    if(user.user_metadata?.business_name)state.business.name=user.user_metadata.business_name;
    if(callback?.type==='recovery'){state.route='reset-password';authReady=true;saveState();return;}
    const workspace=await loadWorkspace();
    const complete=applyWorkspace(workspace);
    if(complete)await loadProductData();
    state.route=state.session?.role==='admin'&&location.pathname==='/admin'?'admin':complete?'overview':'onboarding';
    if(state.route==='admin')setTimeout(loadAdminData,0);
    if(state.route==='overview')setTimeout(loadAnalyticsData,0);
  } catch(error) {
    state.session=null;state.route='login';setTimeout(()=>toast('Authentication error',error.message),0);
  }
  authReady=true;saveState();
}

async function authSubmit(form) {
  const data=fieldData(form);
  if(!isSupabaseConfigured()){toast('Accounts are temporarily unavailable','Open SARAP from the main local address and try again.');return;}
  if(state.route==='register'&&data.password!==data.passwordConfirm){toast('Passwords do not match','Enter the same password twice.');return;}
  form.classList.add('loading');
  try {
    if(state.route==='register'){
      const result=await signUp({email:data.email,password:data.password,fullName:data.name,businessName:data.business});
      state.pendingEmail=data.email;state.business.name=data.business;state.onboardingStep=1;
      if(result.session){state.accountUserId=result.session.user?.id||null;state.mentions=[];state.discoveries=[];state.alerts=[];state.sources=[];state.session={name:data.name,email:data.email,demo:false,verified:true};state.route='onboarding';}
      else state.route='verify-email';
    }else{
      const session=await signIn({email:data.email,password:data.password});
      if(state.accountUserId!==session.user?.id){state.business=structuredClone(emptyBusiness);state.mentions=[];state.discoveries=[];state.alerts=[];state.sources=[];state.admin=null;state.accountUserId=session.user?.id||null;}
      state.session={name:session.user?.user_metadata?.full_name||'SARAP User',email:session.user?.email||data.email,demo:false,verified:Boolean(session.user?.email_confirmed_at)};
      const workspace=await loadWorkspace();const complete=applyWorkspace(workspace);if(complete)await loadProductData();state.route=state.session?.role==='admin'?'admin':complete?'overview':'onboarding';if(state.route==='admin')setTimeout(loadAdminData,0);if(state.route==='overview')setTimeout(loadAnalyticsData,0);
    }
    saveState();render();
  }catch(error){
    form.classList.remove('loading');
    const message=String(error.message||'');
    const detail=/email not confirmed/i.test(message)
      ? 'Open the confirmation link sent to your email, then try again.'
      : /invalid login credentials/i.test(message)
        ? 'Check your email and password, or use Forgot password.'
        : message;
    toast(state.route==='register'?'Could not create account':'Could not sign in',detail);
  }
}
async function onboardingSubmit(form) {
  const data=fieldData(form);
  if(state.onboardingStep===1) Object.assign(state.business,{name:data.name,website:data.website,industry:data.industry,country:data.country,city:data.city,locations:Number(data.locations)});
  if(state.onboardingStep===2) Object.assign(state.business,{aliases:[data.primary,...data.aliases.split('\n').map(x=>x.trim()).filter(Boolean)],handle:data.handle,website:data.domain});
  if(state.onboardingStep<3) state.onboardingStep++; else {
    if(!state.session?.demo){
      form.classList.add('loading');
      try{state.business.id=await completeWorkspace(state.business);}catch(error){form.classList.remove('loading');toast('Could not save workspace',error.message);return;}
    }
    const requested=[];
    if(data.connect2gis)requested.push({name:'2GIS',method:data.twoGis?'scraper':'auto',url:data.twoGis||''});
    if(data.connectYandex)requested.push({name:'Yandex Maps',method:data.yandexUrl?'scraper':'auto',url:data.yandexUrl||''});
    if(data.connectGoogle)requested.push({name:'Google Business',method:'api',url:''});
    if(data.connectInstagram)requested.push({name:'Instagram',method:'api',url:''});
    for(const source of requested){
      try{
        if(state.session?.demo){state.sources.push({id:crypto.randomUUID(),name:source.name,kind:source.method==='api'?'Official':'Monitored',method:source.method==='api'?'API only':source.url?'URL scraper':'Setup required',status:source.method==='api'?'OAuth required':source.url?'Active':'Setup required',state:source.url?'live':'',description:source.url||'Complete this connection in Sources',sourceUrl:source.url,last:'—',next:'—',items:0,errors:0});}
        else{const saved=await createBackendSource(source);state.sources.push(mapStoredSource(saved));}
      }catch(error){toast(`${source.name} not saved`,error.message);}
    }
    state.route='overview';toast('Workspace ready','Your account and business data are saved.');
  }
  saveState(); render();
}

function smartReply(id) {
  const mention=[...state.mentions,...state.discoveries].find(m=>m.id===id); if(!mention)return;
  const critical=mention.risk>=80||/(отрав|fraud|мошен|injur|дискрим|қауіп)/i.test(mention.text);
  const reply=critical?'Human review recommended. This topic may involve safety, legal or reputational risk; SARAP will not suggest a promotional response.':mention.language.includes('Kazakh')||mention.language.includes('Mixed')?'Пікіріңізге рақмет. Күткеніңізден ұзақ қызмет көрсетілгені үшін кешірім сұраймыз. Бұл жағдайды командамен тексеріп, қызмет көрсету сапасын жақсартамыз.':'Спасибо за обратную связь. Нам жаль, что ожидание и обслуживание вас разочаровали. Мы разберём ситуацию с командой и улучшим процесс.';
  modal(`<div class="modal-head"><div><h2>${critical?'Human review':'Smart Reply'}</h2><p>SARAP matched the response language and business tone.</p></div><button class="close" data-action="close-modal">×</button></div><div class="summary">${escapeHtml(reply)}</div><p class="form-note">Not sent automatically — review before use.</p><div class="form-actions"><button class="btn btn-secondary" data-action="regenerate-reply" data-id="${id}">Regenerate</button><button class="btn btn-primary" data-action="copy-reply" data-text="${escapeHtml(reply)}">Copy reply</button></div>`);
}

function editSourceModal(source){
  modal(`<div class="modal-head"><div><h2>Edit ${escapeHtml(source.name)}</h2><p>Update the public page URL or reset the collection mode.</p></div><button class="close" data-action="close-modal">×</button></div><form data-form="source-edit" data-source-id="${escapeHtml(source.id)}"><div class="field"><label>Source page URL</label><input name="url" type="url" required value="${escapeHtml(source.sourceUrl||'')}" placeholder="https://..."></div><div class="field"><label>Collection strategy</label><select name="method"><option value="auto" ${source.collectionMode==='auto'?'selected':''}>Auto — API, then URL</option><option value="scraper" ${source.collectionMode==='scraper'?'selected':''}>Public URL scraper only</option><option value="api" ${source.collectionMode==='api'?'selected':''}>Official API only</option></select></div><div class="form-actions"><button type="button" class="btn btn-secondary" data-action="close-modal">Cancel</button><button class="btn btn-primary">Save source</button></div></form>`);
}

function addSourceModal() {
  function editSourceModal(source){
    modal(`<div class="modal-head"><div><h2>Edit ${escapeHtml(source.name)}</h2><p>Update the public page URL or reset the collection mode.</p></div><button class="close" data-action="close-modal">×</button></div><form data-form="source-edit" data-source-id="${escapeHtml(source.id)}"><div class="field"><label>Source page URL</label><input name="url" type="url" required value="${escapeHtml(source.sourceUrl||'')}" placeholder="https://..."></div><div class="field"><label>Collection strategy</label><select name="method"><option value="auto" ${source.collectionMode==='auto'?'selected':''}>Auto — API, then URL</option><option value="scraper" ${source.collectionMode==='scraper'?'selected':''}>Public URL scraper only</option><option value="api" ${source.collectionMode==='api'?'selected':''}>Official API only</option></select></div><div class="form-actions"><button type="button" class="btn btn-secondary" data-action="close-modal">Cancel</button><button class="btn btn-primary">Save source</button></div></form>`);
  }
  modal(`<div class="modal-head"><div><h2>Connect a source</h2><p>Find the company, choose collection mode and save the connection.</p></div><button class="close" data-action="close-modal">×</button></div><form data-form="source"><div class="field-grid"><div class="field"><label>Source</label><select name="name"><option>2GIS</option><option>Yandex Maps</option><option>Google Business</option><option>Instagram</option><option>Threads</option><option>Telegram</option><option>YouTube</option><option>Website / RSS</option><option>CSV Import</option></select></div><div class="field"><label>Collection strategy</label><select name="method"><option value="auto">Auto — API, then URL</option><option value="api">Official API only</option><option value="scraper">Public URL scraper only</option><option value="import">Manual import</option></select></div></div><div class="source-search-panel"><div class="field-grid"><div class="field"><label>Business name or handle</label><input name="query" value="${escapeHtml(state.business.name)}" placeholder="Coffee Boom"></div><div class="field"><label>City</label><input name="city" value="${escapeHtml(state.business.city)}" placeholder="Almaty"></div></div><button type="button" class="btn btn-secondary" data-action="search-provider" data-provider="selected">Find on selected source ↗</button></div><div class="field" style="margin-top:14px"><label>Selected business page URL</label><input name="url" type="url" placeholder="Paste the exact business page after search"></div><p class="form-note">Search opens the provider with your business and city already filled in. Select the correct card and copy its page URL here. Official API sources can be saved without a URL and will show OAuth required.</p><div class="form-actions"><span></span><button class="btn btn-primary">Add source</button></div></form>`);
  return pageHead('Sources','API-first collection with a controlled URL fallback when credentials are unavailable.','<button class="btn btn-primary" data-action="connect-source">+ Connect source</button>')+(state.sources.length?`<section class="grid source-grid">${state.sources.map(s=>`<article class="source-card glass"><div class="source-head"><div class="source-icon">${sourceIcon(s.name)}</div><div><strong style="font-size:13px">${escapeHtml(s.name)}</strong><small class="muted" style="display:block;font-size:9px">${escapeHtml(s.kind)} · ${escapeHtml(s.method||'Auto')}</small></div><span class="status ${s.state}">${escapeHtml(s.status)}</span></div><h3>${s.method?.startsWith('Auto')?'API → URL fallback':s.kind==='Official'?'Official API connection':s.kind==='Monitored'?'Focused URL monitoring':'Historical data import'}</h3><p>${escapeHtml(s.description)}</p><div class="source-stats"><div><span>Last sync</span><strong>${escapeHtml(s.last)}</strong></div><div><span>Next sync</span><strong>${escapeHtml(s.next)}</strong></div><div><span>Items</span><strong>${s.items}</strong></div><div><span>Errors</span><strong>${s.errors}</strong></div></div>${s.kind!=='Imported'?`<div class="form-actions"><button class="btn btn-quiet" data-action="edit-source" data-id="${escapeHtml(s.id)}">Edit</button><button class="btn btn-quiet" data-action="delete-source" data-id="${escapeHtml(s.id)}">Delete</button><button class="btn btn-secondary" data-action="poll-source" data-id="${escapeHtml(s.id)}">Test collection</button></div>`:''}</article>`).join('')}</section>`:emptyState('No sources connected','Add an official API, a monitored public URL, or an import source.','connect-source','Connect first source'));
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
  const action=e.target.closest('[data-action]')?.dataset.action; if(!action)return;
  const target=e.target.closest('[data-action]');
  if(['landing','login','register','forgot-password'].includes(action)) setRoute(action);
  if(action==='demo'){state=structuredClone(defaultState);state.session={name:'Demo Founder',email:'demo@sarap.kz',demo:true,verified:true};state.route='overview';saveState();render();}
  if(action==='export-csv')exportMentionsCsv(state.mentions.filter(item=>mentionSentimentFilter==='all'||item.sentiment===mentionSentimentFilter));
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
      const user=session.user||{};state.accountUserId=user.id||state.accountUserId;state.session={name:user.user_metadata?.full_name||'SARAP User',email:user.email||state.pendingEmail,demo:false,verified:Boolean(user.email_confirmed_at)};
      if(!state.session.verified)throw new Error('Email is not confirmed yet.');
      const workspace=await loadWorkspace();const complete=applyWorkspace(workspace);if(complete)await loadProductData();state.route=complete?'overview':'onboarding';saveState();render();
    }catch(error){target.disabled=false;toast('Confirmation not found',error.message);}
  }
  if(action==='onboarding-back'){state.onboardingStep=Math.max(1,state.onboardingStep-1);saveState();render();}
  if(action==='review'){const m=[...state.mentions,...state.discoveries].find(x=>x.id===target.dataset.id);m.reviewed=!m.reviewed;if(!state.session?.demo&&state.mentions.includes(m))await db(`/mentions?id=eq.${m.id}`,{method:'PATCH',body:{reviewed:m.reviewed,reviewed_at:m.reviewed?new Date().toISOString():null}});saveState();render();toast('Mention updated',m.reviewed?'Marked as reviewed.':'Returned to review queue.');}
  if(action==='escalate'){toast('Escalated','The mention was added to the team review queue.');}
  if(action==='reply')smartReply(target.dataset.id);
  if(action==='close-modal')closeModal();
  if(action==='copy-reply'){await navigator.clipboard?.writeText(target.dataset.text);toast('Copied','Review the response before sending.');closeModal();}
  if(action==='regenerate-reply'){closeModal();smartReply(target.dataset.id);toast('Reply regenerated','A fresh draft is ready to review.');}
  if(action==='connect-source')addSourceModal();
  if(action==='edit-source'){const source=state.sources.find(item=>item.id===target.dataset.id);if(source)editSourceModal(source);}
  if(action==='delete-source'){
    const source=state.sources.find(item=>item.id===target.dataset.id);if(!source)return;
    if(!confirm(`Delete ${source.name} source?`))return;
    try{
      if(!state.session?.demo){const response=await fetch(apiPath(`/api/sources/${encodeURIComponent(source.id)}`),{method:'DELETE',headers:await apiAuthHeaders()});const body=await response.json();if(!response.ok)throw new Error(body.detail||'Could not delete source');}
      state.sources=state.sources.filter(item=>item.id!==source.id);saveState();render();toast('Source deleted',`${source.name} was removed.`);
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
    target.disabled=true;target.textContent='Checking…';
    try{await pollBackendSource(source);}catch(error){source.errors+=1;source.status='Needs attention';source.state='high';saveState();render();toast('Collection unavailable',error.message);}
  }
  if(action==='add-mention')addMentionModal();
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
      pendingExtractedReviews=[];closeModal();await loadProductData();render();
      toast('Reviews imported',`${imported} saved${duplicates?`, ${duplicates} duplicate${duplicates===1?'':'s'} skipped`:''}.`);
    }catch(error){target.disabled=false;target.textContent='Import selected';toast('Could not import reviews',error.message);}
  }
  if(action==='alert-status'){const a=state.alerts.find(x=>x.id===target.dataset.id);a.status=a.status==='Resolved'?'New':'Resolved';if(!state.session?.demo)await db(`/alerts?id=eq.${a.id}`,{method:'PATCH',body:{status:a.status.toLowerCase(),resolved_at:a.status==='Resolved'?new Date().toISOString():null}});saveState();render();}
  if(action==='configure-alerts'){currentSettingsTab='Alerts';setRoute('settings');}
  if(action==='scan-web'){const list=document.querySelector('#discover-list');if(list)list.innerHTML='<div class="skeleton"></div><div class="skeleton"></div>';try{if(state.session?.demo){setTimeout(()=>{render();toast('Demo scan complete','Sample web discoveries are shown.');},500);}else{const response=await fetch(apiPath('/api/discover'),{method:'POST',headers:{'Content-Type':'application/json',...(await apiAuthHeaders())},body:JSON.stringify({business_id:state.business.id,brand_name:state.business.name,aliases:state.business.aliases,city:state.business.city,country:state.business.country})});if(!response.ok)throw new Error((await response.json()).detail||'Discovery failed');await loadProductData();render();toast('Web scan complete',`${state.discoveries.length} relevant discoveries saved.`);}}catch(error){render();toast('Web scan unavailable',error.message);}}
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
  if(kind==='reset-password'){const d=fieldData(form);if(d.password!==d.passwordConfirm){toast('Passwords do not match','Enter the same password twice.');return;}form.classList.add('loading');try{await updatePassword(d.password);const workspace=await loadWorkspace();const complete=applyWorkspace(workspace);if(complete)await loadProductData();state.route=complete?'overview':'onboarding';saveState();render();toast('Password updated','Your new password is active.');}catch(error){form.classList.remove('loading');toast('Could not update password',error.message);}}
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
    const d=fieldData(form);
    if(['Google Business','Instagram'].includes(d.name)&&d.method==='auto'&&!d.url)d.method='api';
    if(d.name==='CSV Import')d.method='import';
    if(d.method==='scraper'&&!d.url){toast('URL required','Scraper mode needs a public source URL.');return;}
    const collectionMode=d.method==='import'?'auto':d.method;
    const duplicate=state.sources.some(s=>s.name===d.name&&s.collectionMode===collectionMode&&(s.sourceUrl||'')===(d.url||''));
    if(duplicate){toast('Already connected','This source and collection strategy already exist.');return;}
    try{
      if(state.session?.demo){
        const labels={auto:'Auto · API preferred',api:'API only',scraper:'URL scraper',import:'Import'};
        const needsOAuth=d.method==='api';
        const needsSetup=!d.url&&!needsOAuth&&d.method!=='import';
        const description=d.url||(needsOAuth?'Connect the official account in source settings':needsSetup?'Choose the business page to finish setup':'Manual import is ready');
        state.sources=uniqueSources([...state.sources,{id:crypto.randomUUID(),name:d.name,kind:needsOAuth?'Official':d.method==='import'?'Imported':'Monitored',collectionMode,method:labels[d.method],status:needsOAuth?'OAuth required':needsSetup?'Setup required':'Active',state:needsOAuth||needsSetup?'':'live',description,sourceUrl:d.url||'',last:'—',next:needsOAuth||needsSetup?'—':'15 min',items:0,errors:0}]);
      }else{
        const backend=await createBackendSource(d);state.sources=uniqueSources([...state.sources,mapStoredSource(backend)]);
      }
    }catch(error){toast('Could not save source',error.message);return;}
    saveState();closeModal();render();toast('Source added',`${d.name} was saved.`);
  }
  if(kind==='source-edit'){
    const data=fieldData(form);const source=state.sources.find(item=>item.id===form.dataset.sourceId);if(!source)return;
    try{
      if(state.session?.demo){Object.assign(source,{sourceUrl:data.url,collectionMode:data.method,method:data.method==='scraper'?'URL scraper':data.method==='api'?'API only':'Auto · API preferred',status:'Active',state:'live',description:data.url,last:'—',next:'—',errors:0,backendId:null});closeModal();saveState();render();toast('Source updated','Collection state was reset. Test collection again.');return;}
      const response=await fetch(apiPath(`/api/sources/${encodeURIComponent(source.id)}`),{method:'PATCH',headers:{'Content-Type':'application/json',...(await apiAuthHeaders())},body:JSON.stringify({source_url:data.url,collection_mode:data.method})});
      const body=await response.json();if(!response.ok)throw new Error(body.detail||'Could not update source');
      Object.assign(source,{sourceUrl:body.source_url||data.url,collectionMode:body.collection_mode||data.method,method:data.method==='scraper'?'URL scraper':data.method==='api'?'API only':'Auto · API preferred',status:'Active',state:'live',description:body.source_url||data.url,last:'—',next:'—',errors:0,backendId:body.id||source.backendId});
      closeModal();saveState();render();toast('Source updated','Collection state was reset. Test collection again.');
    }catch(error){toast('Could not update source',error.message);}
  }
  if(kind==='mention'){const d=fieldData(form);const normalized=d.text.trim().replace(/\s+/g,' ');if(state.mentions.some(m=>m.text.toLowerCase()===normalized.toLowerCase())){toast('Duplicate ignored','The normalized content already exists.');return;}if(state.session?.demo){const ai=analyzeDemo(normalized,d.rating);const m={id:crypto.randomUUID(),source:d.source,type:'review',author:'Manual demo entry',time:'Just now',text:normalized,rating:Number(d.rating),reviewed:false,...ai};state.mentions.unshift(m);if(m.risk>=60)state.alerts.unshift({id:crypto.randomUUID(),severity:m.risk>=80?'Critical':'High',source:m.source,time:'Just now',aspect:m.aspects.find(a=>a[1]==='neg')?.[0]||'Overall',risk:m.risk,text:m.text,status:'New'});}else{const response=await fetch(apiPath(`/api/mentions/ingest?business_id=${encodeURIComponent(state.business.id)}`),{method:'POST',headers:{'Content-Type':'application/json',...(await apiAuthHeaders())},body:JSON.stringify({source:d.source,source_type:'review',external_id:`manual-${crypto.randomUUID()}`,author_name:'Manual entry',text:normalized,rating:Number(d.rating),metadata:{origin:'manual'}})});if(!response.ok){toast('Could not analyze mention',(await response.json()).detail||'Request failed');return;}await loadProductData();}saveState();closeModal();render();toast('Mention analyzed','The mention, AI analysis and risk score were saved.');}
  if(kind==='settings'){const d=fieldData(form);if(currentSettingsTab==='Business')Object.assign(state.business,{name:d.name,industry:d.industry,city:d.city,locations:Number(d.locations)});if(currentSettingsTab==='Brand identity')Object.assign(state.business,{website:d.website,handle:d.handle,aliases:d.aliases.split('\n').map(x=>x.trim()).filter(Boolean)});if(currentSettingsTab==='Alerts')state.settings.threshold=d.threshold;if(currentSettingsTab==='AI')Object.assign(state.settings,{tone:d.tone,customAspects:d.customAspects});if(!state.session?.demo){try{if(['Business','Brand identity'].includes(currentSettingsTab))await completeWorkspace(state.business);if(['Alerts','AI'].includes(currentSettingsTab))await db('/workspace_settings?on_conflict=business_id',{method:'POST',prefer:'resolution=merge-duplicates',body:{business_id:state.business.id,alert_threshold:state.settings.threshold==='Critical only'?80:state.settings.threshold==='All negative'?30:60,reply_tone:state.settings.tone,custom_aspects:state.settings.customAspects,email_alerts:state.settings.email,telegram_alerts:state.settings.telegram}});}catch(error){toast('Could not save settings',error.message);return;}}saveState();render();toast('Settings saved',state.session?.demo?'Saved in this browser.':'Saved to your SARAP workspace.');}
});

function filterMentions() {
  const q=document.querySelector('#mention-search')?.value.toLowerCase()||''; const type=document.querySelector('#type-filter')?.value||'all'; const risk=document.querySelector('#risk-filter')?.value||'all'; let shown=0;
  document.querySelectorAll('[data-mention]').forEach(card=>{const item=[...state.mentions,...state.discoveries].find(m=>m.id===card.dataset.mention);const text=card.textContent.toLowerCase();const typeOk=type==='all'||item.type===type;const riskOk=risk==='all'||(risk==='high'&&item.risk>=60)||(risk==='medium'&&item.risk>=30&&item.risk<60)||(risk==='low'&&item.risk<30);const match=text.includes(q)&&typeOk&&riskOk;card.classList.toggle('hidden',!match);if(match)shown++;}); document.querySelector('#mentions-empty')?.classList.toggle('hidden',shown>0);
}
document.addEventListener('input',e=>{if(e.target.id==='mention-search'){const query=e.target.value.toLowerCase();document.querySelectorAll('[data-mention-row]').forEach(row=>row.classList.toggle('hidden',!row.textContent.toLowerCase().includes(query)));}if(['type-filter','risk-filter'].includes(e.target.id))filterMentions();});
document.addEventListener('change',e=>{if(['type-filter','risk-filter'].includes(e.target.id))filterMentions();});

await loadPublicConfig();
await initializeAuth();
render();
