import {readFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
const root='/opt/amo/current/';
const {createAmoCrm}=await import(pathToFileURL(root+'amocrm.mjs'));
const amo=await createAmoCrm(pathToFileURL('/var/lib/amo/amocrm.json'),'https://snowbrick.ru');
const {labelDownload}=await import(pathToFileURL(root+'label-download.mjs'));
const data=await amo.printCandidates(0);
const saved=JSON.parse(await readFile('/var/lib/amo/print-devices.json','utf8'));
console.log(JSON.stringify({total:data.items.length,shipped:data.items.filter(v=>v.shipped).length,markedShipped:Object.keys(saved.shipped||{}).length}));
for(const item of data.items.filter(v=>v.hasLabel).sort((a,b)=>b.createdAt-a.createdAt).slice(0,3)){
 try{
  const label=await amo.printLabel(item.id);
  const response=await labelDownload(new URL(label.url));
  console.log(JSON.stringify({status:response.status,redirect:response.status>=300&&response.status<400}));
  await response.body?.cancel();
 }catch(error){console.log(JSON.stringify({error:error.name,code:error.cause?.code||null,details:error.cause?.errors?.map(v=>v.code)||null}));}
}
