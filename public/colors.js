export function classification(order){
 if(order.classification)return order.classification;
 const items=(order.raw.entity.packages||[]).flatMap(p=>p.items||[]);const names=items.map(x=>x.name||'').join(' ');
 const sets=items.filter(x=>/комплект/iu.test(x.name||''));
 return {color:/светло[ -]син/iu.test(names)?'Светло-синий':'Не указан',quantity:items.length?items.reduce((s,x)=>s+Number(x.amount||0),0):null,unit:sets.length===items.length&&sets.length?'комплект':sets.length?'товарных ед. (есть комплекты)':items.length?'шт.':'не указано',name:names};
}
export function renderColors(orders,esc){
 const completed=orders.filter(o=>[...(o.raw.entity.statuses||[])].sort((a,b)=>Date.parse(b.date_time)-Date.parse(a.date_time))[0]?.code==='DELIVERED');
 if(!completed.length)return '';
 const groups=new Map();for(const o of completed){const c=classification(o),key=c.color+'|'+c.unit;const g=groups.get(key)||{color:c.color,unit:c.unit,orders:0,qty:0,unknown:0};g.orders++;if(c.quantity===null)g.unknown++;else g.qty+=c.quantity;groups.set(key,g)}
 const noQty=completed.filter(o=>classification(o).quantity===null).length,noColor=completed.filter(o=>classification(o).color==='Не указан').length;
 return `<div class="paneltitle"><h2>Завершённые · по цветам и количеству</h2></div><div class="colorcards">${[...groups.values()].sort((a,b)=>b.qty-a.qty).map(g=>`<article><span class="colorchip ${g.color==='Светло-синий'?'blue':'unknown'}"></span><b>${esc(g.color)}</b><strong>${g.unknown?'Не указано':g.qty+' '+esc(g.unit==='комплект'?'компл.':g.unit)}</strong><small>Заказов: ${g.orders}</small></article>`).join('')}</div><p class="colorNote">Вручённые отправления, включая входящие и возвратные. Комплекты считаются отдельно от изделий. Без количества: ${noQty} заказов. Без указанного цвета: ${noColor} заказов.</p>`;
}
