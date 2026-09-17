import {timingSafeEqual} from 'node:crypto';
export function validWebhookKey(supplied,expected){
  if(!expected||expected.length<32||typeof supplied!=='string')return false;
  const a=Buffer.from(supplied),b=Buffer.from(expected);return a.length===b.length&&timingSafeEqual(a,b);
}
export function webhookOrder(body){
  if(body?.type!=='ORDER_STATUS')throw new Error('Поддерживается только ORDER_STATUS');
  const number=String(body.attributes?.cdek_number||'');
  if(!/^\d{5,20}$/.test(number))throw new Error('Нет корректного номера накладной');
  if(typeof body.uuid!=='string'||!/^[0-9a-f-]{36}$/i.test(body.uuid))throw new Error('Нет UUID заказа');
  return number;
}
