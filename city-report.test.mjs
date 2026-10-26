import {test} from 'node:test';
import assert from 'node:assert/strict';
import {quantityOf,summarize} from './ops/city-report.mjs';
const custom=(name,value)=>({field_name:name,values:[{value}]});
test('city report counts machine units, distinct buyers, closed sales and shipment evidence without inventing quantity',()=>{
  const lead=(id,city,composition,status=142)=>({id,status_id:status,custom_fields_values:[custom('Город доставки',city),custom('Состав заказа',composition)],_embedded:{contacts:[{id:1,is_main:true}]}});
  const leads=[lead(1,'Москва','Станочек Снегострой (A) — 2 шт.'),lead(2,'г. Москва','Станочек Снегострой (B) — 1 шт.'),lead(3,'Казань','Станочек Снегострой (A)'),lead(4,'Омск','Станочек Снегострой (A) — 5 шт.',143)];
  assert.equal(quantityOf(leads[0]).quantity,2);assert.equal(quantityOf(leads[2]).quantity,null);
  const result=summarize(leads,[],[]);assert.equal(result.cities[0].units,3);assert.equal(result.cities[0].clients,1);assert.equal(result.audit.missingQuantity,1);assert.equal(result.audit.excludedNoSale,1);
});
