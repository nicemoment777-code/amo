// Runs on the server. Output contains counts only, never credentials or orders.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {setTimeout} from 'node:timers/promises';
import {parseNumbers} from '../cdek.mjs';
const credentials = JSON.parse(await readFile('/root/amo-dashboard-credentials.json', 'utf8'));
const origin = new URL(credentials.url).origin;
const request = (path, options = {}) => fetch(origin + path, {redirect: 'manual', signal: AbortSignal.timeout(30000), ...options});
const root = await request('/'); assert.equal(root.status, 302); assert.equal(root.headers.get('location'), '/login');
assert.equal(root.headers.get('www-authenticate'), null);
assert.equal((await request('/login')).status, 200);
assert.equal((await request('/api/state')).status, 401);
assert.equal((await request('/api/amocrm/status')).status, 401);
assert.equal((await request('/integrations/amocrm/callback')).status, 200);
const login = await request('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', Origin: origin}, body: JSON.stringify({username: credentials.username, password: credentials.password})});
assert.equal(login.status, 200);
const setCookie = login.headers.get('set-cookie'); assert.match(setCookie, /; Secure/); assert.match(setCookie, /; HttpOnly/);
const headers = {'Content-Type': 'application/json', Origin: origin, Cookie: setCookie.split(';')[0]};
assert.equal((await request('/integrations/amocrm', {headers})).status, 200);
const crmStatus = await request('/api/amocrm/status', {headers});
assert.equal(crmStatus.status, 200);
assert.equal((await crmStatus.json()).redirectUri, origin + '/integrations/amocrm/callback');
const menu=await request('/',{headers});assert.equal(menu.status,200);assert.match(await menu.text(),/Все заявки/);
for(const asset of ['/printer.js','/printer.css','/printer-model.js'])assert.equal((await request(asset,{headers})).status,200);
assert.equal((await request('/api/browser/devices')).status,401);
const webOrders=await request('/api/browser/catalog?from=1790802000',{headers});assert.equal(webOrders.status,200);
const webData=await webOrders.json();assert.ok(Array.isArray(webData.items));
assert.ok(webData.items.every(v=>Array.isArray(v.skus)&&!('composition' in v)&&!('labelHost' in v)));
const sharedHistory=await request('/api/browser/history',{headers});assert.equal(sharedHistory.status,200);
console.log('Web menu and protected server catalog verified. Orders: '+webData.items.length+'.');
const state = async () => { const response = await request('/api/state', {headers}); assert.equal(response.status, 200); return response.json(); };
const waitForIdle = async () => {
  const deadline = Date.now() + 240000;
  while (Date.now() < deadline) { const current = await state(); if (!current.job.running && !current.pendingCount) return current; await setTimeout(2000); }
  throw new Error('Order synchronization did not finish in time');
};
let numbers = [];
try { numbers = parseNumbers(await readFile('/root/amo-order-numbers', 'utf8')); } catch (e) { if (e.code !== 'ENOENT') throw e; }
// Deployment verifies saved data and access. A background queue can contain new
// webhook deliveries and unavailable historical numbers unrelated to this release.
// Full live synchronization remains an explicit integration check.
let current = await state();
if (process.env.CHECK_FULL_SYNC === '1') {
  await waitForIdle();
  if (numbers.length) {
    const response = await request('/api/sync', {method: 'POST', headers, body: JSON.stringify({numbers: numbers.join('\n')})}); assert.equal(response.status, 202);
  }
  current = await waitForIdle();
  assert.equal(current.job.errors.length, 0);
}
const loaded = new Set(current.orders.map(order => order.number));
assert.ok(numbers.every(number => loaded.has(number)), 'Missing known orders');
console.log(`HTTPS login and amoCRM setup verified. Loaded orders: ${current.orders.length}; cabinet snapshots: ${current.orders.filter(order => order.cabinetSnapshot).length}; pending: ${current.pendingCount}; sync running: ${current.job.running}; sync errors: ${current.job.errors.length}.`);
if (current.pendingCount || current.job.errors.length || current.connection?.error) console.log('CDEK background synchronization needs separate verification; saved orders were not replaced.');
assert.equal((await request('/api/auth/logout', {method: 'POST', headers, body: '{}'})).status, 200);
assert.equal((await request('/api/state', {headers})).status, 401);
console.log('Logout verified; the old session no longer grants access.');
