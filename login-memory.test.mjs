import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {runInNewContext} from 'node:vm';
const source=await readFile(new URL('./public/login.js',import.meta.url),'utf8');
function page({hash='',stored=null,blocked=false}={}){
  const nodes=Object.fromEntries(['loginForm','password','togglePassword','rememberLogin','forgetLogin'].map(id=>[id,{value:'',hidden:true,checked:false,events:{},addEventListener(name,fn){this.events[name]=fn;},focus(){}}]));
  nodes.loginForm.username={value:'admin'};
  const state={stored,replaced:null,requests:0};
  runInNewContext(source,{document:{querySelector:s=>nodes[s.slice(1)]},location:{hash,pathname:'/login',search:''},history:{replaceState:(_,__,path)=>state.replaced=path},URLSearchParams,localStorage:{getItem(){if(blocked)throw Error();return state.stored;},setItem(_,v){if(blocked)throw Error();state.stored=v;},removeItem(){state.stored=null;}},fetch(){state.requests++;throw Error('Unexpected network request');}});
  return {nodes,state};
}
test('personal link fills and remembers credentials, strips fragment before network activity',()=>{
  const {nodes,state}=page({hash:'#user=admin&key=example-private-pass'});
  assert.equal(nodes.password.value,'example-private-pass');assert.equal(nodes.rememberLogin.checked,true);
  assert.equal(state.replaced,'/login');assert.equal(state.requests,0);
  assert.deepEqual(JSON.parse(state.stored),{username:'admin',password:'example-private-pass'});
  const next=page({stored:state.stored});assert.equal(next.nodes.password.value,'example-private-pass');
  next.nodes.forgetLogin.events.click();assert.equal(next.state.stored,null);assert.equal(next.nodes.password.value,'');
});
test('ordinary visitors receive no shared password and malformed links are not remembered',()=>{
  assert.equal(page().nodes.password.value,'');
  const invalid=page({hash:'#user=admin&key='});assert.equal(invalid.nodes.password.value,'');assert.equal(invalid.state.stored,null);
});
test('private storage restrictions do not prevent filling from a personal link',()=>{
  const {nodes,state}=page({hash:'#user=admin&key=example-private-pass',blocked:true});
  assert.equal(nodes.password.value,'example-private-pass');assert.equal(state.replaced,'/login');
});
