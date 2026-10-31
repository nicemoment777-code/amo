import {createHash} from 'node:crypto';
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm,mkdir} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {pathToFileURL} from 'node:url';
import {createBrowserControl} from './browser-control.mjs';
import {skuColors,orderColors} from './public/printer-model.js';

test('unprinted cards are red; printed multi-colour SKU cards use a 45 degree gradient',()=>{
  assert.deepEqual(orderColors({confirmed:false,skus:['product_lime_darkblue']}),['#ff666d','#131936']);
  assert.deepEqual(orderColors({confirmed:true,skus:['product_lime_darkblue']}),['linear-gradient(45deg, #a3e635, #142346)','#131936']);
  assert.equal(skuColors(['A_lime','B_navy','C_lime'])[0],'linear-gradient(45deg, #a3e635, #142346)');
  assert.equal(skuColors(['A_лаймовый_тёмно-синий'])[0],'linear-gradient(45deg, #a3e635, #142346)');
  assert.equal(skuColors(['A_lightblue'])[0],'#8bd7fa');assert.equal(skuColors(['A_darkblue'])[0],'#142346');
  assert.equal(skuColors(['A_red','B_red'])[0],'#ff666d');
  assert.equal(skuColors(['unknown'])[0],skuColors(['unknown'])[0]);
});

test('enabling automation uses server click time and retries preserve that boundary',async()=>{
  const folder=await mkdtemp(tmpdir()+'/browser-auto-start-');let clock=100250;
  try{
    const c=await createBrowserControl(pathToFileURL(folder+'/queue.json'),{now:()=>clock});
    c.publish('A',{snapshot:{items:[]}});
    const body={device:'A',action:'auto',args:{enabled:true,enabledFrom:1},requestId:'new_auto_window_01'};
    const queued=await c.enqueue(body);clock=102500;assert.deepEqual(await c.enqueue(body),queued);
    const {command}=await c.take('A');assert.equal(command.args.enabledFrom,101);
  }finally{await rm(folder,{recursive:true,force:true});}
});
import {createApp} from './http-app.mjs';
import {filterItems,articleCounts,orderedGroups,stamp,day} from './public/printer-model.js';

test('commands are bound to a device, delivered once, persisted before delivery and never replayed',async()=>{
  const folder=await mkdtemp(tmpdir()+'/snowbrick-browser-');
  try{
    const file=pathToFileURL(folder+'/commands.json');let now=1000;
    const c=await createBrowserControl(file,{now:()=>now});
    c.publish('A',{name:'Test computer',snapshot:{items:[]}});c.publish('B',{snapshot:{items:[]}});
    const body={device:'A',action:'print',args:{plan:'sample'},requestId:'0123456789abcdef'};
    const first=await c.enqueue(body);assert.deepEqual(await c.enqueue(body),first);
    assert.equal((await c.take('B')).command,null);
    assert.equal((await c.take('A')).command.id,first.id);
    assert.equal((await c.take('A')).command,null);
    const restored=await createBrowserControl(file,{now:()=>now});assert.equal((await restored.take('A')).command,null);
    await assert.rejects(c.finish('B',{id:first.id,ok:true}),/недоступно/);
    await c.finish('A',{id:first.id,ok:true,result:{submitted:1}});assert.equal(c.result(first.id).status,'done');
    assert.deepEqual(await c.finish('A',{id:first.id,ok:true,result:{submitted:1}}),{ok:true});
    now=62000;await assert.rejects(c.enqueue({...body,requestId:'differentrequest99'}),/не на связи/);
    c.publish('A',{snapshot:{items:[]}});const second=await c.enqueue({...body,requestId:'differentrequest99'});
    now+=120001;assert.equal((await c.take('A')).command,null);assert.equal(c.result(second.id).status,'expired');
  }finally{await rm(folder,{recursive:true,force:true});}
});
test('browser operations require a session and exact Origin; device publication requires a device key',async()=>{
  const folder=await mkdtemp(tmpdir()+'/snowbrick-browser-http-');
  const control=await createBrowserControl(pathToFileURL(folder+'/queue.json'));
  const auth={enabled:true,origin:'https://example.test',session:req=>req.headers.cookie==='owner=valid'?{username:'owner'}:null};
  const server=createApp({sync:{},auth,amocrm:{},printDevices:{authorize:()=>null},browserControl:control});
  await new Promise(r=>server.listen(0,'127.0.0.1',r));const url=`http://127.0.0.1:${server.address().port}`;
  try{
    assert.equal((await fetch(url+'/api/browser/devices')).status,401);
    assert.equal((await fetch(url+'/api/browser/devices',{headers:{cookie:'owner=valid'}})).status,200);
    assert.equal((await fetch(url+'/api/browser/command',{method:'POST',headers:{cookie:'owner=valid',Origin:'https://evil.test','Content-Type':'application/json'},body:'{}'})).status,403);
    assert.equal((await fetch(url+'/api/print-agent/browser/snapshot',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})).status,401);
    const home=await fetch(url+'/',{headers:{cookie:'owner=valid'}});assert.match(await home.text(),/Карточки по артикулу/);
  }finally{await new Promise(r=>server.close(r));await rm(folder,{recursive:true,force:true});}
});
test('browser filters use Moscow dates and multi-article orders count once per article and once in print order',()=>{
  const base=stamp('2026-10-25');assert.equal(day(base),'2026-10-25');
  const items=[{id:1,createdAt:base,skus:['A','B'],deliveryService:'yandex',confirmed:false},{id:2,createdAt:base+2,skus:['A'],deliveryService:'cdek',confirmed:true},{id:3,createdAt:base+1,skus:['A','B'],deliveryService:'yandex',confirmed:false}];
  assert.equal(filterItems(items,{from:base,to:base+10,carrier:'yandex',skus:new Set(['A','B'])}).length,2);
  assert.equal(articleCounts(items).find(v=>v[0]==='A')[1].count,3);
  assert.deepEqual(orderedGroups([...items,items[0]]).map(v=>v.id),[1,3,2]);
});

test('failed durable enqueue never becomes a deliverable print command',async()=>{
  const folder=await mkdtemp(tmpdir()+'/browser-write-fail-');
  try{
    const file=pathToFileURL(folder+'/queue.json'),c=await createBrowserControl(file);
    c.publish('A',{snapshot:{items:[]}});
    await mkdir(folder+'/queue.json');
    await assert.rejects(c.enqueue({device:'A',action:'print',args:{plan:'test'},requestId:'unique_failed_request'}));
    await rm(folder+'/queue.json',{recursive:true});
    assert.equal((await c.take('A')).command,null);
  }finally{await rm(folder,{recursive:true,force:true});}
});
test('server catalog works without an online PC and never reveals raw CRM fields',async()=>{
  const folder=await mkdtemp(tmpdir()+'/browser-catalog-');
  const control=await createBrowserControl(pathToFileURL(folder+'/queue.json'));
  const history={printed:{'7':{status:'submitted'}},uncertain:{'8':{status:'reserved-on-server'}},events:[]};
  const auth={enabled:true,origin:'https://example.test',session:req=>req.headers.cookie==='owner=valid'?{username:'owner'}:null};
  const server=createApp({sync:{},auth,browserControl:control,printDevices:{history:()=>history},
    amocrm:{printCandidates:async()=>({items:[{id:7,composition:'Private product (A); (A)',labelHost:'private.test',createdAt:1,hasLabel:true,deliveryService:'yandex'},{id:8,composition:'(B)',hasLabel:true,createdAt:2,deliveryService:'cdek'}]})}});
  await new Promise(r=>server.listen(0,'127.0.0.1',r));const url='http://127.0.0.1:'+server.address().port;
  try{
    assert.equal((await fetch(url+'/api/browser/catalog?from=0')).status,401);
    const response=await fetch(url+'/api/browser/catalog?from=0',{headers:{cookie:'owner=valid'}});
    const body=await response.json();assert.equal(response.status,200);
    assert.deepEqual(body.items[0].skus,['A']);assert.equal(body.items[0].confirmed,true);assert.equal(body.items[1].canPrint,false);
    assert.doesNotMatch(JSON.stringify(body),/Private product|private.test|composition/);
    assert.equal((await fetch(url+'/api/browser/catalog?from=-1',{headers:{cookie:'owner=valid'}})).status,400);
  }finally{await new Promise(r=>server.close(r));await rm(folder,{recursive:true,force:true});}
});

test('two installations sharing legacy access cannot receive each other browser commands',async()=>{
  const folder=await mkdtemp(tmpdir()+'/browser-installation-');
  const control=await createBrowserControl(pathToFileURL(folder+'/queue.json')),token='x'.repeat(43);
  const auth={enabled:true,origin:'https://example.test',session:req=>req.headers.cookie==='owner=valid'?{}:null};
  const server=createApp({sync:{},auth,amocrm:{},browserControl:control,printAgentHash:createHash('sha256').update(token).digest('hex')});
  await new Promise(r=>server.listen(0,'127.0.0.1',r));const url='http://127.0.0.1:'+server.address().port;
  const headers=id=>({Authorization:'Bearer '+token,'X-Print-Client':id,'Content-Type':'application/json'});
  try{
    const a='a'.repeat(32),b='b'.repeat(32);
    assert.equal((await fetch(url+'/api/print-agent/browser/snapshot',{method:'POST',headers:headers(a),body:JSON.stringify({snapshot:{items:[]}})})).status,200);
    await fetch(url+'/api/browser/command',{method:'POST',headers:{cookie:'owner=valid',Origin:auth.origin,'Content-Type':'application/json'},body:JSON.stringify({device:'legacy:'+a,action:'refresh',args:{},requestId:'uniqueinstallationrequest'})});
    assert.equal((await (await fetch(url+'/api/print-agent/browser/poll',{headers:headers(b)})).json()).command,null);
    assert.equal((await (await fetch(url+'/api/print-agent/browser/poll',{headers:headers(a)})).json()).command.action,'refresh');
  }finally{await new Promise(r=>server.close(r));await rm(folder,{recursive:true,force:true});}
});
