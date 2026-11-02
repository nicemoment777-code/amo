import test from 'node:test';
import assert from 'node:assert/strict';
import {EventEmitter} from 'node:events';
import {PassThrough} from 'node:stream';
import {labelDownload} from './label-download.mjs';

test('label DNS fallback preserves HTTPS hostname and returns PDF',async()=>{
  const url=new URL('https://labels.example.test/file.pdf');let calls=0;
  const response=await labelDownload(url,{fetcher:async target=>{
    if(++calls===1)throw Object.assign(Error('DNS'),{cause:{code:'EAI_AGAIN'}});
    assert.match(String(target),/^https:\/\/dns.google\/resolve\?/);
    return Response.json({Status:0,Answer:[{type:1,data:'203.0.113.1'}]});
  },request:(target,options,callback)=>{
    assert.equal(target,url);assert.equal(options.rejectUnauthorized,undefined);
    options.lookup(url.hostname,{all:true},(error,addresses)=>assert.deepEqual(addresses,[{address:'203.0.113.1',family:4}]));
    const stream=new PassThrough();stream.statusCode=200;stream.headers={'content-type':'application/pdf'};
    callback(stream);queueMicrotask(()=>stream.end('%PDF-test'));return new EventEmitter();
  }});
  assert.equal(await response.text(),'%PDF-test');
});

test('TLS errors never use DNS fallback',async()=>{
  let calls=0;
  await assert.rejects(labelDownload(new URL('https://labels.example.test'),{fetcher:async()=>{calls++;throw Object.assign(Error('TLS'),{cause:{code:'CERT_HAS_EXPIRED'}});}}),/TLS/);
  assert.equal(calls,1);
});
