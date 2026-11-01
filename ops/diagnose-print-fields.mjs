// Read-only CRM diagnosis. Never print IDs, field values, URLs or tokens.
import {readFile} from 'node:fs/promises';
const id=process.argv[2];
if(!/^\d+$/.test(id||''))throw Error('Invalid diagnostic input');
const stored=JSON.parse(await readFile('/var/lib/amo/amocrm.json','utf8'));
const response=await fetch('https://snegostroy.amocrm.ru/api/v4/leads/'+id,{headers:{Authorization:'Bearer '+stored.accessToken},redirect:'error',signal:AbortSignal.timeout(30000)});
if(!response.ok)throw Error('CRM diagnostic HTTP '+response.status);
const lead=await response.json(),fields=lead.custom_fields_values||[];
const text=f=>(f.values||[]).map(v=>typeof v.value==='string'?v.value:'').join('\n').trim();
const value=name=>fields.filter(f=>f.field_name?.trim().toLowerCase()===name).map(text).join('\n');
const shipping=fields.filter(f=>/^(delivery|служба доставки|способ доставки|тип доставки|доставка)$/i.test(f.field_name?.trim()||'')).map(text).join('\n');
const box=/boxberry|боксбер[ри]/i;
const cdekLabel=value('этикетка шк сдэк'),boxberryLabel=value('этикетка boxberry');
const validLink=value=>{try{return new URL(value).protocol==='https:';}catch{return false;}};
console.log(JSON.stringify({shippingCdek:/сдэк|cdek|sdek/i.test(shipping),shippingYandex:/яндекс|yandex/i.test(shipping),shippingBoxberry:box.test(shipping),
  cdekLabel:validLink(cdekLabel),boxberryLabel:validLink(boxberryLabel),yandexLabel:fields.some(f=>/яндекс|yandex/i.test(f.field_name||'')&&/этикет|ярлык|штрихкод|\bшк\b/i.test(f.field_name||'')&&validLink(text(f))),
  boxberryInTitle:box.test(lead.name||''),boxberryInTags:box.test((lead._embedded?.tags||[]).map(v=>v.name).join('\n')),
  boxberryInOtherFields:fields.some(f=>box.test(text(f))&&!/^(delivery|служба доставки|способ доставки|тип доставки|доставка|этикетка boxberry)$/i.test(f.field_name?.trim()||''))}));
