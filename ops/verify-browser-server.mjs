import {readFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
const root='/opt/amo/current/';
const {createAmoCrm}=await import(pathToFileURL(root+'amocrm.mjs'));
const amo=await createAmoCrm(pathToFileURL('/var/lib/amo/amocrm.json'),'https://snowbrick.ru');
const {labelDownload}=await import(pathToFileURL(root+'label-download.mjs'));
const data=await amo.printCandidates(0);
const saved=JSON.parse(await readFile('/var/lib/amo/print-devices.json','utf8'));
console.log(JSON.stringify({total:data.items.length,shipped:data.items.filter(v=>v.shipped).length,markedShipped:Object.keys(saved.shipped||{}).length}));

const stored=JSON.parse(await readFile('/var/lib/amo/amocrm.json','utf8'));
async function get(path){const r=await fetch('https://snegostroy.amocrm.ru'+path,{headers:{Authorization:'Bearer '+stored.accessToken}});if(!r.ok)throw Error('CRM '+r.status);return r.json();}
const pipeline=await get('/api/v4/leads/pipelines/8604134');
console.log(JSON.stringify({deliveryStages:(pipeline._embedded?.statuses||[]).filter(v=>/отправлен|сдэк|пункт.*выдач/i.test(v.name)).map(v=>v.name)}));
const groups=new Map();let missing=0;
for(let page=1;page<=40;page++){
 const raw=await get('/api/v4/leads?limit=250&filter[pipeline_id]=8604134&page='+page);
 for(const lead of raw._embedded?.leads||[]){
  if(saved.shipped?.[lead.id]||saved.browserPrinted?.[lead.id]||saved.jobs?.[lead.id]?.status==='printed')continue;
  const fields=lead.custom_fields_values||[],composition=fields.filter(f=>f.field_name?.trim().toLowerCase()==='состав заказа').flatMap(f=>f.values||[]).map(v=>v.value).filter(v=>typeof v==='string').join('\n');
  if(/\([^()]+\)/.test(composition))continue;missing++;
  const key=JSON.stringify({empty:!composition.trim(),fullWidth:/[（）]/.test(composition),square:/\[[^\]]+\]/.test(composition),explicitSku:fields.some(f=>/^(артикул|sku|артикулы)$/i.test(f.field_name?.trim()||'')&&(f.values||[]).some(v=>String(v.value||'').trim())),compositionAlias:fields.some(f=>/состав\s+заказа/i.test(f.field_name||'')&&f.field_name.trim().toLowerCase()!=='состав заказа')});
  groups.set(key,(groups.get(key)||0)+1);
 }
 if(!raw._links?.next)break;
}
console.log(JSON.stringify({missingSku:missing,categories:[...groups].map(([key,count])=>({...JSON.parse(key),count}))}));
