const hasSku=text=>/\([^()]*\S[^()]*\)/u.test(text);
const values=(lead,name)=>(lead.custom_fields_values||[])
  .filter(field=>[field.field_name,field.field_code].some(value=>value?.trim().toUpperCase()===name.toUpperCase()))
  .flatMap(field=>field.values||[]).map(entry=>entry.value)
  .filter(value=>typeof value==='string'||Number.isSafeInteger(value)).map(value=>String(value).trim()).filter(Boolean);

export function orderComposition(lead){
  const original=values(lead,'Состав заказа').join('\n');
  if(hasSku(original))return {composition:original,articleSource:'composition'};
  const products=values(lead,'PRODUCTS');
  const parts=[];
  for(const value of products){
    if(hasSku(value)){parts.push(value);continue;}
    // A bare SKU is usable; product titles without an explicit SKU are not.
    for(const line of value.split(/[;\n]+/)){
      const sku=line.trim();
      if(/^[\p{L}\p{N}_.-]+$/u.test(sku))parts.push('('+sku+')');
    }
  }
  const composition=parts.join('\n');
  return composition?{composition,articleSource:'products'}:{composition:original,articleSource:null};
}
