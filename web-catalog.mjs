import {skuColors} from './public/printer-model.js';
export function webCatalog(items,history) {
  return items.map(item=>{
    const skus=[...new Set([...String(item.composition||'').matchAll(/\(([^()]*)\)/g)].map(v=>v[1].trim()).filter(Boolean))].sort();
    const key=String(item.id),confirmed=!!history.printed[key],reserved=!!history.uncertain[key],reasons=[];
    if(!skus.length)reasons.push('В составе заказа нет артикула в круглых скобках.');
    if(!item.hasLabel)reasons.push('В заявке не заполнена этикетка доставки.');
    if(reserved)reasons.push('Отправка зарезервирована; подтверждение драйвера не получено. Проверьте очередь Windows.');
    return {id:item.id,orderNumber:item.orderNumber,createdAt:item.createdAt,deliveryService:item.deliveryService,
      hasLabel:!!item.hasLabel,skus,colors:skuColors(skus),confirmed,statusText:confirmed?'Передано драйверу':reserved?'Печать не подтверждена':'Не напечатано',
      canPrint:!!(skus.length&&item.hasLabel&&!reserved),reasons};
  });
}
