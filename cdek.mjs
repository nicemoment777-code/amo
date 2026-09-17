export class CdekClient {
  constructor(id, secret, request = fetch) { this.id=id; this.secret=secret; this.request=request; }
  async token() {
    if(this.access && Date.now()<this.expires) return this.access;
    if(!this.id || !this.secret) throw new Error('Не настроены ключи API СДЭК');
    const r=await this.request('https://api.cdek.ru/v2/oauth/token',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams({grant_type:'client_credentials',client_id:this.id,client_secret:this.secret}),signal:AbortSignal.timeout(30000)});
    if(!r.ok) throw new Error(`СДЭК: авторизация отклонена (${r.status})`);
    const j=await r.json(); if(!j.access_token) throw new Error('СДЭК не выдал токен');
    this.access=j.access_token; this.expires=Date.now()+(Number(j.expires_in || 3600)-60)*1000; return this.access;
  }
  async order(number, retry=true) {
    if(!/^\d{5,20}$/.test(number)) throw new Error('Нужен номер накладной СДЭК: 5–20 цифр');
    const r=await this.request('https://api.cdek.ru/v2/orders?cdek_number='+encodeURIComponent(number),{headers:{Authorization:'Bearer '+await this.token()},signal:AbortSignal.timeout(30000)});
    if(r.status===401 && retry){this.access=null;return this.order(number,false);}
    if(!r.ok) throw new Error(`СДЭК: ошибка ${r.status}`);
    const j=await r.json();
    if(!j.entity?.uuid) throw new Error('СДЭК не вернул доступный заказ');
    if(String(j.entity.cdek_number??number)!==number) throw new Error('СДЭК вернул другой номер накладной');
    return j;
  }
}
export function parseNumbers(text) {
  const values=String(text).split(/[\s,;]+/).filter(Boolean);
  if(!values.length || values.some(x=>!/^\d{5,20}$/.test(x))) throw new Error('Вставьте только номера накладных, разделённые пробелами, запятыми или строками');
  return [...new Set(values)];
}
export function latestStatus(entity) { return [...(entity.statuses||[])].sort((a,b)=>Date.parse(b.date_time)-Date.parse(a.date_time))[0]||{}; }
