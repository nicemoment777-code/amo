import {readFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
const root='/opt/amo/current/';
const {createAmoCrm}=await import(pathToFileURL(root+'amocrm.mjs'));
const amo=await createAmoCrm(pathToFileURL('/var/lib/amo/amocrm.json'),'https://snowbrick.ru');
const {labelDownload}=await import(pathToFileURL(root+'label-download.mjs'));
const data=await amo.printCandidates(0);
const saved=JSON.parse(await readFile('/var/lib/amo/print-devices.json','utf8'));
console.log(JSON.stringify({total:data.items.length,shipped:data.items.filter(v=>v.shipped).length,markedShipped:Object.keys(saved.shipped||{}).length,dateArchived:Object.values(saved.shipped||{}).filter(v=>v.status==='owner-date-archive').length,beforeCutoff:data.items.filter(v=>v.createdAt>0&&v.createdAt<Date.parse('2026-10-31T00:00:00+03:00')/1000).length,oldUnarchived:data.items.filter(v=>v.createdAt>0&&v.createdAt<Date.parse('2026-10-31T00:00:00+03:00')/1000&&!saved.shipped?.[v.id]&&saved.jobs?.[v.id]?.status!=='printed'&&!saved.browserPrinted?.[v.id]).length}));

const stored=JSON.parse(await readFile('/var/lib/amo/amocrm.json','utf8'));
async function get(path){const r=await fetch('https://snegostroy.amocrm.ru'+path,{headers:{Authorization:'Bearer '+stored.accessToken}});if(!r.ok)throw Error('CRM '+r.status);return r.json();}
const pipeline=await get('/api/v4/leads/pipelines/8604134');
console.log(JSON.stringify({deliveryStages:(pipeline._embedded?.statuses||[]).filter(v=>/отправлен|сдэк|пункт.*выдач/i.test(v.name)).map(v=>v.name)}));
const doneIds=new Set((pipeline._embedded?.statuses||[]).filter(v=>['заказ отправлен','принято в сдэк','в пункте выдачи'].includes(v.name?.trim().toLowerCase())).map(v=>v.id));
const groups=new Map(),freshMissing=[];let missing=0;
for(let page=1;page<=40;page++){
 const raw=await get('/api/v4/leads?limit=250&filter[pipeline_id]=8604134&page='+page);
 for(const lead of raw._embedded?.leads||[]){
  if(doneIds.has(lead.status_id)||saved.shipped?.[lead.id]||saved.browserPrinted?.[lead.id]||saved.jobs?.[lead.id]?.status==='printed')continue;
  const fields=lead.custom_fields_values||[],composition=fields.filter(f=>f.field_name?.trim().toLowerCase()==='состав заказа').flatMap(f=>f.values||[]).map(v=>v.value).filter(v=>typeof v==='string').join('\n');
  if(/\([^()]+\)/.test(composition))continue;missing++;freshMissing.push(lead);
  const key=JSON.stringify({empty:!composition.trim(),fullWidth:/[（）]/.test(composition),square:/\[[^\]]+\]/.test(composition),explicitSku:fields.some(f=>/^(артикул|sku|артикулы)$/i.test(f.field_name?.trim()||'')&&(f.values||[]).some(v=>String(v.value||'').trim())),compositionAlias:fields.some(f=>/состав\s+заказа/i.test(f.field_name||'')&&f.field_name.trim().toLowerCase()!=='состав заказа')});
  groups.set(key,(groups.get(key)||0)+1);
 }
 if(!raw._links?.next)break;
}
console.log(JSON.stringify({missingSku:missing,categories:[...groups].map(([key,count])=>({...JSON.parse(key),count}))}));


const productShapes=new Map();let withProducts=0;
for(const lead of freshMissing){
 for(const field of lead.custom_fields_values||[]){
  if(![field.field_name,field.field_code].some(v=>v?.trim().toUpperCase()==='PRODUCTS'))continue;
  for(const entry of field.values||[]){const value=entry.value;if(value===null||value==='')continue;withProducts++;
   let structured=false,keys=[];try{const parsed=typeof value==='string'?JSON.parse(value):value;if(typeof parsed==='object'&&parsed){structured=true;keys=Object.keys(Array.isArray(parsed)?parsed[0]||{}:parsed).filter(k=>/^(sku|article|name|quantity|count|price|products|items)$/i.test(k));}}catch{}
   const text=String(value),key=JSON.stringify({type:typeof value,structured,keys,parentheses:/\([^()]+\)/.test(text),lines:text.split(/\n/).length,semicolon:text.includes(';'),quantitySuffix:/\s[-—×x]\s*\d+\s*(?:шт[.]?)?\s*$/i.test(text),plainSku:/^[\p{L}\p{N}_.-]+$/u.test(text)});productShapes.set(key,(productShapes.get(key)||0)+1);
  }
 }
}
console.log(JSON.stringify({productsValues:withProducts,shapes:[...productShapes].map(([key,count])=>({...JSON.parse(key),count}))}));

const pending=data.items.filter(v=>!saved.shipped?.[v.id]&&!saved.browserPrinted?.[v.id]&&saved.jobs?.[v.id]?.status!=='printed');
console.log(JSON.stringify({pending:pending.length,productsFallback:pending.filter(v=>v.articleSource==='products').length,remainingMissing:pending.filter(v=>!/\([^()]*\S[^()]*\)/.test(v.composition||'')).length}));
const candidate=pending.filter(v=>v.hasLabel&&/\([^()]*\S[^()]*\)/.test(v.composition||'')).sort((a,b)=>b.createdAt-a.createdAt)[0];
if(candidate){
 const {browserPdf}=await import(pathToFileURL(root+'browser-pdf.mjs'));
 const label=await amo.printLabel(candidate.id),url=new URL(label.url);
 if(url.protocol!=='https:'||url.hostname!=='files.crmkit.ru')throw Error('Unexpected label host');
 const response=await labelDownload(url);if(!response.ok)throw Error('Label HTTP '+response.status);
 const content=Buffer.from(await response.arrayBuffer());if(content.length>10e6)throw Error('Label too large');
 const prepared=await browserPdf([label.item],[content]);
 console.log(JSON.stringify({realPdfPrepared:prepared.subarray(0,5).toString()==='%PDF-',bytes:prepared.length,physicalPrint:false}));
}
