import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,readFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {VoiceHost,validateWave,registerWeb} from '../lib/host.js';
import {createServer,request} from 'node:http';
import {defaults,validate} from '../lib/config.js';

function wav(){const b=Buffer.alloc(3244);b.write('RIFF');b.writeUInt32LE(b.length-8,4);b.write('WAVEfmt ',8);b.writeUInt32LE(16,16);b.writeUInt16LE(1,20);b.writeUInt16LE(1,22);b.writeUInt32LE(16000,24);b.writeUInt32LE(32000,28);b.writeUInt16LE(2,32);b.writeUInt16LE(16,34);b.write('data',36);b.writeUInt32LE(b.length-44,40);return b;}

test('settings accepts local native transport while rejecting foreign origins and cross-site requests',async()=>{
  const dir=mkdtempSync(join(tmpdir(),'voice-origin-')),routes=new Map();
  const host=new VoiceHost({get(){}},{directory:dir,launch:false});
  const server=createServer((req,res)=>routes.get(new URL(req.url,'http://local').pathname)(req,res));
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const origin='http://127.0.0.1:'+server.address().port;
  registerWeb({webServer:{getOrigin:()=>origin,register(route){routes.set(route.path,route.handler);return()=>{};}},effect(){}},host);
  const post=(headers={})=>fetch(origin+'/api/dsh-companion-voice/settings',{method:'POST',headers:{'content-type':'application/json','x-lanxi-request':'1',...headers},body:JSON.stringify({expectedRevision:host.revision,settings:defaults})});
  try{
    assert.equal((await post()).status,200,'Native DSH requests may omit Origin');
    assert.equal((await post({origin})).status,200);
    assert.equal((await post({origin:'http://foreign.example'})).status,403);
    assert.equal((await post({origin:origin.replace('http:','https:')})).status,403);
    assert.equal((await post({origin:'null'})).status,403);
    assert.equal((await post({'sec-fetch-site':'cross-site'})).status,403);
    assert.equal((await post({'sec-fetch-site':'same-site'})).status,403);
    assert.equal((await post({'x-lanxi-request':''})).status,403);
    const foreignHost=await new Promise((resolve,reject)=>{const req=request(origin+'/api/dsh-companion-voice/settings',{method:'POST',headers:{host:'foreign.example','x-lanxi-request':'1'}},res=>{res.resume();resolve(res.statusCode);});req.on('error',reject);req.end('{}');});
    assert.equal(foreignHost,403);
  }finally{await host.close();await new Promise(resolve=>server.close(resolve));rmSync(dir,{recursive:true,force:true});}
});
test('configuration and WAV validation reject ambiguous settings and broken audio',()=>{
  assert.throws(()=>validate({...defaults,wakeWords:[]}));assert.throws(()=>validate({...defaults,endpoint:'cloud'}));
  assert.deepEqual(validate({...defaults,wakeWords:['嗨大肥鱼','嗨大肥鱼']}).wakeWords,['嗨大肥鱼']);
  validateWave(wav());const broken=wav();broken.writeUInt32LE(3,40);assert.throws(()=>validateWave(broken));
});
test('private transport, local recognizer, profile settings and cancellation',async()=>{
  const dir=mkdtempSync(join(tmpdir(),'pet-voice-'));let recognized=0,commands=0,cancelled=0;
  const pet={snapshot:()=>({enabled:true}),announce(){},async command(request,valid){assert(valid());commands++;return {status:'ready',text:'测试完成'};},cancel(id){if(id)cancelled++;}};
  const speech={snapshot:()=>({providers:[{id:'sensevoice-local',location:'host-local',preparation:{phase:'ready'}},{id:'cloud',location:'cloud'}]}),prepare(){},resolve(request){assert.equal(request.providerId,'sensevoice-local');return request;},async transcribe(){recognized++;return {text:'嗨大肥鱼'};}};
  const host=new VoiceHost({get:name=>name==='speechToText'?speech:name==='companionLanxi'?pet:undefined},{directory:dir,launch:false});
  try{
    await host.start();const connection=JSON.parse(readFileSync(host.connectionPath));const origin=connection.origin;
    const post=(path,data={},headers={})=>fetch(origin+path,{method:'POST',headers:{authorization:'Bearer '+connection.token,'content-type':'application/json',...headers},body:JSON.stringify(data)});
    assert.equal((await post('/asr',{},{authorization:'bad'})).status,403);
    assert.equal((await post('/asr',{}, {origin})).status,403);
    assert.equal((await post('/asr')).status,400);assert.equal(recognized,0);
    const enabled=await host.update({expectedRevision:0,settings:{...defaults,enabled:true}});assert.equal(enabled.status,'saved');
    assert.equal((await host.update({expectedRevision:0,settings:defaults})).status,'conflict');
    assert.equal((await (await post('/asr',{audioBase64:wav().toString('base64')})).json()).text,'嗨大肥鱼');assert.equal(recognized,1);
    assert.equal((await (await post('/command',{requestId:'voice:test',text:'问题'})).json()).text,'测试完成');assert.equal(commands,1);
    assert(!JSON.stringify(host.status()).includes(connection.token));
    assert.throws(()=>host.previewVoice({}),/voice-not-ready/);
    await post('/heartbeat',{phase:'standby',synthesis:{phase:'ready',device:'test-gpu'}});
    assert.equal(host.previewVoice({voice:'',rate:2,volume:70}).status,'queued');
    const preview=await (await post('/heartbeat',{phase:'standby',synthesis:{phase:'ready'}})).json();
    assert.equal(preview.preview.settings.rate,2);
    assert.equal((await (await post('/heartbeat',{})).json()).preview,undefined);
    let release;pet.command=async(_,valid)=>{await new Promise(r=>release=r);assert(!valid());return {status:'cancelled'};};
    const active=post('/command',{requestId:'voice:cancel',text:'问题'});while(!release)await new Promise(r=>setTimeout(r,5));
    await post('/cancel');release();assert.equal((await (await active).json()).status,'cancelled');assert.equal(cancelled,1);
    await host.update({expectedRevision:1,settings:defaults});assert.equal((await post('/command',{requestId:'voice:off',text:'问题'})).status,400);
  }finally{await host.close();rmSync(dir,{recursive:true,force:true});}
});
