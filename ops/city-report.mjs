// Read-only owner report. Raw CRM records stay on the owner's VPS (0600).
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {pathToFileURL} from 'node:url';
const folder='/var/lib/amo/city-report';
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function get(path){
  for(let attempt=0;attempt<5;attempt++){
    const credentials=JSON.parse(await readFile('/var/lib/amo/amocrm.json','utf8'));
    const r=await fetch('https://snegostroy.amocrm.ru'+path,{headers:{Authorization:'Bearer '+credentials.accessToken},redirect:'error',signal:AbortSignal.timeout(60000)});
    if(r.status===204)return {};
    if([429,502,503,504].includes(r.status)){await pause(2000*(attempt+1));continue;}
    if(!r.ok)throw Error('CRM read failed: '+r.status);
    await pause(350);return r.json();
  }throw Error('CRM retry limit');
}
async function collection(path,key){
  const values=[];
  for(let page=1;page<=10000;page++){
    const data=await get(path+(path.includes('?')?'&':'?')+'limit=250&page='+page);
    values.push(...(data._embedded?.[key]||[]));
    if(!data._links?.next)return [...new Map(values.map(v=>[v.id,v])).values()];
  }throw Error('Pagination limit; report incomplete');
}
const fields=v=>(v.custom_fields_values||[]);
export const field=(v,re)=>fields(v).filter(f=>re.test(f.field_name||'')).flatMap(f=>f.values||[]).map(v=>v.value).filter(v=>v!==null&&v!==undefined);
export function profile(leads,pipelines,deleted){
  const names={},statuses={},shapes={};
  for(const lead of leads){statuses[lead.status_id]=(statuses[lead.status_id]||0)+1;
    for(const f of fields(lead))if(f.values?.length)names[f.field_name]=(names[f.field_name]||0)+1;
    for(const composition of field(lead,/^состав заказа$/i)){
      const s=String(composition);const shape=[/снегострой/i.test(s)?'snowbrick':'other',/станоч|станок/i.test(s)?'machine':'no-machine-word',/\d+\s*шт/i.test(s)?'qty-sht':/\)\s*[-—xх×:]?\s*\d+/i.test(s)?'qty-after-sku':'no-qty'].join('/');shapes[shape]=(shapes[shape]||0)+1;
    }
  }
  const structures={};
  for(const name of ['PRODUCTS','DELIVERY_ADDRESS','Состав заказа']){
    const shapes=new Map();
    for(const lead of leads)for(const value of field(lead,new RegExp('^'+name+'$','i'))){
      const shape=String(value).replace(/https?:\/\/\S+/g,'URL').replace(/[\p{L}\p{N}_]+/gu,w=>/^(город|г|область|обл|край|республика|респ|район|улица|ул|дом|д|кв|индекс|адрес|city|address|country|region|zip|postal|quantity|qty|name|price|sku|amount|шт|снегострой|станочек|станок|количество)$/i.test(w)?w:/^\d+$/.test(w)?'N':'W');
      shapes.set(shape,(shapes.get(shape)||0)+1);
    }structures[name]=[...shapes].sort((a,b)=>b[1]-a[1]).slice(0,35);
  }
  return {scanned:leads.length,deleted:deleted.length,earliest:Math.min(...leads.map(v=>v.created_at||Infinity)),latest:Math.max(...leads.map(v=>v.created_at||0)),fields:Object.entries(names).sort((a,b)=>b[1]-a[1]),statuses,pipelines:pipelines.map(v=>({id:v.id,name:v.name,archive:v.is_archive,statuses:v._embedded?.statuses?.map(s=>({id:s.id,name:s.name}))})),compositionShapes:shapes,structures};
}
export function cityOf(lead){
  const explicit=field(lead,/^(город|город доставки|город получателя|город сдэк|delivery.?city|city)$/i).map(String).map(v=>v.trim()).filter(Boolean);
  return explicit.length?[...new Set(explicit)].join(' / '):null;
}
export function quantityOf(lead){
  const numeric=field(lead,/^(количество станочков|количество станков|количество снегостроев|кол-во станочков|количество товара|количество)$/i).map(Number).filter(v=>Number.isSafeInteger(v)&&v>0&&v<=10000);
  const text=field(lead,/^состав заказа$/i).join('\n');
  const lines=text.split(/\r?\n|;(?![^()]*\))/).map(v=>v.trim()).filter(Boolean);
  let total=0,unknown=0,machineLines=0;
  for(const line of lines){
    if(!/снегострой|станоч|станок/i.test(line)||/^(?:чехол|запасн|дополн|лопат|смазк|ремкомплект)/i.test(line))continue;
    machineLines++;
    const m=line.match(/(?:кол(?:ичество|[.\s-]*во)\s*[:=]?\s*)(\d+)/i)||line.match(/(\d+)\s*(?:шт\.?|штук[аи]?)(?:\s|$|[.,;])/i)||line.match(/\)\s*(?:[-—xх×:]\s*)?(\d+)(?:\s|$|[.,;])/i);
    if(m&&Number(m[1])>0&&Number(m[1])<=10000)total+=Number(m[1]);else unknown++;
  }
  if(machineLines&&!unknown)return {quantity:total,source:'composition'};
  if(numeric.length===1&&(machineLines||/снегострой|станоч|станок/i.test(lead.name||'')))return {quantity:numeric[0],source:'numeric-field'};
  return {quantity:null,source:machineLines?'unknown-quantity':'no-machine'};
}
export function summarize(leads,contacts,pipelines){
  const contactMap=new Map(contacts.map(v=>[v.id,v]));const stages=new Map(pipelines.flatMap(p=>(p._embedded?.statuses||[]).map(s=>[s.id,s.name])));
  const aggregate=new Map();const audit={scanned:leads.length,matched:0,excludedNoSale:0,missingCity:0,missingQuantity:0,noMachine:0,withoutContact:0,quantitySources:{},statusCounts:{}};
  const privateRows=[];
  for(const lead of leads){
    const quantity=quantityOf(lead);if(quantity.source==='no-machine'){audit.noMachine++;continue;}
    const stage=stages.get(lead.status_id)||'';
    const sent=lead.status_id===142||/доставлен|получен|выдан|отправлен|отгружен|успеш/i.test(stage)||field(lead,/^(дата отправки|дата отгрузки|дата доставки|трек.?номер|номер накладной|номер отправления|штрихкод сдэк|cdek.?number)$/i).some(v=>String(v).trim());
    if(!sent){audit.excludedNoSale++;continue;}
    audit.matched++;audit.statusCounts[lead.status_id]=(audit.statusCounts[lead.status_id]||0)+1;
    const city=cityOf(lead);if(!city){audit.missingCity++;continue;}
    if(quantity.quantity===null){audit.missingQuantity++;continue;}
    const ref=lead._embedded?.contacts?.find(v=>v.is_main)||lead._embedded?.contacts?.[0];const contact=contactMap.get(ref?.id);
    const phones=contact?field(contact,/^телефон$/i).map(v=>String(v).replace(/\D/g,'')).filter(Boolean):[];
    const emails=contact?field(contact,/^(email|e-mail)$/i).map(v=>String(v).trim().toLowerCase()).filter(Boolean):[];
    let identity=phones[0]||emails[0]||(ref?'contact:'+ref.id:null);
    if(!identity){audit.withoutContact++;identity='order:'+lead.id;}
    identity=createHash('sha256').update(identity).digest('hex');
    const key=city.toLocaleLowerCase('ru').replace(/^г[.\s]+/,'').replace(/ё/g,'е').replace(/\s+/g,' ').trim();
    const row=aggregate.get(key)||{city:city.replace(/^г[.\s]+/i,'').trim(),units:0,clients:new Set(),orders:0};
    row.units+=quantity.quantity;row.orders++;row.clients.add(identity);aggregate.set(key,row);
    audit.quantitySources[quantity.source]=(audit.quantitySources[quantity.source]||0)+1;
    privateRows.push({id:lead.id,city:row.city,quantity:quantity.quantity,client:identity,status:lead.status_id});
  }
  return {audit,cities:[...aggregate.values()].map(v=>({...v,clients:v.clients.size})).sort((a,b)=>b.units-a.units||a.city.localeCompare(b.city,'ru')),privateRows};
}
async function main(){
  await mkdir(folder,{recursive:true,mode:0o700});let data;
  const mode=process.argv[2]||'profile';
  if(mode==='fetch'||mode==='profile'){
    const pipelines=await collection('/api/v4/leads/pipelines','pipelines');
    const leads=await collection('/api/v4/leads?with=contacts,catalog_elements&order[id]=asc','leads');
    const deleted=await collection('/api/v4/leads?with=only_deleted','leads');
    data={leads,pipelines,deleted,at:Date.now()};await writeFile(folder+'/raw.json',JSON.stringify(data),{mode:0o600});
  }else data=JSON.parse(await readFile(folder+'/raw.json','utf8'));
  if(mode==='report'){
    const contacts=await collection('/api/v4/contacts','contacts');
    const result=summarize(data.leads,contacts,data.pipelines);
    await writeFile(folder+'/audit.json',JSON.stringify(result.privateRows),{mode:0o600});delete result.privateRows;
    result.coverage=profile(data.leads,data.pipelines,data.deleted);
    // Only aggregate data. Never print rows, names, addresses, phones, links or tokens.
    await writeFile('/root/city-report-result.json',JSON.stringify(result),{mode:0o600});
  }else await writeFile('/root/city-report-result.json',JSON.stringify(profile(data.leads,data.pipelines,data.deleted)),{mode:0o600});
  console.log('READ_ONLY_REPORT_READY');
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href)main().catch(()=>{console.error('READ_ONLY_REPORT_FAILED');process.exitCode=1;});
