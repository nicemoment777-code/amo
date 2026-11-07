import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const [id,at]=process.argv.slice(2);if(!/^\d+$/.test(id||'')||!/^\d+$/.test(at||''))throw Error('Missing recovery confirmation');
const credentials=JSON.parse(await readFile('/root/amo-dashboard-credentials.json','utf8')),origin=new URL(credentials.url).origin;
const request=(path,options={})=>fetch(origin+path,{redirect:'manual',signal:AbortSignal.timeout(30000),...options});
const login=await request('/api/auth/login',{method:'POST',headers:{Origin:origin,'Content-Type':'application/json'},body:JSON.stringify({username:credentials.username,password:credentials.password})});assert.equal(login.status,200);
const headers={Cookie:login.headers.get('set-cookie').split(';')[0],Origin:origin,'Content-Type':'application/json'};
try{
 const response=await request('/api/printing/history',{headers});assert.equal(response.status,200);const before=await response.json();
 assert.equal(before.printed[id],undefined);assert.equal(before.uncertain[id]?.at,Number(at));
 const result=await request('/api/printing/recover',{method:'POST',headers,body:JSON.stringify({id,expectedAt:Number(at),confirmedNotPrinted:true})});assert.equal(result.status,200);assert.equal((await result.json()).manualOnly,true);
 const after=await (await request('/api/printing/history',{headers})).json();assert.equal(after.uncertain[id],undefined);assert.equal(after.printed[id],undefined);
 console.log(JSON.stringify({recovered:true,manualOnly:true,markedPrinted:false,physicalPrint:false}));
}finally{await request('/api/auth/logout',{method:'POST',headers,body:'{}'});}
