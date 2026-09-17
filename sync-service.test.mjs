import test from 'node:test';import assert from 'node:assert/strict';import {mkdtemp,readFile,writeFile,rm} from 'node:fs/promises';import {tmpdir} from 'node:os';import {join} from 'node:path';import {pathToFileURL} from 'node:url';import {createSync} from './sync-service.mjs';
test('успешные API-данные сохраняются; ошибки остаются в очереди',async()=>{
 const dir=await mkdtemp(join(tmpdir(),'cdek-sync-'));const base=pathToFileURL(dir+'/');
 try{
  await writeFile(new URL('orders.json',base),JSON.stringify({'12345':{number:'12345',source:'cdek-cabinet',classification:{color:'Светло-синий'},raw:{entity:{}}}}));
  const client={id:'id',secret:'secret',token:async()=> 'token',order:async n=>{if(n==='99999')throw Error('Временная ошибка');return {entity:{uuid:'test',cdek_number:n,packages:[]}}}};
  const sync=await createSync(client,base);sync.enqueue(['12345','12345','99999']);
  while(sync.state().job.running)await new Promise(r=>setTimeout(r,20));
  const db=JSON.parse(await readFile(new URL('orders.json',base),'utf8'));
  assert.equal(db['12345'].source,'cdek-api');assert.equal(db['12345'].classification,undefined);assert.equal(db['12345'].cabinetSnapshot.source,'cdek-cabinet');
  assert.deepEqual(JSON.parse(await readFile(new URL('queue.json',base),'utf8')),['99999']);assert.equal(sync.state().job.errors.length,1);
  const restored=await createSync(client,base);assert.equal(restored.state().pendingCount,1);
 }finally{await rm(dir,{recursive:true,force:true})}
});
