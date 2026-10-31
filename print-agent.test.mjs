import test from 'node:test';
import assert from 'node:assert/strict';
import {once} from 'node:events';
import {createHash} from 'node:crypto';
import {createApp} from './http-app.mjs';

test('print agent token grants only read access to print routes and fails closed', async t => {
  const token = 'a'.repeat(43), printAgentHash = createHash('sha256').update(token).digest('hex');
  const auth = {enabled: true, origin: 'https://example.test', session: () => null};
  const amocrm = {printCandidates: async (from, sample) => ({from, sample, items: []})};
  const server = createApp({auth, amocrm, printAgentHash});
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  t.after(() => new Promise(resolve => { server.close(resolve); server.closeAllConnections(); }));
  const request = (path, options = {}) => fetch(`http://127.0.0.1:${server.address().port}${path}`, {redirect: 'manual', ...options});
  assert.equal((await request('/api/print-agent/leads?from=0')).status, 401);
  const headers = {Authorization: 'Bearer ' + token};
  assert.equal((await request('/api/print-agent/leads?from=bad', {headers})).status, 400);
  const result = await request('/api/print-agent/leads?from=123', {headers});
  assert.equal(result.status, 200); assert.equal((await result.json()).from, 123);
  assert.equal((await request('/api/state', {headers})).status, 401);
  assert.equal((await request('/api/print-agent/leads?from=0', {method: 'POST', headers})).status, 405);
  assert.equal((await request('/api/print-agent/unknown', {headers})).status, 404);
});

test('shared history requires authentication and never invokes CRM for synchronization',async t=>{
  const token='h'.repeat(43),printAgentHash=createHash('sha256').update(token).digest('hex');
  let recorded=null;
  const printDevices={authorize:()=>null,history:()=>({printed:{'1':{status:'submitted'}},uncertain:{},events:[]}),
    record:async(entries,owner)=>{recorded={entries,owner};return {ok:true};}};
  const server=createApp({auth:{enabled:true,session:()=>null},amocrm:{},printDevices,printAgentHash});
  server.listen(0,'127.0.0.1');await once(server,'listening');
  t.after(()=>new Promise(resolve=>{server.close(resolve);server.closeAllConnections();}));
  const request=(path,options={})=>fetch('http://127.0.0.1:'+server.address().port+path,options);
  assert.equal((await request('/api/print-agent/history')).status,401);
  assert.equal((await request('/api/printing/history')).status,401);
  const headers={Authorization:'Bearer '+token,'Content-Type':'application/json'};
  assert.equal((await (await request('/api/print-agent/history',{headers})).json()).printed['1'].status,'submitted');
  assert.equal((await request('/api/print-agent/history',{method:'POST',headers,body:JSON.stringify({entries:[]})})).status,200);
  assert.deepEqual(recorded,{entries:[],owner:'legacy'});
});
