import test from 'node:test';
import assert from 'node:assert/strict';
import {orderComposition} from './order-composition.mjs';
const lead=(composition,products)=>({custom_fields_values:[{field_name:'Состав заказа',values:[{value:composition}]},{field_code:'PRODUCTS',values:products.map(value=>({value}))}]});
test('composition SKU takes priority over PRODUCTS',()=>{
 assert.deepEqual(orderComposition(lead('Товар (PRIMARY) - 2',['Товар (OTHER) - 3'])),{composition:'Товар (PRIMARY) - 2',articleSource:'composition'});
});
test('PRODUCTS supplies SKUs when composition is empty or lacks parentheses',()=>{
 for(const composition of ['', 'Описание без артикула','(   )']){
  const result=orderComposition(lead(composition,['Товар (BLUE_1) - 2; Товар (RED_2) - 1']));
  assert.equal(result.articleSource,'products');assert.match(result.composition,/\(BLUE_1\)/);assert.match(result.composition,/\(RED_2\)/);
 }
});
test('PRODUCTS bare SKUs retain leading zeros and titles are not invented as SKU',()=>{
 assert.equal(orderComposition(lead('', ['00123; BLUE_1'])).composition,'(00123)\n(BLUE_1)');
 assert.equal(orderComposition(lead('', ['Название товара без артикула'])).articleSource,null);
});
