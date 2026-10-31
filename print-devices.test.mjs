import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';
import {createPrintDevices} from './print-devices.mjs';

test('device access needs owner approval, can be revoked and survives restart', async t => {
  const dir = await mkdtemp(join(tmpdir(), 'print-devices-')); t.after(() => rm(dir,{recursive:true,force:true}));
  const file = pathToFileURL(join(dir,'devices.json'));
  let now = 0; const devices = await createPrintDevices(file, {now:()=>now});
  const token = 'a'.repeat(43), tokenHash = createHash('sha256').update(token).digest('hex');
  const pair = devices.begin({tokenHash}, 'ip');
  assert.equal(devices.authorize(token), null);
  assert.equal(devices.poll(pair).approved,false);
  assert.throws(()=>devices.poll({...pair,pollSecret:'wrong'}));
  await devices.approve({code:pair.code,name:'Склад'});
  assert.equal(devices.poll(pair).approved,true);
  assert.equal(devices.authorize(token),tokenHash);
  const restarted = await createPrintDevices(file);
  assert.equal(restarted.authorize(token),tokenHash);
  await restarted.revoke(tokenHash); assert.equal(restarted.authorize(token),null);
  const expired = devices.begin({tokenHash},'ip'); now=600001;
  assert.throws(()=>devices.poll(expired));
  await assert.rejects(devices.approve({code:expired.code}));
});

test('two computers cannot claim one label, even after restart or interrupted print', async t => {
  const dir = await mkdtemp(join(tmpdir(), 'print-claims-')); t.after(()=>rm(dir,{recursive:true,force:true}));
  const file=pathToFileURL(join(dir,'devices.json')); const service=await createPrintDevices(file);
  const claims=await Promise.all([service.claim(123,'a'),service.claim(123,'b')]);
  assert.deepEqual(claims,[{claimed:true},{claimed:false}]);
  await assert.rejects(service.complete(123,'b'));
  const restart=await createPrintDevices(file);
  assert.deepEqual(await restart.claim(123,'b'),{claimed:false});
  await restart.complete(123,'a');
  assert.deepEqual(await restart.claim(123,'a'),{claimed:false});
  await assert.rejects(restart.claim('invalid','a'));
});

test('shared print history persists, imports idempotently, and never frees a claim', async t => {
  const dir=await mkdtemp(join(tmpdir(),'print-history-'));t.after(()=>rm(dir,{recursive:true,force:true}));
  const file=pathToFileURL(join(dir,'devices.json'));
  let service=await createPrintDevices(file,{now:()=>200000});
  await service.claim(12,'a');
  assert.equal(service.history().printed['12'],undefined);
  assert.equal(service.history().uncertain['12'].status,'reserved-on-server');
  const entry={id:'12',eventId:'a'.repeat(64),at:100,status:'submitted',printer:'P1',mode:'manual'};
  await service.record([entry],'b'); await service.record([entry],'b');
  assert.equal(service.history().events.length,1);
  assert.equal(service.history().printed['12'].status,'submitted');
  assert.deepEqual(await service.claim(12,'c'),{claimed:false});
  await assert.rejects(service.record([{...entry,printer:'P2'}],'b'));
  await assert.rejects(service.record([{...entry,eventId:'b'.repeat(64),status:'uncertain'}],'b'));
  service=await createPrintDevices(file);
  assert.equal(service.history().events.length,1);
  assert.equal(service.history().printed['12'].at,100);
});
