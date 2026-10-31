import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {setTimeout} from 'node:timers/promises';
import {randomUUID} from 'node:crypto';
const credentials=JSON.parse(await readFile('/root/amo-dashboard-credentials.json','utf8'));
const origin=new URL(credentials.url).origin;
const request=(path,options={})=>fetch(origin+path,{redirect:'manual',signal:AbortSignal.timeout(30000),...options});
const login=await request('/api/auth/login',{method:'POST',headers:{Origin:origin,'Content-Type':'application/json'},body:JSON.stringify({username:credentials.username,password:credentials.password})});
assert.equal(login.status,200);
const headers={Cookie:login.headers.get('set-cookie').split(';')[0],Origin:origin,'Content-Type':'application/json'};
try{
 let found=null,foundId=null;
 for(let attempt=0;attempt<20&&!found;attempt++){
   const list=await request('/api/browser/devices',{headers});assert.equal(list.status,200);
   for(const device of (await list.json()).devices.filter(v=>v.online)){
     const response=await request('/api/browser/snapshot?device='+encodeURIComponent(device.id),{headers});
     if(response.status!==200)continue;
     const snapshot=await response.json();
     if(snapshot.standalone===true&&(!snapshot.autoPrint||snapshot.loopActive)){found=snapshot;foundId=device.id;}
   }
   if(!found)await setTimeout(2000);
 }
 assert.ok(found,'Standalone Windows companion is not online yet');
 assert.ok(Array.isArray(found.items)&&Array.isArray(found.printers),'Invalid companion state');
 const queued=await request('/api/browser/command',{method:'POST',headers,body:JSON.stringify({device:foundId,action:'printers',args:{},requestId:randomUUID()})});
 assert.equal(queued.status,200);
 const command=await queued.json();let completed=false;
 for(let attempt=0;attempt<25&&!completed;attempt++){
   const response=await request('/api/browser/command/'+command.id,{headers});assert.equal(response.status,200);
   const result=await response.json();
   assert.notEqual(result.status,'failed','Companion rejected printer discovery');
   completed=result.status==='done';if(!completed)await setTimeout(2000);
 }
 assert.ok(completed,'Companion did not process printer discovery');
 const catalog=await request('/api/browser/catalog?from=1790802000',{headers});assert.equal(catalog.status,200);
 const data=await catalog.json();
 console.log(JSON.stringify({standalone:true,commandRoundTrip:true,loopActive:found.loopActive,autoPrint:found.autoPrint,printers:found.printers.length,desktopOrders:found.items.length,serverOrders:data.items.length}));
}finally{await request('/api/auth/logout',{method:'POST',headers,body:'{}'});}
