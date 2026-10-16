import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, readFile, rm, stat} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {once} from 'node:events';
import {createAmoCrm, callbackPath} from './amocrm.mjs';
import {createApp} from './http-app.mjs';
import {createAuth, hashPassword} from './auth.mjs';

const credentials = {clientId: '11111111-2222-3333-4444-555555555555', clientSecret: 'test-only-secret-123456'};
async function fixture(t, options = {}) {
  const dir = await mkdtemp(join(tmpdir(), 'amocrm-'));
  t.after(() => rm(dir, {recursive: true, force: true}));
  const file = pathToFileURL(join(dir, 'amocrm.json'));
  const calls = [];
  const fetcher = async (url, options) => {
    calls.push({url, options});
    return Response.json(url.endsWith('/account') ? {subdomain: 'snegostroy'} : {access_token: 'private-access-' + calls.length, refresh_token: 'private-refresh-' + calls.length, expires_in: 120});
  };
  const service = await createAmoCrm(file, 'https://example.test', {fetcher, ...options});
  return {service, file, calls};
}
const params = url => new URLSearchParams({state: new URL(url).searchParams.get('state'), code: 'private-code', referer: 'snegostroy.amocrm.ru'});

test('OAuth state is session-bound, single-use and expires; account is fixed', async t => {
  let clock = 0;
  const {service, calls} = await fixture(t, {now: () => clock});
  await service.configure(credentials);
  const p = params(service.start('owner-session'));
  await assert.rejects(service.callback(p, 'attacker-session'));
  assert.equal(calls.length, 0);
  await service.callback(p, 'owner-session');
  await assert.rejects(service.callback(p, 'owner-session'));
  const wrong = params(service.start('owner-session')); wrong.set('referer', 'evil.test');
  await assert.rejects(service.callback(wrong, 'owner-session'));
  const old = params(service.start('owner-session')); clock = 600001;
  await assert.rejects(service.callback(old, 'owner-session'));
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, 'https://snegostroy.amocrm.ru/oauth2/access_token');
  assert.equal(JSON.parse(calls[0].options.body).redirect_uri, 'https://example.test' + callbackPath);
});

test('tokens persist privately, refresh once under concurrent requests and status never exposes secrets', async t => {
  let clock = 0;
  const {service, file, calls} = await fixture(t, {now: () => clock});
  await service.configure(credentials);
  await service.callback(params(service.start('session')), 'session');
  assert.doesNotMatch(JSON.stringify(service.status()), /private-|test-only-secret|11111111/);
  if (process.platform !== 'win32') assert.equal((await stat(file)).mode & 0o777, 0o600);
  const restarted = await createAmoCrm(file, 'https://example.test');
  assert.equal(restarted.status().connected, true);
  clock = 120000;
  await Promise.all([service.verify(), service.verify()]);
  assert.equal(calls.filter(call => call.url.endsWith('/access_token')).length, 2);
  assert.equal(JSON.parse(calls[1].options.body).refresh_token, 'private-refresh-1');
  assert.equal(JSON.parse(await readFile(file, 'utf8')).refreshToken, 'private-refresh-2');
  await service.configure(credentials);
  assert.equal(service.status().connected, false);
});

test('OAuth failures do not expose provider bodies or overwrite saved tokens', async t => {
  const {service, file} = await fixture(t, {fetcher: async () => new Response('private-secret-in-provider-error', {status: 400})});
  await service.configure(credentials);
  await assert.rejects(service.callback(params(service.start('session')), 'session'), error => !/private-secret/.test(error.message));
  assert.equal(JSON.parse(await readFile(file, 'utf8')).accessToken, undefined);
  await assert.rejects(service.configure({...credentials, clientId: 'https://evil.test'}));
});

test('background refresh waits until needed and backs off after provider errors', async t => {
  let clock = 0, requests = 0, fail = false;
  const {service} = await fixture(t, {now: () => clock, fetcher: async () => {
    requests++;
    if (fail) throw new Error('private-provider-error');
    return Response.json({access_token: 'test-access', refresh_token: 'test-refresh', expires_in: 120});
  }});
  await service.refreshDue(); assert.equal(requests, 0);
  await service.configure(credentials);
  await service.callback(params(service.start('session')), 'session');
  await service.refreshDue(); assert.equal(requests, 1);
  clock = 60001; fail = true;
  await service.refreshDue(); assert.equal(requests, 2);
  clock = 120001; await service.refreshDue(); assert.equal(requests, 2);
  clock = 960002; fail = false;
  await service.refreshDue(); assert.equal(requests, 3);
  assert.equal(service.status().expiresAt, clock + 120000);
});

test('HTTP protects setup and credentials, enforces Origin and clears callback query', async t => {
  const {service} = await fixture(t);
  const origin = 'https://example.test', password = 'test-only-password-1234';
  const auth = createAuth({NODE_ENV: 'production', APP_ORIGIN: origin, DASHBOARD_USERNAME: 'admin', DASHBOARD_PASSWORD_HASH: await hashPassword(password)});
  const server = createApp({auth, amocrm: service, sync: {state: () => ({orders: []})}});
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  t.after(() => new Promise(resolve => { server.close(resolve); server.closeAllConnections(); }));
  const request = (path, options = {}) => fetch(`http://127.0.0.1:${server.address().port}${path}`, {redirect: 'manual', ...options});
  const post = (path, body, headers = {}) => request(path, {method: 'POST', headers: {'Content-Type': 'application/json', Origin: origin, ...headers}, body: JSON.stringify(body)});
  assert.equal((await request('/api/amocrm/status')).status, 401);
  assert.equal((await request('/integrations/amocrm')).headers.get('location'), '/login');
  assert.equal((await request(callbackPath)).status, 200);
  assert.equal((await request(callbackPath + '?code=private-code')).headers.get('location'), '/login');
  const cookie = (await post('/api/auth/login', {username: 'admin', password})).headers.get('set-cookie').split(';')[0];
  assert.equal((await post('/api/amocrm/configure', credentials, {Cookie: cookie, Origin: 'https://evil.test'})).status, 403);
  assert.equal((await post('/api/amocrm/configure', credentials, {Cookie: cookie})).status, 200);
  const status = await request('/api/amocrm/status', {headers: {Cookie: cookie}});
  assert.equal(status.headers.get('cache-control'), 'no-store');
  assert.doesNotMatch(await status.text(), /test-only-secret/);
  const {url} = await (await post('/api/amocrm/start', {}, {Cookie: cookie})).json();
  const result = await request(callbackPath + '?' + params(url), {headers: {Cookie: cookie}});
  assert.equal(result.headers.get('location'), '/integrations/amocrm?result=ok');
  assert.equal(result.headers.get('referrer-policy'), 'no-referrer');
  assert.equal((await post('/api/amocrm/verify', {}, {Cookie: cookie})).status, 200);
});
