// Return only a service identifier and the selected private label internally.
// Raw delivery fields can contain addresses and must not leave the CRM service.
export function deliveryInfo(lead) {
  const fields = lead.custom_fields_values || [];
  const text = field => (field.values || []).map(v => v.value).filter(v => typeof v === 'string').join('\n').trim();
  const boxberryLabel = fields.find(f => f.field_name?.trim().toLowerCase() === 'этикетка boxberry');
  const yandexLabel = fields.find(f => /яндекс|yandex/i.test(f.field_name || '') && /этикет|ярлык|штрихкод|\bшк\b/i.test(f.field_name || ''));
  const mentions = [lead.name || '', ...(lead._embedded?.tags || []).map(tag => tag.name || ''),
    ...fields.filter(f => text(f)).map(f => `${f.field_name || ''}\n${text(f)}`)].join('\n');
  // В этом аккаунте заполненная этикетка Boxberry означает Яндекс Доставку.
  if (/boxberry|боксбер[ри]/i.test(mentions)) return {service:'yandex', label:text(boxberryLabel || {}) || text(yandexLabel || {})};
  const shipping = fields.filter(f => /^(delivery|служба доставки|способ доставки|тип доставки|доставка)$/i.test(f.field_name?.trim() || '')).map(text).join('\n');
  const yandex = /яндекс|yandex/i.test(shipping), cdek = /сдэк|cdek|sdek/i.test(shipping);
  const cdekLabel = fields.find(f => f.field_name?.trim().toLowerCase() === 'этикетка шк сдэк');
  let service = yandex && !cdek ? 'yandex' : cdek && !yandex ? 'cdek' : 'unknown';
  if (!yandex && !cdek) {
    if (/сдэк|cdek|sdek/i.test(mentions)) service = 'cdek';
    if (text(cdekLabel || {}) && !text(yandexLabel || {})) service = 'cdek';
    if (text(yandexLabel || {}) && !text(cdekLabel || {})) service = 'yandex';
  }
  const label = service === 'cdek' ? text(cdekLabel || {}) : service === 'yandex' ? text(yandexLabel || {}) : '';
  return {service, label};
}
