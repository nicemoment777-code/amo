export const day = seconds => new Date(seconds*1000).toLocaleDateString('sv-SE',{timeZone:'Europe/Moscow'});
export const stamp = (date,time='00:00') => Date.parse(`${date}T${time}:00+03:00`)/1000;
export const title = item => item.orderNumber ? `№ ${item.orderNumber}` : `amo ${item.id}`;
export function filterItems(items,{from,to,query='',carrier='all',skus=null,status='all'}) {
  return items.filter(v=>v.createdAt>=from && v.createdAt<=to && (carrier==='all'||v.deliveryService===carrier)
    && (!query||String(v.id).includes(query)||String(v.orderNumber||'').includes(query))
    && (!skus||v.skus.some(s=>skus.has(s))||(!v.skus.length&&skus.has('')))
    && (status==='all'||v.confirmed===(status==='printed')));
}
export function articleCounts(items) {
  const counts=new Map();
  for (const v of items) for (const sku of v.skus.length?v.skus:['']) {
    const value=counts.get(sku)||{count:0,printed:0,colors:v.colors}; value.count++; value.printed+=Number(v.confirmed); counts.set(sku,value);
  }
  return [...counts].sort((a,b)=>a[0].localeCompare(b[0],'ru'));
}
export function orderedGroups(items) {
  const groups=new Map();
  for (const item of new Map(items.map(v=>[String(v.id),v])).values()) {
    const key=JSON.stringify([...item.skus].sort()); const list=groups.get(key)||[]; list.push(item); groups.set(key,list);
  }
  return [...groups.values()].map(v=>v.sort((a,b)=>a.createdAt-b.createdAt||a.id-b.id))
    .sort((a,b)=>b.length-a.length||a[0].createdAt-b[0].createdAt||a[0].id-b[0].id).flat();
}

export function skuColors(skus) {
  const text=skus.join('; ').toLowerCase(),ink='#131936';
  if(!skus.length)return ['#e4e8ef',ink];
  if(skus.length===1)for(const [words,color,foreground] of [
    [['wsblue','голуб','sky','lightblue'],'#8bd7fa',ink],[['red','красн'],'#ff666d',ink],
    [['pink','розов'],'#f99bcf',ink],[['green','салат','зелён','зелен'],'#c1f48b',ink],
    [['blue','синий','синяя'],'#1255cf','#ffffff'],[['black','чёрн','черн'],'#3c424e','#ffffff'],
    [['yellow','жёлт','желт'],'#ffe19a',ink]])if(words.some(w=>text.includes(w)))return [color,foreground];
  let hash=0;for(const char of text)hash=(hash*31+char.codePointAt(0))>>>0;
  return ['hsl('+hash%360+' 70% 80%)',ink];
}
