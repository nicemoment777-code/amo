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
  const names=[
    ['wsblue|light[ _-]*blue|sky[ _-]*blue|голуб[а-яё]*|небесн[а-яё]*|sky','#8bd7fa',ink],
    ['dark[ _-]*blue|navy|т[её]мно[ _-]*син[а-яё]*','#142346','#ffffff'],
    ['lime|лайм[а-яё]*|салатов[а-яё]*','#a3e635',ink],
    ['red|красн[а-яё]*','#ff666d',ink],['pink|розов[а-яё]*','#f99bcf',ink],
    ['green|салат[а-яё]*|зел[её]н[а-яё]*','#c1f48b',ink],
    ['blue|син[а-яё]*','#1255cf','#ffffff'],['black|ч[её]рн[а-яё]*','#3c424e','#ffffff'],
    ['yellow|ж[её]лт[а-яё]*','#ffe19a',ink],['white|бел[а-яё]*','#ffffff',ink],
    ['gray|grey|сер[а-яё]*','#b7bdc7',ink],['orange|оранж[а-яё]*','#ffad42',ink],
    ['purple|violet|фиолет[а-яё]*','#a58bdc',ink]
  ];
  // One match consumes a compound colour, so darkblue/lightblue do not add blue again.
  const pattern=new RegExp(names.map(([words],index)=>`(?<c${index}>${words})`).join('|'),'gu');
  const found=[];
  for(const match of text.matchAll(pattern)){
    const index=names.findIndex((_,i)=>match.groups['c'+i]!==undefined),value=names[index];
    if(!found.some(v=>v[1]===value[1]))found.push(value);
  }
  if(found.length>1)return [`linear-gradient(45deg, ${found.map(v=>v[1]).join(', ')})`,ink];
  if(found.length)return [found[0][1],found[0][2]];
  let hash=0;for(const char of text)hash=(hash*31+char.codePointAt(0))>>>0;
  return ['hsl('+hash%360+' 70% 80%)',ink];
}

export const orderColors = item => item.confirmed ? skuColors(item.skus) : ['#ff666d','#131936'];
