// Career Fit Check — SPA
'use strict';

// ── state ─────────────────────────────────────────────────────────────────────
const S = {
  screen: 'overview',
  activeCompanyId: null,
  companies: [],
  stats: { total_jobs: 0, new_jobs: 0, avg_fit: 0, companies_tracked: 0 },
  profile: { name: '', role: '', target_role: '', skills: [], skill_count: 0, initials: '' },
  compareIds: new Set(),
  compareCategory: null,  // active department filter on Compare page (null = profile target_role)
  addPhase: 'input',   // 'input' | 'scanning' | 'review'
  addInput: '',
  addResult: null,     // company detail after sync
  deepCategory: null,  // active department filter on Deep Dive page
  learnFilters: { company_id: null, category: null },  // Learn Next filter state
};

// ── API ───────────────────────────────────────────────────────────────────────
async function api(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const r = await fetch('/api' + path, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  if (r.status === 204) return null;
  return r.json();
}

// ── helpers ───────────────────────────────────────────────────────────────────
const esc = s => String(s ?? '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;');

function fitColor(v) {
  return v >= 70 ? '#15604a' : v >= 45 ? '#b9791f' : '#b1493a';
}

function initials(name) {
  const parts = (name || '').split(' ').filter(Boolean);
  return parts.length >= 2
    ? (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
    : (name || 'U').slice(0, 2).toUpperCase();
}

function colorAvatar(color, inits, size = 40, radius = 11, fontSize = 15) {
  return `<div style="width:${size}px;height:${size}px;border-radius:${radius}px;background:${color};color:#fff;display:flex;align-items:center;justify-content:center;font-family:'IBM Plex Mono',monospace;font-weight:600;font-size:${fontSize}px;flex:none;">${esc(inits)}</div>`;
}

function setHTML(id, html) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = html;
}

function setSyncLabel(text) {
  const el = document.getElementById('sync-label');
  if (el) el.textContent = text;
}

// ── navigation ────────────────────────────────────────────────────────────────
const NAV = [
  { id: 'overview',      label: 'Overview',     icon: '<svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>' },
  { id: 'deep',          label: 'Deep Dive',    icon: '<svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><path d="M3 17l4-8 4 4 4-6 4 3"/></svg>' },
  { id: 'compare',       label: 'Compare',      icon: '<svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><rect x="3" y="3" width="8" height="18" rx="1"/><rect x="13" y="7" width="8" height="14" rx="1"/></svg>' },
  { id: 'projects',      label: 'Projects',     icon: '<svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22"/></svg>' },
  { id: 'learn',         label: 'Learn Next',   icon: '<svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>' },
  { id: 'applications',  label: 'Applications', icon: '<svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><path d="M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2"/><rect x="9" y="3" width="6" height="4" rx="1"/><path d="M9 12h6M9 16h4"/></svg>' },
  { id: 'profile',       label: 'Profile',      icon: '<svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/></svg>' },
];

function renderNav() {
  const nav = document.getElementById('nav');
  if (!nav) return;
  nav.innerHTML = NAV.map(item => {
    const active = S.screen === item.id;
    return `<div class="nav-item${active ? ' active' : ''}" onclick="navigate('${item.id}')"
      style="color:${active ? '#15604a' : '#55504a'};">
      <div style="width:18px;height:18px;flex:none;display:flex;align-items:center;justify-content:center;">${item.icon}</div>
      <span style="flex:1;">${item.label}</span>
    </div>`;
  }).join('');
}

function renderProfileFooter() {
  const p = S.profile;
  const avgFit = S.stats.avg_fit || 0;
  const focusLine = p.target_role
    ? `<div style="font-family:'IBM Plex Mono',monospace;font-size:9px;color:#15604a;margin-top:2px;">● ${esc(p.target_role)}</div>`
    : '';
  setHTML('profile-footer', `
    <div style="width:34px;height:34px;border-radius:50%;background:#1b1a17;color:#fff;display:flex;align-items:center;justify-content:center;font-family:'IBM Plex Mono',monospace;font-weight:600;font-size:13px;flex:none;">${esc(p.initials || initials(p.name))}</div>
    <div style="flex:1;min-width:0;">
      <div style="font-size:12.5px;font-weight:600;line-height:1.1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(p.name)}</div>
      <div style="font-family:'IBM Plex Mono',monospace;font-size:9.5px;color:#9a9488;margin-top:2px;">AVG FIT ${avgFit}%</div>
      ${focusLine}
    </div>
  `);
  document.getElementById('profile-footer').onclick = () => navigate('profile');
}

function setTopbar(title, sub) {
  setHTML('top-title', esc(title));
  setHTML('top-sub', esc(sub));
}

function navigate(screen, options = {}) {
  S.screen = screen;
  if (options.companyId !== undefined) S.activeCompanyId = options.companyId;
  renderNav();
  renderScreen();
}

// ── OVERVIEW ──────────────────────────────────────────────────────────────────
async function renderOverview() {
  setTopbar('Overview', 'Your job market intelligence dashboard');
  const [companies, stats] = await Promise.all([
    api('GET', '/companies'),
    api('GET', '/stats'),
  ]);
  S.companies = companies;
  S.stats = stats;
  renderProfileFooter();

  const focusActive = !!(stats.target_role);
  S.profile.target_role = stats.target_role || '';

  const statCards = [
    { label: 'TOTAL OPEN ROLES', value: stats.total_jobs, delta: '', sub: 'across watchlist', deltaColor: '#9a9488' },
    { label: 'NEW THIS WEEK', value: stats.new_jobs, delta: '', sub: 'recently posted', deltaColor: '#b1493a' },
    { label: focusActive ? 'AVG FIT · ' + esc(stats.target_role) : 'AVG FIT', value: stats.avg_fit + '%', delta: '', sub: focusActive ? 'focused roles only' : 'across all companies', deltaColor: fitColor(stats.avg_fit) },
    { label: 'COMPANIES TRACKED', value: stats.companies_tracked, delta: '', sub: 'on your watchlist', deltaColor: '#9a9488' },
  ];

  const statsHtml = statCards.map(s => `
    <div style="background:#fff;border:1px solid #e7e3da;border-radius:14px;padding:16px 18px;">
      <div style="font-family:'IBM Plex Mono',monospace;font-size:10px;letter-spacing:0.6px;color:#9a9488;">${s.label}</div>
      <div style="display:flex;align-items:baseline;gap:8px;margin-top:9px;">
        <div style="font-size:30px;font-weight:600;letter-spacing:-1px;line-height:1;font-family:'IBM Plex Mono',monospace;">${esc(String(s.value))}</div>
      </div>
      <div style="font-size:11.5px;color:#7a756a;margin-top:7px;">${s.sub}</div>
    </div>`).join('');

  const cardsHtml = companies.length === 0
    ? `<div style="grid-column:1/-1;text-align:center;padding:60px;color:#9a9488;">
        <div style="font-size:32px;margin-bottom:12px;">+</div>
        <div style="font-size:15px;font-weight:600;margin-bottom:8px;">No companies yet</div>
        <div style="font-size:13px;">Click "Add company" to start tracking job market intelligence.</div>
       </div>`
    : companies.map(c => companyCard(c)).join('');

  const focusBanner = focusActive ? `
    <div style="background:#e7f0ea;border:1px solid #cfe2d6;border-radius:12px;padding:10px 16px;margin-bottom:18px;display:flex;align-items:center;gap:10px;">
      <span style="font-size:14px;">🎯</span>
      <span style="font-size:12.5px;font-weight:600;color:#15604a;">Career focus: ${esc(stats.target_role)}</span>
      <span style="font-size:12px;color:#2f6f4e;">— fit scores and skill recommendations are filtered to this role type</span>
      <span style="flex:1;"></span>
      <span style="font-family:'IBM Plex Mono',monospace;font-size:10px;color:#15604a;cursor:pointer;text-decoration:underline;" onclick="navigate('profile')">Change focus</span>
    </div>` : '';

  setHTML('screen', `<div class="anim-in" style="padding:26px 28px 60px;">
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:20px;">${statsHtml}</div>
    ${focusBanner}
    <div style="display:flex;align-items:baseline;justify-content:space-between;margin-bottom:13px;">
      <div style="font-size:13px;font-weight:600;">Your watchlist</div>
      <div style="font-family:'IBM Plex Mono',monospace;font-size:10.5px;color:#9a9488;">${companies.length} COMPANIES · SORTED BY FIT</div>
    </div>
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:14px;">${cardsHtml}</div>
  </div>`);
}

function companyCard(c) {
  const sparkSvg = c.spark
    ? `<svg viewBox="0 0 100 32" preserveAspectRatio="none" style="width:100%;height:34px;overflow:visible;"><polyline points="${c.spark}" fill="none" stroke="${c.color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"/></svg>`
    : '<div style="height:34px;"></div>';
  const newBadge = c.new_roles
    ? `<span style="font-family:'IBM Plex Mono',monospace;font-size:9.5px;font-weight:600;color:#b1493a;background:#f5e5e1;border-radius:20px;padding:2px 7px;flex:none;">+${c.new_roles} NEW</span>`
    : '';
  return `<div class="company-card" onclick="goDeep(${c.id})">
    <div style="display:flex;align-items:center;gap:12px;">
      ${colorAvatar(c.color, c.name.slice(0,2).toUpperCase(), 40, 11, 15)}
      <div style="flex:1;min-width:0;">
        <div style="display:flex;align-items:center;gap:7px;">
          <span style="font-weight:600;font-size:14.5px;line-height:1.15;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(c.name)}</span>
        </div>
        <div style="font-size:11.5px;color:#7a756a;margin-top:2px;">${esc(c.sector)}</div>
      </div>
      ${newBadge}
      <div class="remove-btn" onclick="event.stopPropagation();removeCompany(${c.id})">✕</div>
    </div>
    <div style="margin:16px 0 14px;height:34px;">${sparkSvg}</div>
    <div style="display:flex;align-items:center;gap:14px;padding-top:13px;border-top:1px solid #f0ece3;">
      <div style="flex:1;">
        <div style="font-family:'IBM Plex Mono',monospace;font-size:9.5px;color:#9a9488;letter-spacing:0.5px;">OPEN ROLES</div>
        <div style="display:flex;align-items:baseline;gap:6px;margin-top:3px;">
          <span style="font-family:'IBM Plex Mono',monospace;font-size:18px;font-weight:600;">${c.open_roles}</span>
          <span style="font-size:10.5px;font-weight:600;color:${c.vel_color};">${esc(c.vel_label)}</span>
        </div>
        ${S.profile.target_role && c.focus_roles !== c.open_roles
          ? `<div style="font-family:'IBM Plex Mono',monospace;font-size:9px;color:#15604a;margin-top:2px;">${c.focus_roles} in focus</div>`
          : ''}
      </div>
      <div style="text-align:right;">
        <div style="font-family:'IBM Plex Mono',monospace;font-size:9.5px;color:#9a9488;letter-spacing:0.5px;">YOUR FIT</div>
        <div style="font-family:'IBM Plex Mono',monospace;font-size:18px;font-weight:600;color:${c.fit_color};margin-top:3px;">${c.fit}%</div>
      </div>
    </div>
  </div>`;
}

async function removeCompany(id) {
  if (!confirm('Remove this company from your watchlist?')) return;
  await api('DELETE', `/companies/${id}`);
  await renderOverview();
}

function goDeep(id) {
  if (id !== S.activeCompanyId) S.deepCategory = null;
  navigate('deep', { companyId: id });
}

async function setDeepCategory(cat) {
  S.deepCategory = (S.deepCategory === cat) ? null : cat;
  await renderDeepDive();
}

async function setLearnFilter(field, value) {
  if (S.learnFilters[field] === value) {
    S.learnFilters[field] = null;
  } else {
    S.learnFilters[field] = value;
    if (field === 'company_id') S.learnFilters.category = null; // reset category when switching company
  }
  await renderLearn();
}

// ── DEEP DIVE ─────────────────────────────────────────────────────────────────
async function renderDeepDive() {
  const companies = S.companies.length ? S.companies : await api('GET', '/companies');
  S.companies = companies;
  if (!S.activeCompanyId && companies.length) S.activeCompanyId = companies[0].id;
  if (!S.activeCompanyId) {
    setHTML('screen', '<div style="padding:60px;text-align:center;color:#9a9488;">Add a company first to see the deep dive.</div>');
    setTopbar('Deep Dive', 'Per-company analysis');
    return;
  }

  setSyncLabel('LOADING…');
  const catParam = S.deepCategory ? `?category=${encodeURIComponent(S.deepCategory)}` : '';
  const [c, appsData] = await Promise.all([
    api('GET', `/companies/${S.activeCompanyId}${catParam}`),
    api('GET', '/applications').catch(() => ({ applications: [] })),
  ]);
  const savedJobIds = new Set((appsData.applications || []).map(a => a.job_id));
  setSyncLabel('READY');
  setTopbar(c.name, c.sector + (c.hq ? ' · ' + c.hq : ''));

  const switcher = companies.map(co => {
    const active = co.id === S.activeCompanyId;
    return `<div class="switcher-chip${active ? ' active' : ''}" onclick="goDeep(${co.id})">
      ${colorAvatar(co.color, co.name.slice(0,2).toUpperCase(), 24, 7, 11)}
      <span style="font-size:12.5px;font-weight:600;color:${active ? '#15604a' : '#55504a'};">${esc(co.name)}</span>
      <span style="font-family:'IBM Plex Mono',monospace;font-size:11px;font-weight:600;color:${co.fit_color};">${co.fit}%</span>
    </div>`;
  }).join('');

  const newBadge = c.new_roles
    ? `<span style="font-family:'IBM Plex Mono',monospace;font-size:10px;font-weight:600;color:#b1493a;background:#f5e5e1;border-radius:20px;padding:3px 9px;">${c.new_roles} NEW SINCE LAST VISIT</span>`
    : '';

  const statCards = (c.stats || []).map(s => `
    <div style="background:#fff;border:1px solid #e7e3da;border-radius:14px;padding:16px 18px;">
      <div style="font-family:'IBM Plex Mono',monospace;font-size:10px;letter-spacing:0.6px;color:#9a9488;">${esc(s.label)}</div>
      <div style="display:flex;align-items:baseline;gap:8px;margin-top:9px;">
        <div style="font-size:30px;font-weight:600;letter-spacing:-1px;line-height:1;font-family:'IBM Plex Mono',monospace;color:${s.color};">${esc(s.value)}</div>
        <div style="font-size:11.5px;font-weight:600;color:${s.delta_color};">${esc(s.delta)}</div>
      </div>
      <div style="font-size:11.5px;color:#7a756a;margin-top:7px;">${esc(s.sub)}</div>
    </div>`).join('');

  // Velocity bars
  const bars = c.bars || [];
  const barsHtml = bars.map(b => `
    <div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:6px;height:100%;justify-content:flex-end;">
      <div style="font-family:'IBM Plex Mono',monospace;font-size:9px;color:#b6b0a3;opacity:${b.label_op};">${b.value}</div>
      <div style="width:100%;max-width:26px;border-radius:5px 5px 0 0;background:${b.fill};height:${b.h}px;"></div>
      <div style="font-family:'IBM Plex Mono',monospace;font-size:8.5px;color:#bcb6aa;">${esc(b.wk)}</div>
    </div>`).join('');

  // Skills in demand — chip cloud, green = have it, red = missing
  const skillsHtml = (c.skills || []).map(k => {
    const bg    = k.you_have ? '#e7f0ea' : '#f5e5e1';
    const border = k.you_have ? '#cfe2d6' : '#f0cbc5';
    const color  = k.you_have ? '#15604a' : '#b1493a';
    const icon   = k.you_have ? '✓' : '✗';
    return `<div title="in ${k.demand_pct}% of jobs" style="display:inline-flex;align-items:center;gap:5px;background:${bg};border:1px solid ${border};border-radius:20px;padding:4px 10px;cursor:default;">
      <span style="font-family:'IBM Plex Mono',monospace;font-size:10px;font-weight:700;color:${color};">${icon}</span>
      <span style="font-size:12px;font-weight:500;color:${color};">${esc(k.name)}</span>
      <span style="font-family:'IBM Plex Mono',monospace;font-size:9px;color:${color};opacity:0.65;">${k.demand_pct}%</span>
    </div>`;
  }).join(' ');

  // Open roles — show category badge, dim jobs outside focus
  const rolesHtml = (c.roles || []).map(r => {
    const newBadge = r.is_new ? '<span style="font-family:\'IBM Plex Mono\',monospace;font-size:8.5px;font-weight:600;color:#b1493a;background:#f5e5e1;border-radius:4px;padding:1px 5px;">NEW</span>' : '';
    const catBadge = r.category
      ? `<span style="font-family:'IBM Plex Mono',monospace;font-size:8px;color:${r.in_focus ? '#15604a' : '#9a9488'};background:${r.in_focus ? '#e7f0ea' : '#f0ece3'};border-radius:4px;padding:1px 5px;flex:none;">${esc(r.category)}</span>`
      : '';
    const nudgeHtml = r.nudge ? `<div style="font-family:'IBM Plex Mono',monospace;font-size:10px;color:#b9791f;margin-top:6px;">▲ ${esc(r.nudge)}</div>` : '';
    const urlPart = r.url
      ? `<a href="${esc(r.url)}" target="_blank" style="font-size:11px;color:#15604a;text-decoration:none;margin-right:6px;" title="View job">↗</a>`
      : '';
    const rowOpacity = (c.focus_active && !r.in_focus) ? 'opacity:0.45;' : '';
    return `<div style="display:flex;align-items:center;gap:14px;padding:13px 0;border-top:1px solid #f0ece3;${rowOpacity}">
      <div style="flex:1;min-width:0;">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
          <span style="font-size:13.5px;font-weight:600;">${esc(r.title)}</span>${newBadge}${catBadge}
        </div>
        <div style="font-size:11.5px;color:#7a756a;margin-top:3px;">${esc(r.location)}${r.posted_date ? ' · ' + r.posted_date.slice(0,10) : ''}</div>
        ${nudgeHtml}
      </div>
      <div style="display:flex;align-items:center;gap:10px;flex:none;">
        ${urlPart}
        <div style="width:60px;height:6px;background:#f0ece3;border-radius:6px;overflow:hidden;">
          <div style="height:100%;border-radius:6px;background:${r.match_color};width:${r.match}%;"></div>
        </div>
        <div style="width:38px;text-align:right;font-family:'IBM Plex Mono',monospace;font-size:13px;font-weight:600;color:${r.match_color};">${r.match}%</div>
        <div id="save-btn-${r.id}" class="tailor-btn" onclick="saveJob(${r.id}, this)" title="Save to applications"${savedJobIds.has(r.id) ? ' style="color:#15604a;pointer-events:none;"' : ''}>
          <span style="font-family:'IBM Plex Mono',monospace;font-size:11px;">${savedJobIds.has(r.id) ? '✓' : '♡'}</span> ${savedJobIds.has(r.id) ? 'Saved' : 'Save'}
        </div>
        <div class="tailor-btn" onclick="openATS(${r.id},'${esc(r.title)}')" title="Score your resume against this job's ATS keywords">
          <span style="font-family:'IBM Plex Mono',monospace;font-size:11px;">⊕</span> ATS
        </div>
        <div class="tailor-btn" onclick="openTailor(${r.id},'${esc(r.title)}','${esc(c.name)}')">
          <span style="font-family:'IBM Plex Mono',monospace;font-size:11px;">✎</span> Tailor
        </div>
      </div>
    </div>`;
  }).join('');

  // Fit ring
  const ring = c.ring || { circ: 326.7, offset: 326.7 };
  const breakdown = (c.breakdown || []).map(b => `
    <div>
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:5px;">
        <span style="font-size:12px;font-weight:500;">${esc(b.name)}</span>
        <span style="font-family:'IBM Plex Mono',monospace;font-size:9.5px;font-weight:600;color:${b.color};background:${b.bg};border:1px solid ${b.border};border-radius:8px;padding:2px 7px;">${b.you_have ? '✓ ' : '✗ '}${esc(b.tag)}</span>
      </div>
      <div style="height:6px;background:#f0ece3;border-radius:6px;overflow:hidden;">
        <div style="height:100%;border-radius:6px;background:${b.bar_color};width:${b.demand_w}%;opacity:${b.you_have ? '1' : '0.45'};"></div>
      </div>
      <div style="font-family:'IBM Plex Mono',monospace;font-size:9px;color:#9a9488;margin-top:3px;">in ${b.demand_pct}% of jobs</div>
    </div>`).join('');

  // Recs
  const recsHtml = (c.recs || []).map(r => `
    <div style="background:#262420;border:1px solid #34312b;border-radius:11px;padding:13px 14px;">
      <div style="display:flex;align-items:center;justify-content:space-between;">
        <span style="font-size:13px;font-weight:600;">${esc(r.skill)}</span>
        <span style="font-family:'IBM Plex Mono',monospace;font-size:10px;font-weight:600;color:#e0b15f;">+${r.gain}% FIT</span>
      </div>
      <div style="position:relative;height:6px;background:#3a352d;border-radius:6px;margin:10px 0 8px;overflow:visible;">
        <div style="height:100%;border-radius:6px;background:#b9791f;width:${r.level_w}%;"></div>
        <div style="position:absolute;top:-2px;width:2px;height:10px;background:#f6f4ef;border-radius:2px;left:${r.target_w}%;"></div>
      </div>
      <div style="font-family:'IBM Plex Mono',monospace;font-size:10px;color:#a9a397;">${esc(r.detail)}</div>
    </div>`).join('');

  const syncedLabel = c.last_synced
    ? 'SYNCED ' + c.last_synced.slice(0, 10)
    : 'NOT YET SYNCED';

  setHTML('screen', `<div class="anim-in" style="padding:20px 28px 60px;">

    <div style="display:flex;gap:8px;overflow-x:auto;padding-bottom:14px;margin-bottom:6px;">${switcher}</div>

    <div style="display:flex;align-items:center;gap:16px;margin-bottom:20px;">
      ${colorAvatar(c.color, c.name.slice(0,2).toUpperCase(), 54, 14, 21)}
      <div style="flex:1;">
        <div style="display:flex;align-items:center;gap:10px;">
          <div style="font-size:22px;font-weight:600;letter-spacing:-0.4px;">${esc(c.name)}</div>
          ${newBadge}
        </div>
        <div style="font-size:13px;color:#7a756a;margin-top:4px;">${esc(c.sector)}${c.hq ? ' · ' + c.hq : ''}</div>
      </div>
      <button class="btn-primary" onclick="syncCompany(${c.id})" id="sync-btn">↻ Sync now</button>
    </div>

    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:20px;">${statCards}</div>

    <div style="display:grid;grid-template-columns:1fr 358px;gap:18px;align-items:start;">

      <div style="display:flex;flex-direction:column;gap:18px;min-width:0;">

        <div style="background:#fff;border:1px solid #e7e3da;border-radius:16px;padding:20px;">
          <div style="display:flex;align-items:baseline;justify-content:space-between;margin-bottom:18px;">
            <div>
              <div style="font-size:13.5px;font-weight:600;">Hiring velocity</div>
              <div style="font-size:11.5px;color:#7a756a;margin-top:2px;">Open roles tracked, last 12 weeks</div>
            </div>
            <div style="font-family:'IBM Plex Mono',monospace;font-size:11px;font-weight:600;color:${c.vel_color};">${esc(c.vel_label)} 12W</div>
          </div>
          <div style="display:flex;align-items:flex-end;gap:5px;height:130px;">${barsHtml}</div>
        </div>

        <div style="background:#f7edda;border:1px solid #ecddc0;border-radius:14px;padding:15px 17px;display:flex;gap:12px;align-items:flex-start;">
          <div style="width:22px;height:22px;border-radius:6px;background:#b9791f;color:#fff;display:flex;align-items:center;justify-content:center;flex:none;font-family:'IBM Plex Mono',monospace;font-size:11px;font-weight:600;">✦</div>
          <div style="flex:1;">
            <div style="font-family:'IBM Plex Mono',monospace;font-size:9.5px;letter-spacing:0.6px;color:#9a7c33;margin-bottom:4px;">AI&nbsp;NUDGE</div>
            <div style="font-size:13px;line-height:1.5;color:#5e4d22;">${esc(c.nudge)}</div>
            ${c.ai_summary ? `<div style="font-size:12px;line-height:1.55;color:#7a5e2a;margin-top:9px;padding-top:9px;border-top:1px solid #ecddc0;">${esc(c.ai_summary)}</div>` : ''}
          </div>
        </div>

        ${(() => {
          const cats = c.available_categories || [];
          if (!cats.length) return '';
          const allActive = !S.deepCategory;
          const chips = cats.map(cat => {
            const active = cat.name === S.deepCategory;
            return `<div onclick="setDeepCategory('${esc(cat.name)}')" style="cursor:pointer;display:flex;align-items:center;gap:5px;padding:4px 11px;border-radius:20px;font-size:11.5px;font-weight:${active ? '600' : '500'};background:${active ? '#15604a' : '#fff'};color:${active ? '#fff' : '#55504a'};border:1px solid ${active ? '#15604a' : '#e7e3da'};white-space:nowrap;transition:all .15s;">${esc(cat.name)}<span style="font-family:'IBM Plex Mono',monospace;font-size:9.5px;opacity:0.7;">${cat.count}</span></div>`;
          }).join('');
          return `<div style="display:flex;align-items:center;gap:7px;flex-wrap:wrap;padding:10px 13px;background:#fbfaf6;border:1px solid #f0ece3;border-radius:11px;">
            <span style="font-family:'IBM Plex Mono',monospace;font-size:9.5px;letter-spacing:0.5px;color:#9a9488;flex:none;">DEPT</span>
            <div onclick="setDeepCategory(null)" style="cursor:pointer;padding:4px 11px;border-radius:20px;font-size:11.5px;font-weight:${allActive ? '600' : '500'};background:${allActive ? '#1b1a17' : '#fff'};color:${allActive ? '#fff' : '#55504a'};border:1px solid ${allActive ? '#1b1a17' : '#e7e3da'};transition:all .15s;">All</div>
            ${chips}
          </div>`;
        })()}

        <div style="background:#fff;border:1px solid #e7e3da;border-radius:16px;padding:20px;">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;gap:10px;">
            <div style="font-size:13.5px;font-weight:600;">Skills in demand${S.deepCategory ? ` <span style="font-family:'IBM Plex Mono',monospace;font-size:10px;font-weight:500;color:#15604a;background:#e7f0ea;border-radius:6px;padding:2px 7px;">${esc(S.deepCategory)}</span>` : ''}</div>
            <div style="display:flex;align-items:center;gap:10px;flex:none;">
              <span style="display:flex;align-items:center;gap:4px;font-family:'IBM Plex Mono',monospace;font-size:9px;color:#15604a;"><span style="font-weight:700;">✓</span>IN PROFILE</span>
              <span style="display:flex;align-items:center;gap:4px;font-family:'IBM Plex Mono',monospace;font-size:9px;color:#b1493a;"><span style="font-weight:700;">✗</span>MISSING</span>
            </div>
          </div>
          <div style="display:flex;flex-wrap:wrap;gap:7px;">
            ${skillsHtml || '<div style="color:#9a9488;font-size:12px;">Sync to load skill data.</div>'}
          </div>
        </div>

        <div style="background:#fff;border:1px solid #e7e3da;border-radius:16px;padding:20px;">
          <div style="display:flex;align-items:baseline;justify-content:space-between;margin-bottom:14px;">
            <div style="font-size:13.5px;font-weight:600;">Open roles</div>
            <div style="font-family:'IBM Plex Mono',monospace;font-size:10px;color:#9a9488;">MATCH = FIT TO THIS ROLE</div>
          </div>
          <div style="display:flex;flex-direction:column;">
            ${rolesHtml || '<div style="padding:20px 0;text-align:center;color:#9a9488;font-size:12px;">No roles yet — click Sync to load jobs.</div>'}
          </div>
        </div>

      </div>

      <div style="display:flex;flex-direction:column;gap:18px;">

        <div style="background:#fff;border:1px solid #e7e3da;border-radius:16px;padding:20px;">
          <div style="font-size:13.5px;font-weight:600;margin-bottom:4px;">Your fit</div>
          <div style="font-size:11.5px;color:#7a756a;">Skill-by-skill vs what they ask</div>

          <div style="display:flex;align-items:center;gap:18px;margin:18px 0 6px;">
            <div style="position:relative;width:118px;height:118px;flex:none;">
              <svg width="118" height="118" viewBox="0 0 118 118">
                <circle cx="59" cy="59" r="52" fill="none" stroke="#efeae0" stroke-width="11"></circle>
                <circle cx="59" cy="59" r="52" fill="none" stroke="${c.fit_color}" stroke-width="11" stroke-linecap="round"
                  stroke-dasharray="${ring.circ}" stroke-dashoffset="${ring.offset}" transform="rotate(-90 59 59)"></circle>
              </svg>
              <div style="position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;">
                <div style="font-family:'IBM Plex Mono',monospace;font-size:28px;font-weight:600;line-height:1;color:${c.fit_color};">${c.fit}</div>
                <div style="font-family:'IBM Plex Mono',monospace;font-size:9.5px;color:#9a9488;margin-top:2px;">% FIT</div>
              </div>
            </div>
            <div style="flex:1;">
              <div style="font-size:13px;font-weight:600;color:${c.fit_color};">${esc(c.fit_label)}</div>
              <div style="font-size:11.5px;color:#7a756a;line-height:1.5;margin-top:6px;">${esc(c.fit_note)}</div>
            </div>
          </div>

          <div style="display:flex;flex-direction:column;gap:11px;margin-top:14px;padding-top:16px;border-top:1px solid #f0ece3;">
            ${breakdown || '<div style="color:#9a9488;font-size:12px;">Sync to compute skill breakdown.</div>'}
          </div>
          <div style="display:flex;align-items:center;gap:14px;margin-top:14px;font-family:'IBM Plex Mono',monospace;font-size:9.5px;color:#9a9488;flex-wrap:wrap;">
            <span style="display:flex;align-items:center;gap:5px;"><span style="width:14px;height:6px;background:#15604a;border-radius:3px;"></span>YOU HAVE IT</span>
            <span style="display:flex;align-items:center;gap:5px;"><span style="width:14px;height:6px;background:#b1493a;opacity:0.45;border-radius:3px;"></span>NOT IN PROFILE</span>
            <span style="margin-left:auto;">BAR = % of jobs mentioning skill</span>
          </div>
        </div>

        <div style="background:#1b1a17;border-radius:16px;padding:20px;color:#f6f4ef;">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
            <span style="width:18px;height:18px;border-radius:5px;background:#b9791f;display:flex;align-items:center;justify-content:center;font-size:10px;">✦</span>
            <span style="font-size:13.5px;font-weight:600;">What to learn next</span>
          </div>
          <div style="font-size:11.5px;color:#a9a397;line-height:1.5;">To raise your ${esc(c.name)} fit fastest</div>
          <div style="display:flex;flex-direction:column;gap:10px;margin-top:16px;">
            ${recsHtml || '<div style="color:#a9a397;font-size:12px;padding:8px 0;">Sync to get personalised recommendations.</div>'}
          </div>
          <div class="learn-link" onclick="S.learnFilters={company_id:${c.id},category:${c.active_category ? `'${c.active_category}'` : 'null'}};navigate('learn')">See full learning plan →</div>
        </div>

        <div style="font-family:'IBM Plex Mono',monospace;font-size:10px;color:#9a9488;text-align:center;">${syncedLabel}</div>
      </div>
    </div>
  </div>`);
}

async function syncCompany(id) {
  const btn = document.getElementById('sync-btn');
  if (btn) { btn.textContent = '⟳ Syncing…'; btn.disabled = true; }
  setSyncLabel('SYNCING…');
  try {
    const res = await api('POST', `/companies/${id}/sync`);
    setSyncLabel(`SYNCED — ${res.jobs_new} new jobs`);
    setTimeout(() => setSyncLabel('READY'), 3000);
    await renderDeepDive();
  } catch (e) {
    setSyncLabel('SYNC FAILED');
    alert('Sync failed: ' + e.message);
    setTimeout(() => setSyncLabel('READY'), 3000);
  }
}

// ── COMPARE ───────────────────────────────────────────────────────────────────
async function renderCompare() {
  setTopbar('Compare', 'Side-by-side skill gap analysis');
  const companies = S.companies.length ? S.companies : await api('GET', '/companies');
  S.companies = companies;

  if (companies.length === 0) {
    setHTML('screen', '<div style="padding:60px;text-align:center;color:#9a9488;">Add companies to use the compare view.</div>');
    return;
  }

  // Default: select first 3
  if (S.compareIds.size === 0) {
    companies.slice(0, 3).forEach(c => S.compareIds.add(c.id));
  }

  const chipsHtml = companies.map(c => {
    const sel = S.compareIds.has(c.id);
    return `<div class="compare-chip${sel ? ' selected' : ''}" onclick="toggleCompare(${c.id})">
      ${colorAvatar(c.color, c.name.slice(0,2).toUpperCase(), 22, 6, 10)}
      <span style="font-size:12.5px;font-weight:600;color:${sel ? '#15604a' : '#55504a'};">${esc(c.name)}</span>
    </div>`;
  }).join('');

  const ids = [...S.compareIds].join(',');
  if (!ids) {
    setHTML('screen', `<div class="anim-in" style="padding:26px 28px 60px;">
      <div style="font-size:12.5px;color:#7a756a;margin-bottom:13px;">Pick companies to compare.</div>
      <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:24px;">${chipsHtml}</div>
    </div>`);
    return;
  }

  // Default category to profile career focus when not explicitly overridden
  if (S.compareCategory === null && S.profile.target_role) {
    S.compareCategory = S.profile.target_role;
  }

  setSyncLabel('LOADING…');
  const catParam = S.compareCategory ? `&category=${encodeURIComponent(S.compareCategory)}` : '';
  const data = await api('GET', `/compare?ids=${ids}${catParam}`);
  setSyncLabel('READY');

  const cols = data.companies.length;
  const fitCards = data.companies.map(c => `
    <div style="background:#fff;border:1px solid #e7e3da;border-radius:14px;padding:16px 18px;">
      <div style="display:flex;align-items:center;gap:10px;">
        ${colorAvatar(c.color, c.initials, 32, 9, 12)}
        <div style="flex:1;min-width:0;">
          <div style="font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(c.name)}</div>
          <div style="font-size:10.5px;color:#7a756a;">${c.open_roles} open roles</div>
        </div>
      </div>
      <div style="display:flex;align-items:flex-end;gap:8px;margin-top:14px;">
        <div style="font-family:'IBM Plex Mono',monospace;font-size:30px;font-weight:600;line-height:1;color:${c.fit_color};">${c.fit}<span style="font-size:14px;">%</span></div>
        <div style="font-size:11px;color:#7a756a;padding-bottom:3px;">your fit</div>
      </div>
      <div style="height:7px;background:#f0ece3;border-radius:6px;overflow:hidden;margin-top:10px;">
        <div style="height:100%;border-radius:6px;background:${c.fit_color};width:${c.fit}%;"></div>
      </div>
    </div>`).join('');

  const headerCols = data.companies.map(c =>
    `<div style="flex:1;min-width:100px;display:flex;flex-direction:column;align-items:center;gap:5px;">
      ${colorAvatar(c.color, c.initials, 26, 7, 10)}
      <div style="font-size:11px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:90px;text-align:center;">${esc(c.short || c.name.slice(0,12))}</div>
    </div>`
  ).join('');

  const matrixRows = data.rows.map(row => {
    const cells = row.cells.map(cell =>
      `<div style="flex:1;min-width:100px;display:flex;justify-content:center;align-items:center;">
        ${cell.present
          ? `<div style="width:30px;height:30px;border-radius:50%;background:#e7f0ea;border:1.5px solid #cfe2d6;display:flex;align-items:center;justify-content:center;color:#15604a;font-size:15px;font-weight:700;">✓</div>`
          : `<div style="width:30px;height:30px;border-radius:50%;background:#f3efe7;display:flex;align-items:center;justify-content:center;color:#c8c2b8;font-size:18px;line-height:1;">—</div>`
        }
      </div>`
    ).join('');

    const isUniversal = row.coverage === cols;
    const rowBg = row.i_have ? 'rgba(231,240,234,0.45)' : isUniversal ? 'rgba(245,229,225,0.35)' : 'transparent';
    const statusBadge = row.i_have
      ? `<span style="font-family:'IBM Plex Mono',monospace;font-size:9px;font-weight:600;color:#15604a;background:#e7f0ea;border:1px solid #cfe2d6;border-radius:10px;padding:2px 7px;">YOU HAVE IT</span>`
      : `<span style="font-family:'IBM Plex Mono',monospace;font-size:9px;font-weight:600;color:#b1493a;background:#f5e5e1;border:1px solid #f0cbc5;border-radius:10px;padding:2px 7px;">GAP</span>`;

    return `<div style="display:flex;align-items:center;padding:10px 8px;border-bottom:1px solid #f3efe7;background:${rowBg};border-radius:6px;">
      <div style="width:170px;flex:none;padding-right:10px;">
        <div style="font-size:12.5px;font-weight:500;margin-bottom:4px;">${esc(row.skill)}</div>
        ${statusBadge}
      </div>
      <div style="width:52px;flex:none;text-align:center;padding-right:8px;">
        <div style="font-family:'IBM Plex Mono',monospace;font-size:15px;font-weight:700;color:${isUniversal ? '#15604a' : '#7a756a'};">${esc(row.coverage_label)}</div>
        <div style="font-family:'IBM Plex Mono',monospace;font-size:8.5px;color:#9a9488;letter-spacing:0.3px;">COS</div>
      </div>
      ${cells}
    </div>`;
  }).join('');

  const availCats = data.available_categories || [];
  const activeCat = data.active_category || null;
  const catChipsHtml = availCats.map(cat => {
    const active = activeCat === cat;
    return `<div onclick="setCompareCategory('${esc(cat)}')" style="cursor:pointer;padding:5px 12px;border-radius:20px;font-size:11.5px;font-weight:${active ? '600' : '500'};background:${active ? '#15604a' : '#fff'};color:${active ? '#fff' : '#55504a'};border:1px solid ${active ? '#15604a' : '#e7e3da'};white-space:nowrap;transition:all .15s;">${esc(cat)}</div>`;
  }).join('');

  const catFilterBar = availCats.length ? `
    <div style="margin-bottom:18px;">
      <div style="font-family:'IBM Plex Mono',monospace;font-size:9.5px;letter-spacing:0.5px;color:#9a9488;margin-bottom:8px;">FILTER BY DEPARTMENT</div>
      <div style="display:flex;flex-wrap:wrap;gap:7px;align-items:center;">
        <div onclick="setCompareCategory(null)" style="cursor:pointer;padding:5px 12px;border-radius:20px;font-size:11.5px;font-weight:${!activeCat ? '600' : '500'};background:${!activeCat ? '#1b1a17' : '#fff'};color:${!activeCat ? '#fff' : '#55504a'};border:1px solid ${!activeCat ? '#1b1a17' : '#e7e3da'};white-space:nowrap;transition:all .15s;">All</div>
        ${catChipsHtml}
      </div>
    </div>` : '';

  const focusLabel = activeCat
    ? `<span style="font-family:'IBM Plex Mono',monospace;font-size:10px;color:#15604a;background:#e7f0ea;border:1px solid #cfe2d6;border-radius:10px;padding:2px 9px;margin-left:8px;">${esc(activeCat)}</span>`
    : '';

  setHTML('screen', `<div class="anim-in" style="padding:26px 28px 60px;">
    <div style="font-size:12.5px;color:#7a756a;margin-bottom:13px;">Select companies to compare. Skills sorted by how many companies need them.${focusLabel}</div>
    <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:18px;">${chipsHtml}</div>
    ${catFilterBar}

    <div style="display:grid;grid-template-columns:repeat(${cols},1fr);gap:14px;margin-bottom:22px;">${fitCards}</div>

    <div style="background:#fff;border:1px solid #e7e3da;border-radius:16px;padding:8px 20px 16px;overflow-x:auto;">
      <div style="display:flex;align-items:flex-end;padding:14px 8px 12px;border-bottom:1px solid #ece7dd;font-family:'IBM Plex Mono',monospace;font-size:10px;letter-spacing:0.5px;color:#9a9488;">
        <div style="width:170px;flex:none;">SKILL</div>
        <div style="width:52px;flex:none;text-align:center;">COS</div>
        ${headerCols}
      </div>
      ${matrixRows || '<div style="padding:20px 0;color:#9a9488;font-size:12px;">Sync companies to see skill data.</div>'}
      <div style="display:flex;align-items:center;gap:18px;padding-top:14px;font-family:'IBM Plex Mono',monospace;font-size:9.5px;color:#9a9488;flex-wrap:wrap;">
        <span style="display:flex;align-items:center;gap:6px;"><span style="width:14px;height:14px;border-radius:50%;background:#e7f0ea;border:1.5px solid #cfe2d6;display:flex;align-items:center;justify-content:center;color:#15604a;font-size:9px;">✓</span>COMPANY NEEDS IT</span>
        <span style="display:flex;align-items:center;gap:6px;"><span style="width:14px;height:14px;border-radius:50%;background:#f3efe7;display:flex;align-items:center;justify-content:center;color:#c8c2b8;font-size:11px;">—</span>NOT REQUIRED</span>
        <span style="display:flex;align-items:center;gap:6px;"><span style="display:inline-block;width:12px;height:12px;border-radius:3px;background:rgba(231,240,234,0.8);border:1px solid #cfe2d6;"></span>YOU HAVE IT</span>
        <span style="display:flex;align-items:center;gap:6px;"><span style="display:inline-block;width:12px;height:12px;border-radius:3px;background:rgba(245,229,225,0.6);border:1px solid #f0cbc5;"></span>UNIVERSAL GAP</span>
        <span style="margin-left:auto;">COS = companies needing this skill</span>
      </div>
    </div>

    <div style="background:#e7f0ea;border:1px solid #cfe2d6;border-radius:14px;padding:16px 18px;margin-top:18px;display:flex;gap:12px;align-items:flex-start;">
      <div style="width:22px;height:22px;border-radius:6px;background:#15604a;color:#fff;display:flex;align-items:center;justify-content:center;flex:none;font-size:12px;">✓</div>
      <div style="font-size:13px;line-height:1.5;color:#1d4d3c;">${esc(data.verdict)}</div>
    </div>
  </div>`);
}

function toggleCompare(id) {
  if (S.compareIds.has(id)) { S.compareIds.delete(id); }
  else { S.compareIds.add(id); }
  renderCompare();
}

function setCompareCategory(cat) {
  S.compareCategory = cat;
  renderCompare();
}

// ── LEARN ─────────────────────────────────────────────────────────────────────
async function renderLearn() {
  setTopbar('Learn Next', 'Prioritised skills to close your gaps');
  setSyncLabel('LOADING…');
  const params = new URLSearchParams();
  if (S.learnFilters.company_id) params.set('company_id', S.learnFilters.company_id);
  if (S.learnFilters.category) params.set('category', S.learnFilters.category);
  const qs = params.toString() ? '?' + params.toString() : '';
  const data = await api('GET', '/learn' + qs);
  setSyncLabel('READY');

  const statsHtml = (data.stats || []).map(s => `
    <div>
      <div style="font-family:'IBM Plex Mono',monospace;font-size:26px;font-weight:600;color:#e0b15f;">${esc(s.value)}</div>
      <div style="font-size:11px;color:#a9a397;margin-top:3px;">${esc(s.label)}</div>
    </div>`).join('');

  const recsHtml = (data.recs || []).map(r => `
    <div style="background:#fff;border:1px solid #e7e3da;border-radius:16px;padding:20px;display:flex;gap:20px;align-items:flex-start;">
      <div style="width:40px;height:40px;border-radius:11px;background:${r.rank_bg};color:${r.rank_color};display:flex;align-items:center;justify-content:center;font-family:'IBM Plex Mono',monospace;font-weight:600;font-size:17px;flex:none;">${r.rank}</div>
      <div style="flex:1;min-width:0;">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:10px;">
          <span style="font-size:15px;font-weight:600;">${esc(r.skill)}</span>
          <span style="font-family:'IBM Plex Mono',monospace;font-size:9.5px;font-weight:600;color:${r.tag_color};background:${r.tag_bg};border-radius:5px;padding:2px 7px;">${esc(r.tag)}</span>
          ${!r.in_profile
            ? `<span style="font-family:'IBM Plex Mono',monospace;font-size:9px;font-weight:600;color:#b1493a;background:#f5e5e1;border:1px solid #e8c5bf;border-radius:5px;padding:2px 7px;">NOT IN PROFILE</span>`
            : `<span style="font-family:'IBM Plex Mono',monospace;font-size:9px;font-weight:600;color:#9a7c33;background:#f7edda;border:1px solid #ecddc0;border-radius:5px;padding:2px 7px;">+${r.gap_pts} PTS NEEDED</span>`}
        </div>
        ${r.jobs_requiring && r.jobs_requiring.length ? `
        <div style="background:#e7f0ea;border:1px solid #cfe2d6;border-radius:9px;padding:9px 12px;margin-bottom:10px;">
          <span style="font-family:'IBM Plex Mono',monospace;font-size:9px;letter-spacing:0.4px;color:#15604a;font-weight:600;display:block;margin-bottom:5px;">WHY IN DEMAND</span>
          <div style="font-size:12px;color:#1b3a28;line-height:1.55;">${r.jobs_requiring.map(t => esc(t)).join('<span style="color:#8bba9a;margin:0 4px;">·</span>')}</div>
        </div>` : `<div style="font-size:12px;color:#7a756a;line-height:1.5;margin-bottom:10px;">${esc(r.why)}</div>`}
        ${r.tip ? `<div style="background:#f7edda;border:1px solid #ecddc0;border-radius:9px;padding:9px 12px;font-size:12px;line-height:1.55;color:#5e4d22;">
          <span style="font-family:'IBM Plex Mono',monospace;font-size:9px;letter-spacing:0.4px;color:#9a7c33;font-weight:600;display:block;margin-bottom:4px;">WHAT TO LEARN</span>
          ${esc(r.tip)}
        </div>` : ''}
      </div>
      <div style="width:180px;flex:none;">
        <div style="display:flex;justify-content:space-between;font-family:'IBM Plex Mono',monospace;font-size:10px;color:#9a9488;margin-bottom:6px;">
          <span>NOW ${r.level}</span>
          <span style="color:#15604a;">TARGET ${r.target}</span>
        </div>
        <div style="position:relative;height:8px;background:#f0ece3;border-radius:6px;overflow:visible;">
          <div style="height:100%;border-radius:6px;background:#b9791f;width:${r.level_w}%;"></div>
          <div style="position:absolute;top:-2px;width:2px;height:12px;background:#15604a;border-radius:2px;left:${r.target_w}%;"></div>
        </div>
        <div style="font-family:'IBM Plex Mono',monospace;font-size:10px;color:#7a756a;margin-top:8px;text-align:right;">est. <span style="color:#15604a;font-weight:600;">+${r.gain}% avg fit</span></div>
      </div>
    </div>`).join('');

  // Company filter chips
  const companyChipsHtml = (data.available_companies || []).map(co => {
    const active = S.learnFilters.company_id === co.id;
    return `<div onclick="setLearnFilter('company_id', ${co.id})" style="cursor:pointer;display:flex;align-items:center;gap:6px;padding:5px 12px;border-radius:20px;font-size:11.5px;font-weight:${active ? '600' : '500'};background:${active ? co.color : '#fff'};color:${active ? '#fff' : '#55504a'};border:1px solid ${active ? co.color : '#e7e3da'};white-space:nowrap;transition:all .15s;">
      ${esc(co.name)}
    </div>`;
  }).join('');

  // Category filter chips
  const catChipsHtml = (data.available_categories || []).map(cat => {
    const active = S.learnFilters.category === cat;
    return `<div onclick="setLearnFilter('category', '${esc(cat)}')" style="cursor:pointer;padding:5px 12px;border-radius:20px;font-size:11.5px;font-weight:${active ? '600' : '500'};background:${active ? '#15604a' : '#fff'};color:${active ? '#fff' : '#55504a'};border:1px solid ${active ? '#15604a' : '#e7e3da'};white-space:nowrap;transition:all .15s;">${esc(cat)}</div>`;
  }).join('');

  const filterBar = `
    <div style="background:#fbfaf6;border:1px solid #f0ece3;border-radius:14px;padding:14px 16px;margin-bottom:18px;display:flex;flex-direction:column;gap:10px;">
      ${(data.available_companies || []).length > 1 ? `
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
        <span style="font-family:'IBM Plex Mono',monospace;font-size:10px;letter-spacing:0.5px;color:#9a9488;width:52px;flex:none;">COMPANY</span>
        <div onclick="setLearnFilter('company_id', null)" style="cursor:pointer;padding:5px 12px;border-radius:20px;font-size:11.5px;font-weight:${!S.learnFilters.company_id ? '600' : '500'};background:${!S.learnFilters.company_id ? '#1b1a17' : '#fff'};color:${!S.learnFilters.company_id ? '#fff' : '#55504a'};border:1px solid ${!S.learnFilters.company_id ? '#1b1a17' : '#e7e3da'};transition:all .15s;">All</div>
        ${companyChipsHtml}
      </div>` : ''}
      ${(data.available_categories || []).length > 0 ? `
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
        <span style="font-family:'IBM Plex Mono',monospace;font-size:10px;letter-spacing:0.5px;color:#9a9488;width:52px;flex:none;">DEPT</span>
        <div onclick="setLearnFilter('category', null)" style="cursor:pointer;padding:5px 12px;border-radius:20px;font-size:11.5px;font-weight:${!S.learnFilters.category ? '600' : '500'};background:${!S.learnFilters.category ? '#1b1a17' : '#fff'};color:${!S.learnFilters.category ? '#fff' : '#55504a'};border:1px solid ${!S.learnFilters.category ? '#1b1a17' : '#e7e3da'};transition:all .15s;">All</div>
        ${catChipsHtml}
      </div>` : ''}
    </div>`;

  setHTML('screen', `<div class="anim-in" style="padding:26px 28px 60px;">
    <div style="background:#1b1a17;border-radius:18px;padding:24px 26px;color:#f6f4ef;margin-bottom:22px;">
      <div style="display:flex;align-items:center;gap:9px;margin-bottom:12px;">
        <span style="width:22px;height:22px;border-radius:6px;background:#b9791f;display:flex;align-items:center;justify-content:center;font-size:12px;">✦</span>
        <span style="font-family:'IBM Plex Mono',monospace;font-size:10px;letter-spacing:0.6px;color:#c9a253;">AI ANALYSIS · ${S.learnFilters.company_id ? (data.available_companies||[]).find(c=>c.id===S.learnFilters.company_id)?.name?.toUpperCase() || 'COMPANY' : 'ACROSS YOUR WATCHLIST'}</span>
      </div>
      <div style="font-size:19px;font-weight:600;line-height:1.45;letter-spacing:-0.2px;max-width:760px;">${esc(data.headline)}</div>
      <div style="display:flex;gap:28px;margin-top:20px;">${statsHtml}</div>
    </div>

    ${filterBar}

    <div style="font-size:13px;font-weight:600;margin-bottom:4px;">All skill gaps — ranked by impact</div>
    <div style="font-size:12px;color:#7a756a;margin-bottom:16px;">Every skill that appears in matching job postings but is missing or underdeveloped in your profile.</div>

    <div style="display:flex;flex-direction:column;gap:14px;">
      ${recsHtml || '<div style="padding:40px;text-align:center;color:#9a9488;">Add and sync companies to get personalised recommendations.</div>'}
    </div>
  </div>`);
}

// ── PROFILE ───────────────────────────────────────────────────────────────────
async function renderProfile() {
  setTopbar('Profile', 'Manage your skills and preferences');
  const [p, suggestData] = await Promise.all([
    api('GET', '/profile'),
    api('GET', '/profile/suggestions').catch(() => ({ suggestions: [] })),
  ]);
  S.profile = p;

  const suggestions = suggestData.suggestions || [];
  const avgFit = S.stats.avg_fit || 0;

  const suggestHtml = suggestions.map(s =>
    `<div class="suggest-chip" onclick="addSuggestedSkill('${esc(s)}')">+ ${esc(s)}</div>`
  ).join('');

  const skillsHtml = `<div style="display:flex;flex-wrap:wrap;gap:8px;">${
    p.skills.map(s =>
      `<div style="display:inline-flex;align-items:center;gap:7px;background:#f3efe7;border:1px solid #e7e3da;border-radius:20px;padding:5px 8px 5px 13px;">
        <span style="font-size:12.5px;font-weight:500;">${esc(s.name)}</span>
        <div class="icon-btn danger" title="Remove" onclick="deleteSkill('${esc(s.name)}')" style="width:18px;height:18px;font-size:11px;padding:0;display:flex;align-items:center;justify-content:center;border-radius:50%;margin:0;">✕</div>
      </div>`
    ).join('')
  }</div>`;

  const resumeSection = `
    <label class="resume-drop" for="resume-file">
      <span style="width:34px;height:34px;border-radius:9px;background:#f3efe7;display:flex;align-items:center;justify-content:center;font-size:16px;color:#7a756a;">↑</span>
      <span style="font-size:12.5px;font-weight:600;color:#15604a;">Upload resume</span>
      <span style="font-family:'IBM Plex Mono',monospace;font-size:9.5px;color:#9a9488;">PDF · DOCX · UP TO 10MB</span>
      <input type="file" id="resume-file" accept=".pdf,.doc,.docx" style="display:none;" onchange="handleResume(this)"/>
    </label>
    <div id="resume-status" style="font-family:'IBM Plex Mono',monospace;font-size:10px;color:#7a756a;text-align:center;min-height:16px;margin-top:4px;"></div>`;

  const aiSummary = p.skills.length
    ? `You have ${p.skill_count} tracked skills. Your strongest areas are ${p.skills.slice(0,3).map(s=>s.name).join(', ')}. Keep growing and sync companies to see where you stand.`
    : 'Add your skills to start getting personalised fit scores and recommendations.';

  const FOCUS_CATEGORIES = [
    'Data & ML', 'Software Engineering', 'Product', 'Design',
    'Operations', 'Finance', 'Marketing & Growth', 'People & HR',
  ];
  const currentFocus = p.target_role || '';
  const focusChips = FOCUS_CATEGORIES.map(cat => {
    const active = cat === currentFocus;
    return `<div onclick="setTargetRole('${esc(cat)}')" style="cursor:pointer;padding:5px 11px;border-radius:20px;font-size:11.5px;font-weight:${active ? '600' : '500'};background:${active ? '#15604a' : '#f0ece3'};color:${active ? '#fff' : '#55504a'};border:1px solid ${active ? '#15604a' : '#e7e3da'};transition:all .15s;">${esc(cat)}</div>`;
  }).join('');
  const focusClearLink = currentFocus
    ? `<span style="font-size:11px;color:#9a9488;cursor:pointer;text-decoration:underline;margin-top:6px;display:inline-block;" onclick="setTargetRole('')">Clear focus</span>`
    : '';
  const focusSection = `
    <div style="background:#fff;border:1px solid #e7e3da;border-radius:16px;padding:18px;">
      <div style="font-size:13.5px;font-weight:600;margin-bottom:3px;">Career focus</div>
      <div style="font-size:11.5px;color:#7a756a;margin-bottom:14px;">Fit scores, skill gaps and Learn Next filter to this role type across all companies.</div>
      <div style="display:flex;flex-wrap:wrap;gap:7px;">${focusChips}</div>
      ${focusClearLink}
    </div>`;

  setHTML('screen', `<div class="anim-in" style="padding:26px 28px 60px;">
    <div style="display:grid;grid-template-columns:1fr 320px;gap:18px;align-items:start;">

      <div style="background:#fff;border:1px solid #e7e3da;border-radius:16px;padding:22px;">
        <div style="display:flex;align-items:baseline;justify-content:space-between;margin-bottom:6px;">
          <div style="font-size:14px;font-weight:600;">Your skills</div>
          <div style="font-family:'IBM Plex Mono',monospace;font-size:10px;color:#9a9488;">${p.skill_count} KEYWORDS</div>
        </div>
        <div style="font-size:12px;color:#7a756a;margin-bottom:16px;">Skills are matched as keywords against job postings — exactly how ATS systems work. Add a skill and it counts.</div>

        <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;">
          <input id="skill-input" class="skill-input" placeholder="Add a skill — e.g. Databricks, R, Terraform" onkeydown="if(event.key==='Enter')addNewSkill()"/>
          <button class="btn-add-skill" onclick="addNewSkill()">+ Add</button>
        </div>

        <div style="display:flex;flex-wrap:wrap;align-items:center;gap:7px;margin-bottom:20px;">
          <span style="font-family:'IBM Plex Mono',monospace;font-size:10px;letter-spacing:0.5px;color:#9a9488;margin-right:2px;">SUGGESTED</span>
          ${suggestHtml}
        </div>

        <div style="margin-top:4px;">
          ${skillsHtml || '<div style="color:#9a9488;font-size:12px;padding:10px 0;">No skills yet. Add one above.</div>'}
        </div>
      </div>

      <div style="display:flex;flex-direction:column;gap:18px;">
        <div style="background:#fff;border:1px solid #e7e3da;border-radius:16px;padding:22px;">
          <div style="display:flex;align-items:center;gap:13px;">
            <div style="width:48px;height:48px;border-radius:50%;background:#1b1a17;color:#fff;display:flex;align-items:center;justify-content:center;font-family:'IBM Plex Mono',monospace;font-weight:600;font-size:17px;">${esc(p.initials || initials(p.name))}</div>
            <div style="flex:1;min-width:0;">
              <div id="profile-name-display" style="display:flex;align-items:center;gap:8px;">
                <span style="font-size:15px;font-weight:600;">${esc(p.name)}</span>
                <span class="icon-btn" title="Edit name & role" onclick="editProfileMeta()" style="font-size:11px;opacity:0.5;">✎</span>
              </div>
              <div id="profile-role-display" style="font-size:12px;color:#7a756a;margin-top:2px;">${esc(p.role)}</div>
              <div id="profile-meta-edit" style="display:none;margin-top:8px;flex-direction:column;gap:7px;">
                <input id="profile-name-input" class="text-input" value="${esc(p.name)}" placeholder="Your name" style="font-size:13px;padding:6px 10px;"/>
                <input id="profile-role-input" class="text-input" value="${esc(p.role)}" placeholder="Your role" style="font-size:13px;padding:6px 10px;"/>
                <div style="display:flex;gap:7px;">
                  <button class="btn-add-skill" onclick="saveProfileMeta()" style="flex:1;">Save</button>
                  <button class="btn-back" onclick="cancelProfileMeta()">Cancel</button>
                </div>
              </div>
            </div>
          </div>
          <div style="display:flex;gap:12px;margin-top:20px;">
            <div style="flex:1;background:#e7f0ea;border-radius:12px;padding:14px;">
              <div style="font-family:'IBM Plex Mono',monospace;font-size:26px;font-weight:600;color:#15604a;">${avgFit}%</div>
              <div style="font-size:10.5px;color:#1d4d3c;margin-top:3px;">avg watchlist fit</div>
            </div>
            <div style="flex:1;background:#f3efe7;border-radius:12px;padding:14px;">
              <div style="font-family:'IBM Plex Mono',monospace;font-size:26px;font-weight:600;">${p.skill_count}</div>
              <div style="font-size:10.5px;color:#7a756a;margin-top:3px;">tracked skills</div>
            </div>
          </div>
        </div>

        <div style="background:#f7edda;border:1px solid #ecddc0;border-radius:16px;padding:18px;">
          <div style="font-family:'IBM Plex Mono',monospace;font-size:9.5px;letter-spacing:0.6px;color:#9a7c33;margin-bottom:8px;">✦ AI SUMMARY</div>
          <div style="font-size:13px;line-height:1.55;color:#5e4d22;">${aiSummary}</div>
        </div>

        ${focusSection}

        <div style="background:#fff;border:1px solid #e7e3da;border-radius:16px;padding:18px;">
          <div style="font-size:13.5px;font-weight:600;margin-bottom:3px;">Resume</div>
          <div style="font-size:11.5px;color:#7a756a;margin-bottom:14px;">Upload your resume so tailored drafts start from your real experience.</div>
          ${resumeSection}
        </div>
      </div>
    </div>
  </div>`);
}

function editProfileMeta() {
  const nameDisplay = document.getElementById('profile-name-display');
  const roleDisplay = document.getElementById('profile-role-display');
  const editPanel  = document.getElementById('profile-meta-edit');
  if (!nameDisplay || !editPanel) return;
  nameDisplay.style.display = 'none';
  roleDisplay.style.display = 'none';
  editPanel.style.display   = 'flex';
  document.getElementById('profile-name-input')?.focus();
}

function cancelProfileMeta() {
  const nameDisplay = document.getElementById('profile-name-display');
  const roleDisplay = document.getElementById('profile-role-display');
  const editPanel  = document.getElementById('profile-meta-edit');
  if (!nameDisplay || !editPanel) return;
  nameDisplay.style.display = '';
  roleDisplay.style.display = '';
  editPanel.style.display   = 'none';
}

async function saveProfileMeta() {
  const name = (document.getElementById('profile-name-input')?.value || '').trim();
  const role = (document.getElementById('profile-role-input')?.value || '').trim();
  if (!name) return;
  await api('PUT', '/profile', { name, role });
  S.profile = await api('GET', '/profile');
  S.stats   = await api('GET', '/stats');
  renderProfileFooter();
  await renderProfile();
}

async function addNewSkill() {
  const input = document.getElementById('skill-input');
  const name = (input?.value || '').trim();
  if (!name) return;
  await api('POST', '/profile/skill', { name, level: 60 });
  input.value = '';
  await renderProfile();
}

async function addSuggestedSkill(name) {
  await api('POST', '/profile/skill', { name, level: 50 });
  await renderProfile();
}

async function adjustSkill(name, delta) {
  const p = await api('GET', '/profile');
  const skill = p.skills.find(s => s.name === name);
  if (!skill) return;
  const newLevel = Math.max(0, Math.min(100, skill.level + delta));
  await api('POST', '/profile/skill', { name, level: newLevel });
  await renderProfile();
}

async function deleteSkill(name) {
  await api('DELETE', `/profile/skill/${encodeURIComponent(name)}`);
  await renderProfile();
}

async function handleResume(input) {
  if (!input.files[0]) return;
  const file = input.files[0];
  const label = document.getElementById('resume-status');
  if (label) label.textContent = 'Uploading…';
  try {
    const form = new FormData();
    form.append('file', file);
    const r = await fetch('/api/profile/resume', { method: 'POST', body: form });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(err.detail || r.statusText);
    }
    const data = await r.json();
    if (label) label.textContent = data.message || `Added ${data.skills_added} skills`;
    // Refresh cached stats so overview shows updated avgFit on next visit
    try { S.stats = await api('GET', '/stats'); } catch (_) {}
    await renderProfile();
  } catch (e) {
    if (label) label.textContent = 'Upload failed: ' + e.message;
    alert('Resume upload failed: ' + e.message);
  }
  input.value = '';
}

// ── ADD COMPANY OVERLAY ───────────────────────────────────────────────────────
function openAddOverlay() {
  S.addPhase = 'input';
  S.addInput = '';
  S.addResult = null;
  document.getElementById('add-overlay').style.display = 'flex';
  renderAddBody();
}

function closeAddOverlay() {
  document.getElementById('add-overlay').style.display = 'none';
}

function renderAddBody() {
  const examples = ['Picnic', 'Zalando', 'Booking.com', 'ASML'];

  if (S.addPhase === 'input') {
    setHTML('add-body', `
      <div style="font-family:'IBM Plex Mono',monospace;font-size:9.5px;letter-spacing:0.6px;color:#9a9488;margin-bottom:8px;">COMPANY NAME</div>
      <div style="display:flex;gap:9px;align-items:center;">
        <input id="add-input" class="text-input" placeholder="Company name or career page URL" value="${esc(S.addInput)}"
          onkeydown="if(event.key==='Enter')startAddScan()" oninput="S.addInput=this.value"/>
        <button class="btn-add" onclick="startAddScan()">Scan</button>
      </div>
      <div style="display:flex;flex-wrap:wrap;align-items:center;gap:7px;margin-top:14px;">
        <span style="font-family:'IBM Plex Mono',monospace;font-size:10px;color:#9a9488;margin-right:2px;">TRY</span>
        ${examples.map(e => `<div class="example-pill" onclick="document.getElementById('add-input').value='${e}';S.addInput='${e}';">${e}</div>`).join('')}
      </div>
      <div style="display:flex;gap:10px;align-items:flex-start;background:#fff;border:1px solid #e7e3da;border-radius:12px;padding:14px;margin-top:20px;">
        <span style="color:#b9791f;font-size:13px;flex:none;">✦</span>
        <div style="font-size:11.5px;line-height:1.55;color:#55504a;">Paste a company name <em>or</em> their direct career page URL (e.g. <code>careers.zalando.com</code> or a Greenhouse/Lever link). Career Fit Check scrapes live job posts, extracts required skills, and scores each role against your profile.</div>
      </div>
    `);
    setTimeout(() => document.getElementById('add-input')?.focus(), 50);

  } else if (S.addPhase === 'scanning') {
    setHTML('add-body', `
      <div style="text-align:center;padding:34px 0;">
        <div class="spinner" style="margin:0 auto 18px;"></div>
        <div style="font-size:14.5px;font-weight:600;">Scanning job posts…</div>
        <div style="font-size:12px;color:#7a756a;margin-top:6px;">Reading roles, detecting required skills and hiring trend.</div>
      </div>
    `);

  } else if (S.addPhase === 'review' && S.addResult) {
    const c = S.addResult;
    const topSkills = (c.skills || []).slice(0, 6).map(k =>
      `<span style="font-size:11px;font-weight:500;color:${k.you_have ? '#15604a' : '#55504a'};background:#f6f4ef;border:1px solid #ece7dd;border-radius:6px;padding:3px 9px;">${esc(k.name)}</span>`
    ).join('');
    const sampleRoles = (c.roles || []).slice(0, 4).map(r =>
      `<div style="display:flex;align-items:center;gap:12px;padding:9px 0;border-top:1px solid #f0ece3;">
        <div style="flex:1;min-width:0;">
          <div style="font-size:12.5px;font-weight:600;">${esc(r.title)}</div>
          <div style="font-size:10.5px;color:#7a756a;margin-top:1px;">${esc(r.location)}</div>
        </div>
        <div style="font-family:'IBM Plex Mono',monospace;font-size:12px;font-weight:600;color:${r.match_color};flex:none;">${r.match}%</div>
      </div>`
    ).join('');

    setHTML('add-body', `
      <div style="display:flex;align-items:center;gap:7px;font-family:'IBM Plex Mono',monospace;font-size:9.5px;color:#15604a;margin-bottom:12px;">
        <span style="width:7px;height:7px;border-radius:50%;background:#15604a;"></span>SCAN COMPLETE · REVIEW &amp; CONFIRM
      </div>
      <div style="background:#fff;border:1px solid #e7e3da;border-radius:14px;padding:18px;">
        <div style="display:flex;align-items:center;gap:13px;">
          ${colorAvatar(c.color, c.name.slice(0,2).toUpperCase(), 46, 12, 18)}
          <div style="flex:1;min-width:0;">
            <div style="font-size:16px;font-weight:600;letter-spacing:-0.2px;">${esc(c.name)}</div>
            <div style="font-size:11.5px;color:#7a756a;margin-top:2px;">${esc(c.sector)}${c.hq ? ' · ' + c.hq : ''}</div>
          </div>
        </div>
        <div style="display:flex;gap:10px;margin-top:16px;">
          <div style="flex:1;background:#f6f4ef;border-radius:10px;padding:11px 13px;">
            <div style="font-family:'IBM Plex Mono',monospace;font-size:8.5px;letter-spacing:0.5px;color:#9a9488;">OPEN ROLES</div>
            <div style="display:flex;align-items:baseline;gap:6px;margin-top:4px;">
              <span style="font-family:'IBM Plex Mono',monospace;font-size:19px;font-weight:600;">${c.open_roles}</span>
              <span style="font-size:10px;font-weight:600;color:${c.vel_color};">${esc(c.vel_label)}</span>
            </div>
          </div>
          <div style="flex:1;background:#f6f4ef;border-radius:10px;padding:11px 13px;">
            <div style="font-family:'IBM Plex Mono',monospace;font-size:8.5px;letter-spacing:0.5px;color:#9a9488;">YOUR FIT</div>
            <div style="font-family:'IBM Plex Mono',monospace;font-size:19px;font-weight:600;color:${c.fit_color};margin-top:4px;">${c.fit}%</div>
          </div>
        </div>
        ${topSkills ? `<div style="font-family:'IBM Plex Mono',monospace;font-size:8.5px;letter-spacing:0.5px;color:#9a9488;margin:16px 0 8px;">TOP SKILLS DETECTED</div><div style="display:flex;flex-wrap:wrap;gap:6px;">${topSkills}</div>` : ''}
        ${sampleRoles ? `<div style="font-family:'IBM Plex Mono',monospace;font-size:8.5px;letter-spacing:0.5px;color:#9a9488;margin:16px 0 8px;">SAMPLE ROLES</div><div style="display:flex;flex-direction:column;">${sampleRoles}</div>` : ''}
      </div>
      <div style="display:flex;gap:10px;margin-top:16px;">
        <div class="btn-back" onclick="S.addPhase='input';renderAddBody()">← Back</div>
        <button class="btn-add" style="flex:1;border-radius:10px;padding:12px;" onclick="confirmAdd()">
          Add ${esc(c.name)} to watchlist
        </button>
      </div>
    `);
  }
}

function _isUrl(s) {
  return /^https?:\/\/|^www\.|[a-z0-9-]+\.(com|io|co|net|org|de|nl|uk|eu)(\/|$)/i.test(s.trim());
}

function _nameFromUrl(url) {
  try {
    const u = new URL(url.startsWith('http') ? url : 'https://' + url);
    const host = u.hostname.replace(/^www\./, '');
    // Greenhouse: boards.greenhouse.io/{slug} or greenhouse.io/{slug}
    if (host.includes('greenhouse.io')) {
      const p = u.pathname.split('/').filter(Boolean);
      if (p.length) return p[0].split('-').map(w => w[0].toUpperCase() + w.slice(1)).join(' ');
    }
    // Lever: jobs.lever.co/{slug}
    if (host.includes('lever.co')) {
      const p = u.pathname.split('/').filter(Boolean);
      if (p.length) return p[0].split('-').map(w => w[0].toUpperCase() + w.slice(1)).join(' ');
    }
    // Strip common career subdomains (EN + international equivalents)
    // e.g. careers.zalando.com, jobs.google.com, karriere.miele.de,
    //      vacatures.ing.com, werkenbij.ah.nl → company name from SLD
    const stripped = host.replace(
      /^(careers?|jobs?|apply|work|career|karriere|stellenangebote|vacatures?|emplois?|vacantes?|carriere|werkenbij|joinen|talent|join|recrutement)\./i,
      ''
    );
    const parts = stripped.split('.');
    // For country-code TLDs (e.g. miele.de) take the SLD, not the TLD
    const domain = parts.length >= 2 ? parts[parts.length - 2] : parts[0];
    return domain.charAt(0).toUpperCase() + domain.slice(1);
  } catch { return ''; }
}

async function startAddScan() {
  const raw = (document.getElementById('add-input')?.value || S.addInput || '').trim();
  if (!raw) return;

  let name, careerUrl;
  if (_isUrl(raw)) {
    const fullUrl = raw.startsWith('http') ? raw : 'https://' + raw;
    name = _nameFromUrl(fullUrl) || raw;
    careerUrl = fullUrl;
  } else {
    name = raw;
    careerUrl = null;
  }

  S.addInput = name;
  S.addPhase = 'scanning';
  renderAddBody();

  try {
    // Create company (include career_url if user pasted one)
    const payload = careerUrl ? { name, career_url: careerUrl } : { name };
    const created = await api('POST', '/companies', payload);
    // Sync it
    await api('POST', `/companies/${created.id}/sync`);
    // Fetch full detail for review
    const detail = await api('GET', `/companies/${created.id}`);
    S.addResult = detail;
    S.addPhase = 'review';
    renderAddBody();
  } catch (e) {
    // If 409, company exists — fetch it and show review
    if (e.message && e.message.includes('already exists')) {
      try {
        const companies = await api('GET', '/companies');
        const existing = companies.find(c => c.name.toLowerCase() === name.toLowerCase());
        if (existing) {
          const detail = await api('GET', `/companies/${existing.id}`);
          S.addResult = detail;
          S.addPhase = 'review';
          renderAddBody();
          return;
        }
      } catch {}
    }
    S.addPhase = 'input';
    renderAddBody();
    alert('Could not add company: ' + e.message);
  }
}

async function confirmAdd() {
  closeAddOverlay();
  S.companies = await api('GET', '/companies');
  const added = S.addResult;
  S.addResult = null;
  if (added) {
    navigate('deep', { companyId: added.id });
  } else {
    await renderOverview();
  }
}

// ── TAILOR OVERLAY ────────────────────────────────────────────────────────────
const T = {
  jobId: null,
  tone: 'Professional',
  length: 'Standard',
  leadWith: [],        // current chip selection
  availableLeadWith: [], // chips offered from API
  tab: 'resume',
  data: null,          // last API response
  loading: false,
};

// ── ATS SCORER ────────────────────────────────────────────────────────────────
const ATS = { jobId: null, loading: false, data: null };

function openATS(jobId, title) {
  ATS.jobId = jobId;
  ATS.loading = false;
  ATS.data = null;
  document.getElementById('ats-title').textContent = title;
  setHTML('ats-score-badge', '');
  document.getElementById('ats-overlay').style.display = 'flex';
  _renderATSBody();
}

function _closeATS() {
  document.getElementById('ats-overlay').style.display = 'none';
}

function _renderATSBody() {
  if (ATS.loading) {
    setHTML('ats-body', `
      <div style="padding:48px;text-align:center;">
        <div class="spinner" style="margin:0 auto 16px;"></div>
        <div style="font-size:13.5px;font-weight:600;">Analysing resume keywords…</div>
        <div style="font-size:12px;color:#7a756a;margin-top:6px;">Extracting keywords from your resume and matching against the job.</div>
      </div>`);
    return;
  }

  if (!ATS.data) {
    setHTML('ats-body', `
      <div style="margin-bottom:14px;">
        <div style="font-size:13.5px;font-weight:600;margin-bottom:5px;">Paste your resume text</div>
        <div style="font-size:12px;color:#7a756a;margin-bottom:12px;">Copy all the text from your resume and paste it below. We'll extract keywords and check which ones the ATS would find — and which are missing.</div>
        <textarea id="ats-resume-text" style="width:100%;min-height:180px;border:1px solid #e7e3da;border-radius:12px;padding:14px;font-size:12.5px;font-family:'IBM Plex Sans',sans-serif;background:#fff;resize:vertical;box-sizing:border-box;outline:none;line-height:1.5;" placeholder="Paste your resume here…"></textarea>
      </div>
      <button class="btn-primary" onclick="_runATSScore()" style="width:100%;padding:12px;">Analyse ATS Score →</button>`);
    return;
  }

  if (ATS.data.error) {
    setHTML('ats-body', `<div style="padding:24px;text-align:center;color:#b1493a;">${esc(ATS.data.error)}<br><br><button class="btn-back" onclick="ATS.data=null;_renderATSBody();">← Try again</button></div>`);
    return;
  }

  const d = ATS.data;
  const scoreColor = d.score >= 70 ? '#15604a' : d.score >= 45 ? '#b9791f' : '#b1493a';
  const scoreBg   = d.score >= 70 ? '#e7f0ea' : d.score >= 45 ? '#f7edda' : '#f5e5e1';
  const scoreMsg  = d.score >= 70 ? 'Strong ATS match — your resume is well-aligned.' : d.score >= 45 ? 'Partial match — adding the missing keywords will significantly boost your score.' : 'Weak match — the resume needs keyword alignment before applying.';

  const chipGreen = s => `<span style="display:inline-flex;align-items:center;gap:4px;background:#e7f0ea;border:1px solid #cfe2d6;border-radius:20px;padding:3px 11px;font-size:11.5px;color:#15604a;font-weight:500;"><span>✓</span>${esc(s)}</span>`;
  const chipRed   = s => `<span style="display:inline-flex;align-items:center;gap:4px;background:#f5e5e1;border:1px solid #e8c5bf;border-radius:20px;padding:3px 11px;font-size:11.5px;color:#b1493a;font-weight:500;"><span>✗</span>${esc(s)}</span>`;
  const chipAmber = s => `<span style="display:inline-flex;align-items:center;gap:4px;background:#f7edda;border:1px solid #ecddc0;border-radius:20px;padding:3px 11px;font-size:11.5px;color:#9a7c33;font-weight:500;"><span>~</span>${esc(s)}</span>`;

  const missingBlock = d.required_missing.length ? `
    <div style="background:#f5e5e1;border:1px solid #e8c5bf;border-radius:12px;padding:16px;margin-bottom:16px;">
      <div style="font-family:'IBM Plex Mono',monospace;font-size:9.5px;letter-spacing:0.5px;color:#b1493a;font-weight:600;margin-bottom:10px;">ADD THESE EXACT KEYWORDS TO YOUR RESUME</div>
      <div style="display:flex;flex-wrap:wrap;gap:7px;">${d.required_missing.map(s => `<span style="background:#fff;border:1px solid #e8c5bf;border-radius:7px;padding:4px 10px;font-family:'IBM Plex Mono',monospace;font-size:11px;color:#b1493a;">${esc(s)}</span>`).join('')}</div>
    </div>` : `<div style="background:#e7f0ea;border:1px solid #cfe2d6;border-radius:12px;padding:14px;margin-bottom:16px;font-size:12.5px;color:#15604a;font-weight:500;">✓ All required keywords found in your resume.</div>`;

  setHTML('ats-score-badge', `<span style="color:${scoreColor};">${d.score}%</span>`);

  setHTML('ats-body', `
    <div style="display:flex;align-items:center;gap:20px;background:${scoreBg};border-radius:14px;padding:20px 22px;margin-bottom:20px;">
      <div style="font-family:'IBM Plex Mono',monospace;font-size:54px;font-weight:700;color:${scoreColor};line-height:1;flex:none;">${d.score}%</div>
      <div>
        <div style="font-size:14.5px;font-weight:600;margin-bottom:5px;">${scoreMsg}</div>
        <div style="font-size:12px;color:#55504a;">Your resume contains <strong>${d.required_matched.length}/${d.total_required}</strong> required keywords${d.total_preferred ? ` and <strong>${d.preferred_matched.length}/${d.total_preferred}</strong> preferred keywords` : ''}. ${d.resume_keywords_detected} total keywords detected in the resume.</div>
      </div>
    </div>

    ${missingBlock}

    ${d.required_matched.length || d.required_missing.length ? `
    <div style="margin-bottom:16px;">
      <div style="font-family:'IBM Plex Mono',monospace;font-size:9.5px;letter-spacing:0.5px;color:#9a9488;font-weight:600;margin-bottom:9px;">REQUIRED KEYWORDS — ${d.required_matched.length} of ${d.total_required} matched</div>
      <div style="display:flex;flex-wrap:wrap;gap:6px;">${[...d.required_matched.map(chipGreen), ...d.required_missing.map(chipRed)].join(' ')}</div>
    </div>` : ''}

    ${d.preferred_matched.length || d.preferred_missing.length ? `
    <div style="margin-bottom:16px;">
      <div style="font-family:'IBM Plex Mono',monospace;font-size:9.5px;letter-spacing:0.5px;color:#9a9488;font-weight:600;margin-bottom:9px;">PREFERRED KEYWORDS — ${d.preferred_matched.length} of ${d.total_preferred} matched</div>
      <div style="display:flex;flex-wrap:wrap;gap:6px;">${[...d.preferred_matched.map(chipGreen), ...d.preferred_missing.map(chipAmber)].join(' ')}</div>
    </div>` : ''}

    <div style="text-align:center;margin-top:8px;">
      <button class="btn-back" onclick="ATS.data=null;_renderATSBody();">← Score a different resume</button>
    </div>`);
}

async function _runATSScore() {
  const resumeText = (document.getElementById('ats-resume-text')?.value || '').trim();
  if (!resumeText) { alert('Please paste your resume text first.'); return; }
  ATS.loading = true;
  _renderATSBody();
  try {
    ATS.data = await api('POST', '/ats-score', { job_id: ATS.jobId, resume_text: resumeText });
  } catch (e) {
    ATS.data = { error: e.message };
  } finally {
    ATS.loading = false;
    _renderATSBody();
  }
}

// ── TAILOR ────────────────────────────────────────────────────────────────────
function openTailor(jobId, title, company) {
  T.jobId = jobId;
  T.tone = 'Professional';
  T.length = 'Standard';
  T.leadWith = [];
  T.tab = 'resume';
  T.data = null;

  document.getElementById('tailor-title').textContent = title;
  document.getElementById('tailor-sub').textContent = company + ' · Resume & Cover Letter';
  setHTML('tailor-avatar', '');
  setHTML('tailor-fit', '');
  document.getElementById('tailor-overlay').style.display = 'flex';
  _renderTailorBody();
  _fetchTailor();
}

function _closeTailor() {
  document.getElementById('tailor-overlay').style.display = 'none';
}

async function _fetchTailor() {
  if (T.loading) return;
  T.loading = true;
  _renderTailorBody();
  try {
    const data = await api('POST', '/tailor', {
      job_id: T.jobId,
      tone: T.tone,
      length: T.length,
      lead_with: T.leadWith,
    });
    T.data = data;
    T.availableLeadWith = data.lead_with || [];
    if (!T.leadWith.length) T.leadWith = [...T.availableLeadWith];

    // Update overlay header with company color + fit
    const fitColor = data.fit >= 70 ? '#15604a' : data.fit >= 45 ? '#b9791f' : '#b1493a';
    setHTML('tailor-avatar', colorAvatar(data.company_color || '#15604a', data.company_name.slice(0,2).toUpperCase(), 34, 9, 13));
    setHTML('tailor-fit', `<span style="color:${fitColor};">${data.fit}%</span>`);
  } catch (e) {
    T.data = { error: e.message };
  } finally {
    T.loading = false;
    _renderTailorBody();
  }
}

function _renderTailorBody() {
  if (T.loading) {
    setHTML('tailor-body', `
      <div style="padding:48px;text-align:center;">
        <div class="spinner" style="margin:0 auto 16px;"></div>
        <div style="font-size:13.5px;font-weight:600;">Generating with Gemini…</div>
        <div style="font-size:12px;color:#7a756a;margin-top:6px;">Tailoring your resume and cover letter for this role.</div>
      </div>`);
    return;
  }

  if (!T.data) {
    setHTML('tailor-body', `<div style="padding:48px;text-align:center;color:#9a9488;">Press Generate to start.</div>`);
    return;
  }

  if (T.data.error) {
    setHTML('tailor-body', `
      <div style="padding:48px;text-align:center;color:#b1493a;">
        <div style="font-size:18px;margin-bottom:10px;">⚠</div>
        <div style="font-size:13px;">${esc(T.data.error)}</div>
        <button class="btn-primary" style="margin-top:18px;" onclick="_fetchTailor()">Retry</button>
      </div>`);
    return;
  }

  const tones = ['Professional', 'Confident', 'Concise'];
  const lengths = ['Brief', 'Standard', 'Detailed'];

  const toneHtml = `<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
    <span style="font-family:'IBM Plex Mono',monospace;font-size:9.5px;color:#9a9488;margin-right:2px;">TONE</span>
    <div class="tab-group">${tones.map(t =>
      `<div class="tab-opt${T.tone === t ? ' active' : ''}" onclick="_setTone('${t}')">${t}</div>`
    ).join('')}</div>
    <span style="font-family:'IBM Plex Mono',monospace;font-size:9.5px;color:#9a9488;margin-left:8px;margin-right:2px;">LENGTH</span>
    <div class="tab-group">${lengths.map(l =>
      `<div class="tab-opt${T.length === l ? ' active' : ''}" onclick="_setLength('${l}')">${l}</div>`
    ).join('')}</div>
  </div>`;

  const leadChips = (T.data.required_skills || []).slice(0, 8).map(s => {
    const on = T.leadWith.includes(s);
    return `<div class="${on ? 'suggest-chip' : 'suggest-chip'}"
      onclick="_toggleLead('${esc(s)}')"
      style="border-color:${on ? '#15604a' : '#d6cfc2'};color:${on ? '#15604a' : '#55504a'};${on ? 'background:#e7f0ea;' : ''}">
      ${on ? '✓ ' : '+ '}${esc(s)}
    </div>`;
  }).join('');

  const content = T.tab === 'resume' ? T.data.resume : T.data.cover_letter;
  const contentHtml = content
    ? content.split('\n').map(line => {
        const trimmed = line.trim();
        if (!trimmed) return '<div style="height:10px;"></div>';
        if (trimmed.startsWith('•')) return `<div style="display:flex;gap:10px;margin-bottom:6px;"><span style="flex:none;color:#15604a;">•</span><span style="flex:1;">${esc(trimmed.slice(1).trim())}</span></div>`;
        if (trimmed === trimmed.toUpperCase() && trimmed.length > 3) return `<div style="font-family:'IBM Plex Mono',monospace;font-size:10px;letter-spacing:0.6px;color:#9a9488;margin:14px 0 8px;">${esc(trimmed)}</div>`;
        return `<div style="margin-bottom:4px;line-height:1.6;">${esc(trimmed)}</div>`;
      }).join('')
    : '<div style="color:#9a9488;font-size:12px;">No content generated.</div>';

  setHTML('tailor-body', `
    <div style="padding:18px 20px;border-bottom:1px solid #e7e3da;background:#fff;">
      ${toneHtml}
      ${leadChips ? `<div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:12px;align-items:center;">
        <span style="font-family:'IBM Plex Mono',monospace;font-size:9.5px;color:#9a9488;margin-right:2px;">LEAD WITH</span>
        ${leadChips}
      </div>` : ''}
    </div>

    <div style="display:flex;gap:0;border-bottom:1px solid #e7e3da;background:#fff;">
      ${['resume','cover_letter'].map(tab => {
        const label = tab === 'resume' ? 'Resume' : 'Cover Letter';
        const active = T.tab === tab;
        return `<div onclick="_setTab('${tab}')"
          style="padding:11px 18px;font-size:13px;font-weight:600;cursor:pointer;
          border-bottom:2px solid ${active ? '#15604a' : 'transparent'};
          color:${active ? '#15604a' : '#7a756a'};transition:color 0.1s;">
          ${label}
        </div>`;
      }).join('')}
    </div>

    <div style="padding:22px 24px;">
      <div style="background:#fff;border:1px solid #e7e3da;border-radius:14px;padding:22px 26px;font-size:13px;line-height:1.65;color:#1b1a17;min-height:200px;">
        ${contentHtml}
      </div>
      <div style="display:flex;gap:10px;margin-top:14px;justify-content:flex-end;">
        <button class="btn-back" onclick="_fetchTailor()">↻ Regenerate</button>
        <button class="btn-primary" onclick="_copyTailor()">
          <svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
          Copy to clipboard
        </button>
      </div>
    </div>`);
}

function _setTone(t) { T.tone = t; _fetchTailor(); }
function _setLength(l) { T.length = l; _fetchTailor(); }

function _setTab(tab) {
  T.tab = tab;
  _renderTailorBody();
}

function _toggleLead(skill) {
  const idx = T.leadWith.indexOf(skill);
  if (idx >= 0) T.leadWith.splice(idx, 1);
  else T.leadWith.push(skill);
  _fetchTailor();
}

async function _copyTailor() {
  const content = T.tab === 'resume' ? T.data?.resume : T.data?.cover_letter;
  if (!content) return;
  try {
    await navigator.clipboard.writeText(content);
    const btn = document.querySelector('#tailor-body .btn-primary');
    if (btn) { btn.textContent = '✓ Copied!'; setTimeout(() => btn.innerHTML = '<svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg> Copy to clipboard', 2000); }
  } catch {
    alert('Copy failed — please select and copy the text manually.');
  }
}

// ── SCREEN ROUTER ─────────────────────────────────────────────────────────────
async function renderScreen() {
  document.getElementById('scroll-area').scrollTop = 0;
  setHTML('screen', '<div style="padding:60px;text-align:center;"><div class="spinner" style="margin:0 auto;"></div></div>');
  try {
    if (S.screen === 'overview') await renderOverview();
    else if (S.screen === 'deep') await renderDeepDive();
    else if (S.screen === 'compare') await renderCompare();
    else if (S.screen === 'learn') await renderLearn();
    else if (S.screen === 'profile') await renderProfile();
    else if (S.screen === 'projects') await renderProjects();
    else if (S.screen === 'applications') await renderApplications();
  } catch (e) {
    console.error(e);
    setHTML('screen', `<div style="padding:40px;text-align:center;color:#b1493a;">
      <div style="font-size:20px;margin-bottom:10px;">⚠</div>
      <div style="font-size:13px;">${esc(e.message)}</div>
    </div>`);
  }
}

// ── PROJECTS ──────────────────────────────────────────────────────────────────
async function renderProjects() {
  setTopbar('Projects', 'GitHub portfolio intelligence');
  setSyncLabel('LOADING…');
  let data;
  try {
    data = await api('GET', '/github/repos');
  } catch (e) {
    data = { connected: false };
  }
  setSyncLabel('READY');

  if (!data.connected) {
    _renderProjectsDisconnected();
    return;
  }
  _renderProjectsConnected(data);
}

function _renderProjectsDisconnected() {
  setHTML('screen', `<div class="anim-in" style="padding:26px 28px 60px;">
    <div style="max-width:520px;margin:40px auto;">
      <div style="background:#fff;border:1px solid #e7e3da;border-radius:18px;padding:32px;text-align:center;">
        <div style="width:52px;height:52px;border-radius:14px;background:#1b1a17;color:#fff;display:flex;align-items:center;justify-content:center;margin:0 auto 18px;font-size:22px;">⎇</div>
        <div style="font-size:18px;font-weight:600;letter-spacing:-0.2px;margin-bottom:8px;">Connect your GitHub</div>
        <div style="font-size:13px;color:#7a756a;line-height:1.6;max-width:380px;margin:0 auto 24px;">Career Fit Check scans your public repos, detects your portfolio skills, calculates market fit per project, and suggests what to build next.</div>
        <div style="display:flex;align-items:center;gap:9px;max-width:380px;margin:0 auto;">
          <input id="gh-input" class="text-input" placeholder="Your GitHub username" style="flex:1;"
            onkeydown="if(event.key==='Enter')connectGitHub()"/>
          <button class="btn-add" onclick="connectGitHub()">Scan</button>
        </div>
        <div style="margin-top:16px;font-family:'IBM Plex Mono',monospace;font-size:10px;color:#9a9488;">PUBLIC REPOS ONLY · NO TOKEN REQUIRED</div>
      </div>
    </div>
  </div>`);
  setTimeout(() => document.getElementById('gh-input')?.focus(), 50);
}

async function connectGitHub() {
  const username = (document.getElementById('gh-input')?.value || '').trim();
  if (!username) return;

  setHTML('screen', `<div class="anim-in" style="padding:60px;text-align:center;">
    <div class="spinner" style="margin:0 auto 18px;"></div>
    <div style="font-size:14.5px;font-weight:600;">Scanning ${esc(username)}…</div>
    <div style="font-size:12px;color:#7a756a;margin-top:6px;">Reading repos, detecting skills and computing market fit.</div>
  </div>`);
  setSyncLabel('SCANNING…');

  try {
    const data = await api('POST', '/github/connect', { username });
    setSyncLabel('READY');
    _renderProjectsConnected(data);
  } catch (e) {
    setSyncLabel('READY');
    setHTML('screen', `<div class="anim-in" style="padding:60px;text-align:center;color:#b1493a;">
      <div style="font-size:20px;margin-bottom:10px;">⚠</div>
      <div style="font-size:13px;">${esc(e.message)}</div>
      <div style="margin-top:18px;"><button class="btn-back" onclick="renderProjects()">← Try again</button></div>
    </div>`);
  }
}

async function resyncGitHub() {
  const username = (document.getElementById('gh-username-label')?.textContent || '').trim();
  if (!username) { await renderProjects(); return; }
  setHTML('screen', `<div style="padding:60px;text-align:center;">
    <div class="spinner" style="margin:0 auto 18px;"></div>
    <div style="font-size:14px;font-weight:600;">Re-syncing ${esc(username)}…</div>
  </div>`);
  setSyncLabel('SYNCING…');
  try {
    const data = await api('POST', '/github/connect', { username });
    setSyncLabel('READY');
    _renderProjectsConnected(data);
  } catch (e) {
    setSyncLabel('READY');
    alert('Re-sync failed: ' + e.message);
    await renderProjects();
  }
}

async function disconnectGitHub() {
  if (!confirm('Disconnect GitHub and clear cached repo data?')) return;
  await api('DELETE', '/github/disconnect');
  await renderProjects();
}

function _renderProjectsConnected(data) {
  const stats = data.stats || {};
  const repos = data.repos || [];
  const buildNext = data.build_next || [];

  const statCards = [
    { label: 'REPOS SCANNED',    value: stats.repos_scanned || 0,    sub: 'public repositories' },
    { label: 'SKILLS DETECTED',  value: stats.skills_detected || 0,  sub: 'from languages & topics' },
    { label: 'ALIGNED ROLES',    value: stats.aligned_roles || 0,    sub: 'open roles that match' },
  ].map(s => `
    <div style="background:#fff;border:1px solid #e7e3da;border-radius:14px;padding:16px 18px;">
      <div style="font-family:'IBM Plex Mono',monospace;font-size:10px;letter-spacing:0.6px;color:#9a9488;">${s.label}</div>
      <div style="font-family:'IBM Plex Mono',monospace;font-size:30px;font-weight:600;letter-spacing:-1px;line-height:1;margin-top:9px;">${s.value}</div>
      <div style="font-size:11.5px;color:#7a756a;margin-top:7px;">${s.sub}</div>
    </div>`).join('');

  const repoCards = repos.map(r => {
    const skillTags = (r.skills || []).slice(0, 5).map(s =>
      `<span style="font-size:11px;font-weight:500;color:#55504a;background:#f6f4ef;border:1px solid #ece7dd;border-radius:6px;padding:2px 8px;">${esc(s)}</span>`
    ).join('');

    const langDot = r.language
      ? `<span style="display:inline-flex;align-items:center;gap:5px;font-size:11.5px;color:#7a756a;">
          <span style="width:8px;height:8px;border-radius:50%;background:${esc(r.lang_color)};flex:none;"></span>${esc(r.language)}
         </span>`
      : '';

    const feedbackHtml = r.feedback
      ? `<div style="background:#f7edda;border:1px solid #ecddc0;border-radius:9px;padding:10px 12px;margin-top:12px;display:flex;gap:9px;align-items:flex-start;">
          <span style="color:#b9791f;font-size:12px;flex:none;margin-top:1px;">✦</span>
          <span style="font-size:11.5px;line-height:1.5;color:#5e4d22;">${esc(r.feedback)}</span>
         </div>`
      : '';

    const bestCo = r.best_company
      ? `<div style="display:flex;align-items:center;gap:7px;margin-top:11px;padding-top:11px;border-top:1px solid #f0ece3;">
          <span style="font-family:'IBM Plex Mono',monospace;font-size:9.5px;color:#9a9488;">BEST FIT</span>
          ${colorAvatar(r.best_company_color, r.best_company.slice(0,2).toUpperCase(), 20, 5, 9)}
          <span style="font-size:12px;font-weight:500;">${esc(r.best_company)}</span>
         </div>`
      : '';

    return `<div style="background:#fff;border:1px solid #e7e3da;border-radius:16px;padding:18px;display:flex;flex-direction:column;">
      <div style="display:flex;align-items:flex-start;gap:10px;">
        <div style="flex:1;min-width:0;">
          <div style="display:flex;align-items:center;gap:8px;">
            <a href="${esc(r.url)}" target="_blank" style="font-size:14px;font-weight:600;color:#1b1a17;text-decoration:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(r.name)}</a>
            ${r.stars ? `<span style="font-family:'IBM Plex Mono',monospace;font-size:10px;color:#9a9488;">★ ${r.stars}</span>` : ''}
          </div>
          ${langDot ? `<div style="margin-top:5px;">${langDot}</div>` : ''}
          ${r.description ? `<div style="font-size:12px;color:#7a756a;line-height:1.5;margin-top:5px;">${esc(r.description)}</div>` : ''}
        </div>
        <div style="font-family:'IBM Plex Mono',monospace;font-size:17px;font-weight:600;color:${esc(r.fit_color)};flex:none;">${r.fit}%</div>
      </div>
      ${skillTags ? `<div style="display:flex;flex-wrap:wrap;gap:5px;margin-top:11px;">${skillTags}</div>` : ''}
      ${feedbackHtml}
      ${bestCo}
    </div>`;
  }).join('');

  const buildNextCards = buildNext.map(b => {
    const skillTags = (b.skills || []).map(s =>
      `<span style="font-size:11px;font-weight:500;color:#15604a;background:#e7f0ea;border:1px solid #cfe2d6;border-radius:6px;padding:2px 8px;">${esc(s)}</span>`
    ).join('');
    const coAvatars = (b.companies || []).slice(0, 3).map((co, i) => {
      const colors = ['#15604a','#2563a6','#6b4f9e'];
      return colorAvatar(colors[i % colors.length], co.slice(0,2).toUpperCase(), 22, 6, 10);
    }).join('');

    return `<div style="background:#fff;border:1px solid #e7e3da;border-radius:14px;padding:16px 18px;">
      <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:10px;">
        <div style="font-size:13.5px;font-weight:600;">${esc(b.name)}</div>
        <span style="font-family:'IBM Plex Mono',monospace;font-size:10px;font-weight:600;color:#15604a;background:#e7f0ea;border-radius:5px;padding:3px 8px;white-space:nowrap;flex:none;">+${b.gain}% FIT</span>
      </div>
      ${b.description ? `<div style="font-size:12px;color:#7a756a;line-height:1.5;margin-bottom:10px;">${esc(b.description)}</div>` : ''}
      <div style="display:flex;flex-wrap:wrap;gap:5px;margin-bottom:11px;">${skillTags}</div>
      <div style="display:flex;align-items:center;gap:7px;padding-top:10px;border-top:1px solid #f0ece3;">
        <span style="font-family:'IBM Plex Mono',monospace;font-size:9.5px;color:#9a9488;">FOR</span>
        <div style="display:flex;gap:4px;">${coAvatars}</div>
      </div>
    </div>`;
  }).join('');

  setHTML('screen', `<div class="anim-in" style="padding:20px 28px 60px;">

    <div style="background:#fff;border:1px solid #e7e3da;border-radius:14px;padding:12px 18px;display:flex;align-items:center;gap:14px;margin-bottom:20px;">
      <div style="width:34px;height:34px;border-radius:9px;background:#1b1a17;color:#fff;display:flex;align-items:center;justify-content:center;font-size:16px;flex:none;">⎇</div>
      <div style="flex:1;min-width:0;">
        <div style="display:flex;align-items:center;gap:8px;">
          <span style="font-size:13.5px;font-weight:600;" id="gh-username-label">${esc(data.username)}</span>
          <span style="font-family:'IBM Plex Mono',monospace;font-size:9.5px;color:#9a9488;">· ${stats.repos_scanned || 0} REPOS</span>
        </div>
        <div style="font-family:'IBM Plex Mono',monospace;font-size:9.5px;color:#9a9488;margin-top:2px;">LAST SYNCED ${esc(data.last_synced || 'just now')}</div>
      </div>
      <button class="btn-resync" onclick="resyncGitHub()">↻ Re-sync</button>
      <button class="btn-disconnect" onclick="disconnectGitHub()">Disconnect</button>
    </div>

    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:24px;">${statCards}</div>

    <div style="display:flex;align-items:baseline;justify-content:space-between;margin-bottom:13px;">
      <div style="font-size:13px;font-weight:600;">Portfolio</div>
      <div style="font-family:'IBM Plex Mono',monospace;font-size:10px;color:#9a9488;">${repos.length} REPOS · SORTED BY FIT</div>
    </div>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:28px;">
      ${repoCards || '<div style="grid-column:1/-1;padding:30px;text-align:center;color:#9a9488;font-size:13px;">No public repos found.</div>'}
    </div>

    ${buildNextCards ? `
    <div style="display:flex;align-items:baseline;justify-content:space-between;margin-bottom:13px;">
      <div style="font-size:13px;font-weight:600;">Build next</div>
      <div style="font-family:'IBM Plex Mono',monospace;font-size:10px;color:#9a9488;">AI-SUGGESTED · RANKED BY FIT IMPACT</div>
    </div>
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:14px;">${buildNextCards}</div>` : ''}

  </div>`);
}

// ── APPLICATIONS ──────────────────────────────────────────────────────────────

async function saveJob(jobId, btn) {
  if (btn) {
    btn.textContent = '✓ Saved';
    btn.style.color = '#15604a';
    btn.style.pointerEvents = 'none';
  }
  try {
    await api('POST', '/applications', { job_id: jobId, status: 'saved' });
  } catch (e) {
    if (btn) {
      btn.innerHTML = '<span style="font-family:\'IBM Plex Mono\',monospace;font-size:11px;">♡</span> Save';
      btn.style.color = '';
      btn.style.pointerEvents = '';
    }
    console.warn('Save failed:', e.message);
  }
}

const _STATUS_META = {
  saved:        { label: 'Saved',       color: '#7a756a', bg: '#f0ece3',  border: '#e7e3da' },
  applied:      { label: 'Applied',     color: '#2563a6', bg: '#e8f0fb',  border: '#b8d0f0' },
  interviewing: { label: 'Interviewing',color: '#15604a', bg: '#e7f0ea',  border: '#cfe2d6' },
  offer:        { label: 'Offer',       color: '#5a3e9c', bg: '#f0ecfb',  border: '#d4c8f3' },
  rejected:     { label: 'Rejected',    color: '#b1493a', bg: '#f5e5e1',  border: '#e8c9c4' },
};
const _STATUS_ORDER = ['saved', 'applied', 'interviewing', 'offer', 'rejected'];

async function renderApplications() {
  setTopbar('Applications', 'Track your job applications');
  setSyncLabel('LOADING…');
  let data;
  try {
    data = await api('GET', '/applications');
  } catch {
    data = { applications: [], total: 0 };
  }
  setSyncLabel('READY');

  const apps = data.applications || [];

  if (!apps.length) {
    setHTML('screen', `<div class="anim-in" style="padding:26px 28px 60px;">
      <div style="max-width:480px;margin:60px auto;background:#fff;border:1px solid #e7e3da;border-radius:18px;padding:40px;text-align:center;">
        <div style="font-size:32px;margin-bottom:16px;opacity:0.3;">♡</div>
        <div style="font-size:16px;font-weight:600;margin-bottom:8px;">No saved jobs yet</div>
        <div style="font-size:13px;color:#7a756a;line-height:1.6;">
          Hit <strong>Save</strong> on any open role in the Deep Dive to start tracking your applications here.
        </div>
        <button class="btn-primary" style="margin-top:22px;" onclick="navigate('deep')">Go to Deep Dive →</button>
      </div>
    </div>`);
    return;
  }

  // Group by status
  const grouped = {};
  for (const st of _STATUS_ORDER) grouped[st] = [];
  for (const a of apps) {
    if (grouped[a.status]) grouped[a.status].push(a);
  }

  const columns = _STATUS_ORDER.map(st => {
    const meta = _STATUS_META[st];
    const items = grouped[st];
    const cards = items.map(a => {
      const skillTags = a.required_skills.slice(0, 4).map(s =>
        `<span style="font-size:10.5px;font-weight:500;color:#55504a;background:#f6f4ef;border:1px solid #ece7dd;border-radius:5px;padding:1px 7px;">${esc(s)}</span>`
      ).join('');

      const urlLink = a.url
        ? `<a href="${esc(a.url)}" target="_blank" style="font-size:11px;color:#15604a;text-decoration:none;" title="View job posting">↗ View</a>`
        : '';

      const nextStatuses = _STATUS_ORDER.filter(s => s !== st && s !== 'rejected');
      const moveButtons = nextStatuses.slice(0, 2).map(s =>
        `<button onclick="moveApp(${a.id},'${s}')" style="font-size:10.5px;padding:3px 8px;border:1px solid #e7e3da;border-radius:6px;background:#fff;cursor:pointer;color:#55504a;">${_STATUS_META[s].label}</button>`
      ).join('');

      return `<div style="background:#fff;border:1px solid #e7e3da;border-radius:12px;padding:14px;display:flex;flex-direction:column;gap:9px;">
        <div style="display:flex;align-items:flex-start;gap:9px;">
          ${colorAvatar(a.company_color, a.company_name.slice(0,2).toUpperCase(), 28, 7, 12)}
          <div style="flex:1;min-width:0;">
            <div style="font-size:13px;font-weight:600;line-height:1.2;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="${esc(a.title)}">${esc(a.title)}</div>
            <div style="font-size:11px;color:#7a756a;margin-top:2px;">${esc(a.company_name)}${a.location ? ' · ' + a.location : ''}</div>
          </div>
          <div style="font-family:'IBM Plex Mono',monospace;font-size:13px;font-weight:600;color:${a.fit_color};flex:none;">${a.fit}%</div>
        </div>
        ${skillTags ? `<div style="display:flex;flex-wrap:wrap;gap:4px;">${skillTags}</div>` : ''}
        <div id="note-display-${a.id}" onclick="openNote(${a.id})" style="font-size:11px;color:${a.notes ? '#55504a' : '#bcb6aa'};cursor:text;line-height:1.45;white-space:pre-wrap;">${a.notes ? esc(a.notes) : 'Add a note…'}</div>
        <textarea id="note-input-${a.id}" rows="3" onblur="saveNote(${a.id})" onkeydown="if(event.key==='Escape')this.blur()" placeholder="Add a note…" style="display:none;width:100%;font-size:11px;border:1px solid #cfe2d6;border-radius:6px;padding:5px 7px;resize:vertical;font-family:inherit;color:#1b1a17;background:#f9fdf9;outline:none;box-sizing:border-box;">${esc(a.notes)}</textarea>
        <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;padding-top:8px;border-top:1px solid #f0ece3;">
          <div style="display:flex;gap:5px;">${moveButtons}</div>
          <div style="display:flex;align-items:center;gap:8px;">
            ${urlLink}
            <button onclick="removeApp(${a.id})" style="font-size:11px;color:#b1493a;background:none;border:none;cursor:pointer;padding:0;" title="Remove">✕</button>
          </div>
        </div>
      </div>`;
    }).join('');

    return `<div style="flex:1;min-width:180px;display:flex;flex-direction:column;gap:10px;">
      <div style="display:flex;align-items:center;gap:8px;padding:10px 12px;background:${meta.bg};border:1px solid ${meta.border};border-radius:10px;">
        <span style="font-family:'IBM Plex Mono',monospace;font-size:10px;font-weight:600;color:${meta.color};">${meta.label.toUpperCase()}</span>
        <span style="font-family:'IBM Plex Mono',monospace;font-size:10px;color:#9a9488;margin-left:auto;">${items.length}</span>
      </div>
      ${cards || `<div style="padding:18px 12px;text-align:center;color:#bcb6aa;font-size:12px;border:1px dashed #e7e3da;border-radius:10px;">—</div>`}
    </div>`;
  }).join('');

  const total = apps.length;
  const appliedPlus = apps.filter(a => ['applied','interviewing','offer'].includes(a.status)).length;
  const avgFit = total ? Math.round(apps.reduce((s, a) => s + a.fit, 0) / total) : 0;

  setHTML('screen', `<div class="anim-in" style="padding:20px 28px 60px;">

    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:22px;">
      <div style="background:#fff;border:1px solid #e7e3da;border-radius:14px;padding:16px 18px;">
        <div style="font-family:'IBM Plex Mono',monospace;font-size:10px;letter-spacing:0.6px;color:#9a9488;">TRACKED ROLES</div>
        <div style="font-family:'IBM Plex Mono',monospace;font-size:30px;font-weight:600;letter-spacing:-1px;line-height:1;margin-top:9px;">${total}</div>
        <div style="font-size:11.5px;color:#7a756a;margin-top:7px;">saved or in progress</div>
      </div>
      <div style="background:#fff;border:1px solid #e7e3da;border-radius:14px;padding:16px 18px;">
        <div style="font-family:'IBM Plex Mono',monospace;font-size:10px;letter-spacing:0.6px;color:#9a9488;">IN PROGRESS</div>
        <div style="font-family:'IBM Plex Mono',monospace;font-size:30px;font-weight:600;letter-spacing:-1px;line-height:1;margin-top:9px;color:#15604a;">${appliedPlus}</div>
        <div style="font-size:11.5px;color:#7a756a;margin-top:7px;">applied or interviewing</div>
      </div>
      <div style="background:#fff;border:1px solid #e7e3da;border-radius:14px;padding:16px 18px;">
        <div style="font-family:'IBM Plex Mono',monospace;font-size:10px;letter-spacing:0.6px;color:#9a9488;">AVG FIT</div>
        <div style="font-family:'IBM Plex Mono',monospace;font-size:30px;font-weight:600;letter-spacing:-1px;line-height:1;margin-top:9px;color:${fitColor(avgFit)};">${avgFit}%</div>
        <div style="font-size:11.5px;color:#7a756a;margin-top:7px;">across tracked roles</div>
      </div>
    </div>

    <div style="display:flex;gap:12px;overflow-x:auto;padding-bottom:8px;align-items:flex-start;">
      ${columns}
    </div>

  </div>`);
}

async function moveApp(appId, status) {
  await api('PUT', `/applications/${appId}`, { status });
  await renderApplications();
}

async function removeApp(appId) {
  await api('DELETE', `/applications/${appId}`);
  await renderApplications();
}

// ── NOTES ─────────────────────────────────────────────────────────────────────

function openNote(appId) {
  const display = document.getElementById(`note-display-${appId}`);
  const input   = document.getElementById(`note-input-${appId}`);
  if (!display || !input) return;
  display.style.display = 'none';
  input.style.display   = 'block';
  input.focus();
  input.setSelectionRange(input.value.length, input.value.length);
}

async function saveNote(appId) {
  const display = document.getElementById(`note-display-${appId}`);
  const input   = document.getElementById(`note-input-${appId}`);
  if (!display || !input) return;
  const notes = input.value;
  input.style.display   = 'none';
  display.style.display = '';
  display.textContent   = notes || 'Add a note…';
  display.style.color   = notes ? '#55504a' : '#bcb6aa';
  try {
    await api('PUT', `/applications/${appId}`, { notes });
  } catch (e) {
    console.warn('Note save failed:', e.message);
  }
}

// ── CAREER FOCUS ─────────────────────────────────────────────────────────────
async function setTargetRole(role) {
  await api('PUT', '/profile', { target_role: role });
  S.profile.target_role = role;
  S.stats = await api('GET', '/stats');
  renderProfileFooter();
  await renderProfile();
}

// ── INIT ──────────────────────────────────────────────────────────────────────
async function init() {
  // Wire up static buttons
  document.getElementById('add-btn').onclick = openAddOverlay;
  document.getElementById('add-close').onclick = closeAddOverlay;
  document.getElementById('tailor-close').onclick = _closeTailor;
  document.getElementById('ats-close').onclick = _closeATS;

  // Close overlays on backdrop click
  document.getElementById('add-overlay').onclick = e => {
    if (e.target === e.currentTarget) closeAddOverlay();
  };
  document.getElementById('tailor-overlay').onclick = e => {
    if (e.target === e.currentTarget) _closeTailor();
  };
  document.getElementById('ats-overlay').onclick = e => {
    if (e.target === e.currentTarget) _closeATS();
  };

  // Load initial profile for footer
  try {
    S.profile = await api('GET', '/profile');
    S.stats = await api('GET', '/stats');
  } catch {}

  renderNav();
  renderProfileFooter();
  await renderScreen();
}

document.addEventListener('DOMContentLoaded', init);
