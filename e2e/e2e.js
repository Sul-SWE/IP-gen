/* End-to-end test in a real browser (Playwright). Start the server on an EMPTY database first, then:
     BASE=http://localhost:8000 ADMIN_USER=admin ADMIN_PASS=... node e2e/e2e.js
   The browser locale is Arabic on purpose: pages must still show English digits. */
const { chromium } = require('playwright');
const path = require('path');

const BASE = (process.env.BASE || 'http://localhost:8000').replace(/\/$/, '') + '/';
const USER = process.env.ADMIN_USER || 'admin', PASS = process.env.ADMIN_PASS || '';
const SHOTS = process.env.SHOTS || '';
const SAMPLE = path.join(__dirname, '..', 'prototype', 'data', 'sample-data.xlsx');
let failed = 0;
const ok = (name, cond, detail) => { if (!cond) failed++; console.log((cond ? 'PASS ' : 'FAIL ') + name + (detail !== undefined && !cond ? ' :: ' + detail : '')); };

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 720 }, locale: 'ar-SA' });
  const p = await ctx.newPage();
  const errs = [];
  const watch = (page, tag) => {
    page.on('console', m => { if (m.type() === 'error' && !/status of (401|409|400|404|429)/.test(m.text())) errs.push(tag + ': ' + m.text()); });
    page.on('pageerror', e => errs.push(tag + ' PAGEERROR: ' + e.message));
  };
  watch(p, 'admin');
  const W = ms => p.waitForTimeout(ms);
  const go = async (page, ms = 600) => { await p.goto(BASE + page); await W(ms); };
  const shot = async name => { if (SHOTS) await p.screenshot({ path: path.join(SHOTS, name + '.png') }); };
  const text = sel => p.textContent(sel);
  const confirm = async (name) => { if (name) await p.fill('#dlgName', name); await p.click('#dlgOk'); await W(700); };

  /* ---------- viewer: no sign-in ---------- */
  await go('index.html');
  ok('viewer sees the dashboard without signing in', /Address ranges/.test(await text('#dash')));
  ok('viewer menu has no admin pages', (await p.$$eval('#nav a', a => a.map(x => x.textContent).join('|'))) === 'Dashboard|Worksheet');
  ok('viewer has no New facility button', !(await p.$('#qa a.primary')));
  await shot('01-viewer-dashboard');
  await go('worksheet.html');
  ok('viewer worksheet hides import/export', !(await p.isVisible('#btnExp')));
  await go('generate.html');
  ok('admin page sends the viewer to sign-in', /login\.html/.test(p.url()));

  /* ---------- sign in ---------- */
  await p.fill('#u', USER); await p.fill('#p', 'wrong-password'); await p.click('#go'); await W(500);
  ok('wrong password is refused', /Wrong username or password/.test(await text('#msg')));
  await shot('02-login');
  await p.fill('#p', PASS); await p.click('#go'); await W(900);
  ok('sign-in returns to the requested page', /generate\.html/.test(p.url()), p.url());
  ok('admin menu shows all pages', (await p.$$eval('#nav a', a => a.length)) === 5);

  /* ---------- import: preview then confirm ---------- */
  await go('worksheet.html');
  await p.setInputFiles('#impf', SAMPLE); await W(900);
  const sum = await p.$$eval('.sum b', e => e.map(x => x.textContent).join());
  ok('import preview counts (add,skip,notes)', sum === '10,3,2', sum);
  ok('nothing is saved before Confirm', /0 of 0/.test(await text('#count')), await text('#count'));
  await shot('03-import-preview');
  await confirm('Engineer A');
  ok('import added 10 rows', /10 of 10/.test(await text('#count')), await text('#count'));
  await p.setInputFiles('#impf', SAMPLE); await W(900);
  ok('same file twice adds nothing', (await p.$$eval('.sum b', e => e[0].textContent)) === '0');
  await p.click('#dlgNo'); await W(300);
  await shot('04-worksheet');

  /* ---------- generate ---------- */
  await go('generate.html?gcp=HDGCP1-R1&vendor=Yokogawa');
  ok('engineer name is remembered', (await p.inputValue('#eng')) === 'Engineer A');
  await p.fill('#num', '1000'); await W(600);
  ok('live duplicate-name hint', /already exists/.test(await text('#nmHint')), await text('#nmHint'));
  await p.click('#btnGen'); await W(500);
  ok('duplicate name is rejected with the reason', /UTMN-1000 already exists/.test(await text('#msg')), await text('#msg'));
  await p.fill('#num', '2000'); await W(500); await p.click('#btnGen'); await W(600);
  ok('first free host is chosen (1 and 2 are imported)', /18\.1\.20\.171/.test(await text('#pv')) && /Host numbers 1, 2 are busy/.test(await text('#pv')));
  await shot('05-generate-preview');
  await p.dblclick('#btnSave').catch(() => {}); await W(900);
  ok('saved', /Saved/.test(await text('#msg')), await text('#msg'));
  await shot('06-generate-saved');

  /* ---------- management ---------- */
  await go('management.html');
  ok('double click created exactly one record', /Records\s*11/.test(await text('#t_active')), await text('#t_active'));
  await p.fill('#q', 'UTMN-2000'); await W(700);
  ok('search finds the record', /1 of 1 shown/.test(await text('#count')), await text('#count'));
  await p.click('button[data-a=ips]'); await W(200);
  ok('details show all addresses', /IES Moxa IP/.test(await text('tr.detail')));
  await p.click('button[data-a=edit]'); await W(400);
  await p.selectOption('#e_ven', 'Honeywell'); await W(700);
  ok('modify shows old and new IPs before saving', /18\.1\.100\.1/.test(await text('#e_net')) && /18\.1\.20\.171/.test(await text('#e_net')));
  await shot('07-modify');
  await p.fill('#e_date', '2026-13-01'); await p.click('#dlgOk'); await W(300);
  ok('invalid date keeps the dialog open', /real date/.test(await text('#dlgMsg')));
  await p.fill('#e_date', '2026-11-05'); await confirm();
  ok('modify with regeneration saved', /new IPs \(RTU IP-1 18\.1\.100\.1\)/.test(await text('#msg')), await text('#msg'));
  await p.click('button[data-a=del]'); await W(300); await confirm();
  ok('moved to trash', /moved to the trash/.test(await text('#msg')));
  await p.click('#t_trash'); await W(700);
  ok('trash shows who deleted', /Engineer A/.test(await text('#t')) && /UTMN-2000/.test(await text('#t')));
  await shot('08-trash');
  await p.click('button[data-a=restore]'); await W(300); await confirm();
  ok('restored', /restored/.test(await text('#msg')));
  await p.click('#t_log'); await W(700);
  ok('change log has details', /Modified/.test(await text('#t')) && /Vendor Yokogawa -> Honeywell/.test(await text('#t')));
  await shot('09-log');

  /* ---------- undo last import ---------- */
  await go('worksheet.html');
  await p.click('#btnUndo'); await W(500); await confirm();
  ok('undo removed the imported rows', /1 of 1/.test(await text('#count')), await text('#count'));
  await p.setInputFiles('#impf', SAMPLE); await W(900); await confirm();
  ok('export button downloads a file', await (async () => {
    const [dl] = await Promise.all([p.waitForEvent('download', { timeout: 8000 }), p.click('#btnExp')]);
    return /^IP-Generator-\d{4}-\d{2}-\d{2}\.xlsx$/.test(dl.suggestedFilename());
  })().catch(() => false));

  /* ---------- settings (admin panel) ---------- */
  await go('settings.html', 900);
  await shot('10-settings');
  await p.fill('#facCode', 'abqq'); await p.click('#facForm button'); await W(300); await confirm();
  ok('facility added', /ABQQ/.test(await text('.chips')));
  await p.click('#addGcp'); await W(300);
  await p.fill('#g_code', 'newgcp-r1'); await p.fill('#g_o1', '30'); await p.fill('#g_o2', '2'); await p.fill('#g_rv', '1900'); await p.fill('#g_pv', '1901');
  await confirm();
  ok('GCP & Ring added with blocks', /NEWGCP-R1/.test(await text('#set')) && /added with its first blocks/.test(await text('#msg')), await text('#msg'));
  await p.click('#addGcp'); await W(300);
  await p.fill('#g_code', 'OTHER-R1'); await p.fill('#g_o1', '30'); await p.fill('#g_o2', '2'); await p.fill('#g_rv', '1'); await p.fill('#g_pv', '2');
  await confirm();
  ok('a second GCP on the same prefix is refused', /already used by NEWGCP-R1/.test(await text('#msg')), await text('#msg'));
  // plan a block for the first range: conflict first, then valid
  await p.click('button[data-a=addblock]'); await W(300);
  await p.fill('#b_A', '100'); await p.fill('#b_B', '31'); await p.fill('#b_M', '12'); await p.click('#dlgOk'); await W(200);
  ok('an octet used by another block is refused in the dialog', /already used/.test(await text('#dlgMsg')));
  await p.fill('#b_A', '30'); await confirm();
  ok('planned block saved', /Planned/.test(await text('#set')));
  await shot('11-settings-planned');
  await p.click('button[data-a=activate]'); await W(300); await confirm();
  ok('block activated, old one retired', /1 retired block/.test(await text('#set')) && /Block 2/.test(await text('#set')));
  // vendor: unsafe rule is refused, then a safe one is added
  await p.click('#addVendor'); await W(300);
  await p.fill('#vn', 'Emerson'); await p.fill('#vc', '90'); await p.fill('#voA', '50'); await p.fill('#voB', '51'); await p.fill('#voM', '52');
  await p.click('#vcheck'); await W(600);
  ok('unsafe vendor rule is explained', /not safe/.test(await text('#vres')), await text('#vres'));
  await p.fill('#vc', '20'); await p.click('#vcheck'); await W(600);
  ok('safe vendor rule shows example addresses', /10\.1\.50\.169/.test(await text('#vres')));
  await shot('12-add-vendor');
  await confirm();
  ok('vendor added', /Emerson/.test(await text('#set')) && /Vendor Emerson added/.test(await text('#msg')), await text('#msg'));
  await go('generate.html?gcp=HDGCP1-R1&vendor=Yokogawa');
  await p.fill('#num', '3000'); await W(400); await p.click('#btnGen'); await W(600);
  ok('generation uses the newly activated block', /18\.1\.30\.169/.test(await text('#pv')), (await text('#pv')).slice(0, 200));
  await p.selectOption('#ven', 'Emerson'); await p.selectOption('#fac', 'ABQQ'); await W(300); await p.click('#btnGen'); await W(600);
  ok('new vendor and facility work in generation', /ABQQ-3000/.test(await text('#pv')) && /18\.1\.50\.169/.test(await text('#pv')));

  /* ---------- markup stays text ---------- */
  await go('management.html');
  await p.fill('#q', '<img src=x onerror="window.__xss=1">'); await W(700);
  ok('markup in search is shown as text, never run', (await p.evaluate(() => window.__xss)) === undefined && /No records match/.test(await text('#t')));

  /* ---------- only one admin at a time ---------- */
  const ctx2 = await browser.newContext({ viewport: { width: 1280, height: 720 } });
  const p2 = await ctx2.newPage(); watch(p2, 'admin2');
  await p2.goto(BASE + 'login.html'); await p2.fill('#u', USER); await p2.fill('#p', PASS); await p2.click('#go'); await p2.waitForTimeout(700);
  ok('second admin is told someone is signed in', /Another admin is signed in/.test(await p2.textContent('#msg')), await p2.textContent('#msg'));
  if (SHOTS) await p2.screenshot({ path: path.join(SHOTS, '13-admin-busy.png') });
  await p2.click('#force'); await p2.waitForTimeout(900);
  ok('take-over signs the second admin in', /index\.html/.test(p2.url()) && (await p2.$$eval('#nav a', a => a.length)) === 5);
  await p.fill('#q', 'UTMN'); await W(900);
  ok('the first admin is signed out and told why', /login\.html\?reason=session_replaced/.test(p.url()) && /Another admin signed in/.test(await text('#msg')), p.url());
  await ctx2.close();
  await p.fill('#u', USER); await p.fill('#p', PASS); await p.click('#go'); await W(900);
  if (/Another admin/.test(await text('#msg').catch(() => ''))) { await p.click('#force'); await W(900); }

  /* ---------- layout at laptop, tablet and phone ---------- */
  const arabic = /[٠-٩۰-۹]/;
  let layoutOk = true, digitsOk = true;
  for (const w of [390, 820, 1280]) {
    await p.setViewportSize({ width: w, height: w === 390 ? 844 : w === 820 ? 1180 : 720 });
    for (const pg of ['index', 'generate', 'management', 'worksheet', 'settings']) {
      await go(pg + '.html', 800);
      const r = await p.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth, t: document.body.innerText, h: document.documentElement.scrollHeight }));
      if (r.sw > r.cw) { layoutOk = false; console.log('   sideways scroll: ' + pg + ' @' + w + ' ' + r.sw + '>' + r.cw); }
      if (arabic.test(r.t)) { digitsOk = false; console.log('   arabic digits: ' + pg + ' @' + w); }
      if (w === 1280) console.log('   height @1280x720: ' + pg + ' ' + r.h);
      if (SHOTS && (w !== 1280 || pg === 'index' || pg === 'settings')) await p.screenshot({ path: path.join(SHOTS, 'L-' + pg + '-' + w + '.png'), fullPage: w !== 1280 });
    }
  }
  ok('no sideways page scroll at 390, 820 and 1280 px', layoutOk);
  ok('no Arabic digits with an Arabic browser locale', digitsOk);
  for (const w of [390, 820, 1280]) {
    await p.setViewportSize({ width: w, height: 800 }); await go('index.html', 700);
    const fill = await p.evaluate(() => [...document.querySelectorAll('.kpis,.dgrid')].map(g => { const gr = g.getBoundingClientRect(); return Math.round(Math.max(...[...g.children].map(c => c.getBoundingClientRect().right)) - gr.right); }));
    ok('dashboard rows fill the width @' + w, fill.length >= 2 && fill.every(x => x === 0), fill.join());
  }
  ok('no console errors', errs.length === 0, errs.join(' | '));
  await browser.close();
  console.log(failed ? '\n' + failed + ' check(s) FAILED' : '\nAll end-to-end checks passed');
  process.exit(failed ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
