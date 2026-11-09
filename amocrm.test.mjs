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

test('printing reads every page in the selected pipeline and extracts only required values', async t => {
  const paths = [];
  const {service} = await fixture(t, {fetcher: async url => {
    if (url.endsWith('/oauth2/access_token')) return Response.json({access_token:'access',refresh_token:'refresh',expires_in:3600});
    if(url.includes('/pipelines/'))return Response.json({_embedded:{statuses:[{id:777,name:'Заказ отправлен'}]}});
    paths.push(new URL(url));
    const page = new URL(url).searchParams.get('page');
    return Response.json({_embedded:{leads:[{id:Number(page),created_at:123,pipeline_id:8604134,status_id:page==='1'?777:778,custom_fields_values:[
      {field_name:'Итоговый вес, кг',values:[{value:4.52}]},
      {field_name:'ORDERID',values:[{value:page === '1' ? '001048' : 1047}]},
      {field_name:'Состав заказа',values:[{value:'Товар 1 - 2; Товар 2 - 1'}]},
      {field_name:'Этикетка ШК СДЭК',values:[{value:'https://files.crmkit.ru/private.pdf'}]}
    ]}]},_links:page === '1' ? {next:{href:'https://evil.test/ignored'}} : {}});
  }});
  await service.configure(credentials);
  await service.callback(params(service.start('session')), 'session');
  const data = await service.printCandidates(123);
  assert.equal(data.items.length, 2);
  assert.equal(data.items[0].shipped,true);assert.equal(data.items[1].shipped,false);
  for (const url of paths) {
    assert.equal(url.hostname, 'snegostroy.amocrm.ru');
    assert.equal(url.searchParams.get('filter[pipeline_id]'), '8604134');
    assert.equal(url.searchParams.get('filter[created_at][from]'), '123');
  }
  assert.equal(data.items[0].labelHost, 'files.crmkit.ru');
  assert.equal(data.items[0].hasLabel, true);
  assert.equal(data.items[0].packageWeight,'4.52 кг');
  assert.equal(data.items[0].orderNumber, '001048');
  assert.equal(data.items[1].orderNumber, '1047');
  assert.doesNotMatch(JSON.stringify(data.items), /private.pdf/);
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

test('all three completed delivery stages are archived, pending remains printable',async t=>{
 const stages=['Заказ отправлен','Принято в СДЭК','В пункте выдачи','Новый заказ'];
 const {service}=await fixture(t,{fetcher:async url=>{
  if(url.endsWith('/oauth2/access_token'))return Response.json({access_token:'access',refresh_token:'refresh',expires_in:3600});
  if(url.includes('/pipelines/'))return Response.json({_embedded:{statuses:stages.map((name,id)=>({id,name}))}});
  return Response.json({_embedded:{leads:stages.map((_,status_id)=>({id:status_id+1,status_id,pipeline_id:8604134,custom_fields_values:[]}))}});
 }});
 await service.configure(credentials);await service.callback(params(service.start('session')),'session');
 assert.deepEqual((await service.printCandidates(0)).items.map(v=>v.shipped),[true,true,true,false]);
});

test('feedback stage never enters catalogs and direct item/label reads are blocked',async t=>{
 const {service}=await fixture(t,{fetcher:async url=>{
  if(url.endsWith('/oauth2/access_token'))return Response.json({access_token:'access',refresh_token:'refresh',expires_in:3600});
  if(url.includes('/pipelines/'))return Response.json({_embedded:{statuses:[{id:55,name:'  Форма  обратной связи  '},{id:56,name:'Новый заказ'}]}});
  if(url.includes('/leads/100'))return Response.json({id:100,pipeline_id:8604134,status_id:55,custom_fields_values:[]});
  const page=new URL(url).searchParams.get('page');
  return Response.json({_embedded:{leads:[{id:page==='1'?100:101,pipeline_id:8604134,status_id:page==='1'?55:56,custom_fields_values:[]}]},_links:page==='1'?{next:{}}:{}});
 }});
 await service.configure(credentials);await service.callback(params(service.start('session')),'session');
 assert.deepEqual((await service.printCandidates(0)).items.map(v=>v.id),[101]);
 await assert.rejects(service.printLabel(100),error=>error.status===409);
 assert.deepEqual((await service.printCandidates(0,true)).items,[]);
});
test('report includes all stages and pipelines, deduplicates pages and returns only order composition',async t=>{
 const paths=[];
 const {service}=await fixture(t,{fetcher:async url=>{
  if(url.endsWith('/oauth2/access_token'))return Response.json({access_token:'access',refresh_token:'refresh',expires_in:3600});
  const parsed=new URL(url);paths.push(parsed);const page=parsed.searchParams.get('page');
  const lead=(id,created,pipeline)=>({id,created_at:created,pipeline_id:pipeline,status_id:999,name:'Private recipient',custom_fields_values:[{field_name:'PRODUCTS',values:[{value:'(A)'}]},{field_name:'Phone',values:[{value:'private-phone'}]}]});
  return Response.json({_embedded:{leads:page==='1'?[lead(1,5,8604134),lead(3,0,42)]:[lead(1,5,8604134),lead(2,6,42),lead(4,11,42)]},_links:page==='1'?{next:{href:'next'}}:{}});
 }});
 await service.configure(credentials);await service.callback(params(service.start('owner')),'owner');
 const all=await service.reportItems(1,10);
 assert.deepEqual(all.items.map(v=>v.id),[1,2]);assert.equal(all.items[0].composition,'(A)');
 assert.ok(paths.every(v=>!v.searchParams.has('filter[pipeline_id]')));
 assert.doesNotMatch(JSON.stringify(all),/Private recipient|private-phone/);
 const selected=await service.reportItems(1,10,42);assert.deepEqual(selected.items.map(v=>v.id),[2]);
 assert.equal(paths.at(-1).searchParams.get('filter[pipeline_id]'),'42');
});

test('report HTTP requires owner session and validates bounded dates',async()=>{
 const calls=[];const auth={enabled:true,origin:'https://example.test',session:req=>req.headers.cookie==='owner=valid'?{}:null};
 const server=createApp({sync:{},auth,amocrm:{reportItems:async(...args)=>{calls.push(args);return {items:[]};}}});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const base='http://127.0.0.1:'+server.address().port;
 try{
  assert.equal((await fetch(base+'/api/printing/report-items?from=1&to=10&pipeline=all')).status,401);
  const options={headers:{cookie:'owner=valid'}};
  assert.equal((await fetch(base+'/api/printing/report-items?from=1&to=10&pipeline=all',options)).status,200);
  assert.deepEqual(calls,[[1,10,null]]);
  for(const query of ['from=1','from=10&to=1','from=0&to=999999999','from=1&to=10&pipeline=no'])assert.equal((await fetch(base+'/api/printing/report-items?'+query,options)).status,400);
 }finally{await new Promise(r=>server.close(r));}
});
