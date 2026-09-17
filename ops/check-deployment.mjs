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
const login = await request('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', Origin: origin}, body: JSON.stringify({username: credentials.username, password: credentials.password})});
assert.equal(login.status, 200);
const setCookie = login.headers.get('set-cookie'); assert.match(setCookie, /; Secure/); assert.match(setCookie, /; HttpOnly/);
const headers = {'Content-Type': 'application/json', Origin: origin, Cookie: setCookie.split(';')[0]};
const state = async () => { const response = await request('/api/state', {headers}); assert.equal(response.status, 200); return response.json(); };
const waitForIdle = async () => {
  const deadline = Date.now() + 240000;
  while (Date.now() < deadline) { const current = await state(); if (!current.job.running && !current.pendingCount) return current; await setTimeout(2000); }
  throw new Error('Order synchronization did not finish in time');
};
await waitForIdle();
let numbers = [];
try { numbers = parseNumbers(await readFile('/root/amo-order-numbers', 'utf8')); } catch (e) { if (e.code !== 'ENOENT') throw e; }
if (numbers.length) {
  const response = await request('/api/sync', {method: 'POST', headers, body: JSON.stringify({numbers: numbers.join('\n')})}); assert.equal(response.status, 202);
}
const current = await waitForIdle();
assert.equal(current.job.errors.length, 0);
const loaded = new Set(current.orders.map(order => order.number));
assert.ok(numbers.every(number => loaded.has(number)), 'Missing known orders');
console.log(`HTTPS login verified. Loaded orders: ${current.orders.length}; sync errors: ${current.job.errors.length}.`);
assert.equal((await request('/api/auth/logout', {method: 'POST', headers, body: '{}'})).status, 200);
assert.equal((await request('/api/state', {headers})).status, 401);
console.log('Logout verified; the old session no longer grants access.');
