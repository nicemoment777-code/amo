import {test} from 'node:test';
import assert from 'node:assert/strict';
import {quantityOf,summarize,cityOf} from './ops/city-report.mjs';
const custom=(name,value)=>({field_name:name,values:[{value}]});
test('city report counts machine units, distinct buyers, closed sales and shipment evidence without inventing quantity',()=>{
  const lead=(id,city,composition,status=142)=>({id,status_id:status,custom_fields_values:[custom('Город доставки',city),custom('Состав заказа',composition)],_embedded:{contacts:[{id:1,is_main:true}]}});
  const leads=[lead(1,'Москва','Станочек Снегострой (A) — 2 шт.'),lead(2,'г. Москва','Станочек Снегострой (B) — 1 шт.'),lead(3,'Казань','Станочек Снегострой (A)'),lead(4,'Омск','Станочек Снегострой (A) — 5 шт.',143)];
  assert.equal(quantityOf(leads[0]).quantity,2);assert.equal(quantityOf(leads[2]).quantity,null);
  const result=summarize(leads,[],[]);assert.equal(result.cities[0].units,3);assert.equal(result.cities[0].clients,1);assert.equal(result.audit.missingQuantity,1);assert.equal(result.audit.excludedNoSale,1);
});
test('historic product quantities multiply bundle contents, never price or accessory',()=>{
  const lead={custom_fields_values:[custom('PRODUCTS','Комплект из 2 станочков (bundle) - 3x4990 = 14970;\nКрасный снегострой + нож-пила в подарок (single), шт - 2x2990 = 5980'),custom('Состав заказа','Красный снегострой (single), шт - 2')]};
  assert.equal(quantityOf(lead).quantity,8);
  assert.equal(cityOf({custom_fields_values:[custom('DELIVERY_ADDRESS','RU: Нижний Новгород Пункт выдачи: ул. Тестовая, 1 (RU, Нижний Новгород, ул. Тестовая)123456')]}),'Нижний Новгород');
});
