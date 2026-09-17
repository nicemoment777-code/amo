import test from 'node:test';
import assert from 'node:assert/strict';
import {once} from 'node:events';
import {createAuth, hashPassword} from './auth.mjs';
import {createApp} from './http-app.mjs';

const password = 'test-only-password-12345';
const hash = await hashPassword(password);
const config = {NODE_ENV: 'production', APP_ORIGIN: 'https://example.test', DASHBOARD_USERNAME: 'admin', DASHBOARD_PASSWORD_HASH: hash};
async function fixture(t, options) {
  const queued = [], auth = createAuth(config, options);
  const sync = {orders: {}, state: () => ({orders: [{number: '12345'}], pendingCount: 0, job: {running: false}}), enqueue: n => queued.push(n), verify: async () => {}};
  const server = createApp({sync, auth, webhookSecret: 'a'.repeat(64)});
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  t.after(() => new Promise(resolve => { server.close(resolve); server.closeAllConnections(); }));
  const request = (path, options = {}) => fetch(`http://127.0.0.1:${server.address().port}${path}`, {redirect: 'manual', ...options});
  const post = (path, body, headers = {}) => request(path, {method: 'POST', headers: {'Content-Type': 'application/json', Origin: config.APP_ORIGIN, ...headers}, body: JSON.stringify(body)});
  const login = () => post('/api/auth/login', {username: 'admin', password});
  return {request, post, login, queued};
}

test('anonymous visits see the login page, never orders or a browser auth challenge', async t => {
  const {request, post} = await fixture(t);
  const root = await request('/'); assert.equal(root.status, 302); assert.equal(root.headers.get('location'), '/login');
  const login = await request('/login'); assert.equal(login.status, 200); assert.match(await login.text(), /autocomplete="current-password"/);
  for (const path of ['/api/state', '/api/auth/session']) {
    const res = await request(path); assert.equal(res.status, 401); assert.equal(res.headers.get('www-authenticate'), null); assert.doesNotMatch(await res.text(), /12345/);
  }
  assert.equal((await post('/api/sync', {all: true})).status, 401);
  const invalid = await post('/api/auth/login', {username: 'admin', password: 'wrong'});
  assert.equal(invalid.status, 401); assert.equal(invalid.headers.get('set-cookie'), null);
});

test('login creates a secure session; rotation and logout invalidate old cookies', async t => {
  const {request, post, login} = await fixture(t);
  const signedIn = await login(); assert.equal(signedIn.status, 200);
  const setCookie = signedIn.headers.get('set-cookie');
  for (const marker of ['__Host-amo_session=', 'HttpOnly', 'Secure', 'SameSite=Lax', 'Path=/']) assert.ok(setCookie.includes(marker));
  const cookie = setCookie.split(';')[0];
  const state = await request('/api/state', {headers: {Cookie: cookie}}); assert.equal(state.status, 200); assert.equal((await state.json()).orders.length, 1); assert.equal(state.headers.get('cache-control'), 'no-store');
  const rotated = await post('/api/auth/login', {username: 'admin', password}, {Cookie: cookie});
  const nextCookie = rotated.headers.get('set-cookie').split(';')[0]; assert.notEqual(nextCookie, cookie);
  assert.equal((await request('/api/state', {headers: {Cookie: cookie}})).status, 401);
  assert.equal((await request('/api/state', {headers: {Cookie: nextCookie + 'x'}})).status, 401);
  const logout = await post('/api/auth/logout', {}, {Cookie: nextCookie}); assert.equal(logout.status, 200); assert.match(logout.headers.get('set-cookie'), /Max-Age=0/);
  assert.equal((await request('/api/state', {headers: {Cookie: nextCookie}})).status, 401);
});

test('sessions expire and do not survive a process restart', async t => {
  let clock = 0; const {request, login} = await fixture(t, {now: () => clock, lifetime: 1000});
  const cookie = (await login()).headers.get('set-cookie').split(';')[0];
  clock = 1001; assert.equal((await request('/api/state', {headers: {Cookie: cookie}})).status, 401);
  assert.equal(createAuth(config).session({headers: {cookie}}), null);
});

test('cross-site login, logout and sync are rejected, including missing Origin', async t => {
  const {request, post, login} = await fixture(t);
  const cookie = (await login()).headers.get('set-cookie').split(';')[0];
  for (const path of ['/api/auth/login', '/api/auth/logout', '/api/sync']) {
    assert.equal((await post(path, {username: 'admin', password}, {Origin: 'https://evil.test', Cookie: cookie})).status, 403);
    assert.equal((await request(path, {method: 'POST', headers: {'Content-Type': 'application/json', Cookie: cookie}, body: '{}'})).status, 403);
  }
  assert.equal((await request('/api/state', {headers: {Cookie: cookie}})).status, 200);
});

test('failed logins are rate limited and recover after the time window', async t => {
  let clock = 0; const {post, login} = await fixture(t, {now: () => clock});
  for (let i = 0; i < 8; i++) assert.equal((await post('/api/auth/login', {username: 'admin', password: 'wrong'})).status, 401);
  assert.equal((await login()).status, 429); clock = 900001; assert.equal((await login()).status, 200);
});

test('CDEK webhook keeps its independent secret authentication', async t => {
  const {request, queued} = await fixture(t);
  const options = {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({type: 'ORDER_STATUS', uuid: '12345678-1234-1234-1234-123456789012', attributes: {cdek_number: '12345'}})};
  assert.equal((await request('/webhooks/cdek/wrong', options)).status, 404);
  assert.equal((await request('/webhooks/cdek/' + 'a'.repeat(64), options)).status, 200); assert.deepEqual(queued, [['12345']]);
});

test('production and partial authentication configuration fail closed', () => {
  assert.throws(() => createAuth({NODE_ENV: 'production'}));
  assert.throws(() => createAuth({DASHBOARD_USERNAME: 'admin'}));
  assert.throws(() => createAuth({...config, APP_ORIGIN: 'http://example.test'}));
  assert.throws(() => createAuth({...config, DASHBOARD_PASSWORD_HASH: 'plain-password'}));
  assert.equal(createAuth({}).enabled, false);
});
