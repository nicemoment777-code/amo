import test from 'node:test';
import assert from 'node:assert/strict';
import {deliveryInfo} from './delivery-service.mjs';
const lead = fields => ({custom_fields_values:Object.entries(fields).map(([field_name,value])=>({field_name,values:[{value}]}))});
test('delivery filters classify CRM fields and never use CDEK label for a Yandex order', () => {
  assert.deepEqual(deliveryInfo(lead({DELIVERY:'СДЭК: ПВЗ','Этикетка ШК СДЭК':'https://files.test/cdek.pdf'})),{service:'cdek',label:'https://files.test/cdek.pdf'});
  assert.deepEqual(deliveryInfo(lead({DELIVERY:'Яндекс Доставка: ПВЗ','Этикетка ШК СДЭК':'https://files.test/stale.pdf'})),{service:'yandex',label:''});
  assert.deepEqual(deliveryInfo(lead({DELIVERY:'Yandex delivery','Этикетка ШК Яндекс':'https://files.test/yandex.pdf'})),{service:'yandex',label:'https://files.test/yandex.pdf'});
  assert.equal(deliveryInfo(lead({'Этикетка ШК СДЭК':'https://files.test/cdek.pdf'})).service,'cdek');
  assert.deepEqual(deliveryInfo(lead({DELIVERY:'Самовывоз'})),{service:'unknown',label:''});
  assert.deepEqual(deliveryInfo(lead({DELIVERY:'CDEK / Яндекс','Этикетка ШК СДЭК':'https://files.test/cdek.pdf'})),{service:'unknown',label:''});
});
