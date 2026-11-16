import {createServer} from 'node:http';
import {randomBytes,timingSafeEqual} from 'node:crypto';
import {mkdirSync,readFileSync,writeFileSync,renameSync,unlinkSync,existsSync} from 'node:fs';
import {join,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawn,execFileSync} from 'node:child_process';
import {defaults,validate} from './config.js';

const root=dirname(dirname(fileURLToPath(import.meta.url)));
const loopback=address=>['127.0.0.1','::1','::ffff:127.0.0.1'].includes(address);
const read=(path,fallback)=>{try{return JSON.parse(readFileSync(path,'utf8'));}catch(error){if(error.code==='ENOENT')return fallback;throw error;}};
function atomic(path,value){const pending=path+'.pending';writeFileSync(pending,JSON.stringify(value),{mode:0o600});renameSync(pending,path);}
const json=(res,code,value)=>{if(res.destroyed||res.writableEnded)return;res.writeHead(code,{'content-type':'application/json; charset=utf-8','cache-control':'no-store'});res.end(JSON.stringify(value));};
async function body(req,limit){let size=0;const chunks=[];for await(const b of req){size+=b.length;if(size>limit)throw Error('body-too-large');chunks.push(b);}return JSON.parse(Buffer.concat(chunks).toString('utf8'));}

export class VoiceHost {
  constructor(scope,{directory,launch=true}={}) {
    this.scope=scope;this.directory=directory;this.launch=launch;this.closed=false;this.pending=new Set();this.turn=null;
    this.runtime={phase:'off',devices:[],voices:[],microphone:false,lastError:null,synthesis:{engine:'cosyvoice3',phase:'off',error:null,device:null}};this.lastSeen=0;this.restarts=0;this.child=null;
    mkdirSync(directory,{recursive:true,mode:0o700});
    if(process.platform==='win32'){
      // Inherit only the current user's grants and SYSTEM. Never print the token.
      const sid=execFileSync('whoami.exe',['/user','/fo','csv','/nh'],{encoding:'utf8',windowsHide:true}).match(/S-1-[\d-]+/)[0];
      execFileSync('icacls.exe',[directory,'/inheritance:r','/grant:r','*'+sid+':(OI)(CI)(F)','*S-1-5-18:(OI)(CI)(F)'],{windowsHide:true,stdio:'pipe'});
    }
    this.settingsPath=join(directory,'settings.json');this.connectionPath=join(directory,'connection.json');
    const saved=read(this.settingsPath,{revision:0,settings:defaults});this.settings=validate(saved.settings);this.revision=saved.revision;
    this.token=randomBytes(32).toString('hex');
  }
  speech(){return this.scope.get?.('speechToText');}
  pet(){return this.scope.get?.('companionLanxi');}
  provider(){return this.speech()?.snapshot().providers.find(p=>p.id==='sensevoice-local'&&p.location==='host-local');}
  status(){
    let provider=null;try{provider=this.provider()??null;}catch{}
    return {version:1,revision:this.revision,settings:this.settings,recognizer:provider,officialAvailable:Boolean(this.speech()),pet:this.pet()?.snapshot()??null,runtime:{...this.runtime,connected:Date.now()-this.lastSeen<7000},workerRunning:Boolean(this.child&&!this.child.killed),platform:process.platform};
  }
  prepare(){const provider=this.provider();if(!provider)throw Error('official-recognizer-unavailable');this.speech().prepare(provider.id,{});return {status:'preparing'};}
  previewVoice(input){
    if(!this.settings.enabled||!this.pet()?.snapshot().enabled||this.runtime.synthesis?.phase!=='ready'||this.turn)throw Error('voice-not-ready');
    const settings=validate({...this.settings,voice:input.voice??'',rate:input.rate??this.settings.rate,volume:input.volume??this.settings.volume});
    this.preview={settings:{voice:settings.voice,rate:settings.rate,volume:settings.volume},expires:Date.now()+5000};return {status:'queued'};
  }
  async update(input){
    if(input.expectedRevision!==this.revision)return {status:'conflict',...this.status()};
    const settings=validate(input.settings);
    atomic(this.settingsPath,{revision:this.revision+1,settings});this.settings=settings;this.revision++;
    if(settings.enabled){try{this.prepare();}catch{}this.startWorker();}else{for(const pending of this.pending)pending.abort();this.pet()?.cancel(this.activeRequest);}
    return {status:'saved',...this.status()};
  }
  authenticated(req){
    if(req.headers.origin!==undefined||!loopback(req.socket.remoteAddress))return false;
    if(req.headers.host!=='127.0.0.1:'+this.port)return false;
    const a=Buffer.from(req.headers.authorization??''),b=Buffer.from('Bearer '+this.token);return a.length===b.length&&timingSafeEqual(a,b);
  }
  async start(){
    this.server=createServer((req,res)=>this.handle(req,res));
    await new Promise((resolve,reject)=>{this.server.once('error',reject);this.server.listen(0,'127.0.0.1',resolve);});this.port=this.server.address().port;
    if(this.closed){this.server.close();return this;}
    atomic(this.connectionPath,{version:1,origin:'http://127.0.0.1:'+this.port,token:this.token,pid:process.pid});
    if(this.launch){this.startWorker();this.watch=setInterval(()=>this.startWorker(),5000);this.watch.unref();}
    if(this.settings.enabled)try{this.prepare();}catch{}
    return this;
  }
  startWorker(){
    if(this.closed||!this.launch||process.platform!=='win32'||this.child||Date.now()<(this.nextStart??0))return;
    const python=join(root,'.venv','Scripts','python.exe');
    if(!existsSync(python)){this.runtime.lastError='python-runtime-missing';return;}
    const child=spawn(python,['-X','utf8',join(root,'native','worker.py'),'--connection',this.connectionPath],{windowsHide:true,stdio:['ignore','ignore','pipe']});this.child=child;
    let error='';child.stderr.on('data',chunk=>{error=(error+chunk.toString()).slice(-1500);});
    child.on('error',()=>{this.runtime.lastError='worker-start-failed';});
    child.on('exit',()=>{if(this.child===child)this.child=null;if(!this.closed){this.runtime={...this.runtime,microphone:false,phase:'error',lastError:'worker-exited'};this.nextStart=Date.now()+Math.min(30000,1000*2**Math.min(this.restarts++,5));}});
  }
  async handle(req,res){
    if(!this.authenticated(req)){json(res,403,{error:'authentication'});return;}
    if(req.method!=='POST'){json(res,405,{error:'method'});return;}
    const controller=new AbortController();this.pending.add(controller);res.on('close',()=>{if(!res.writableEnded)controller.abort();});
    try{
      const input=await body(req,6*1024*1024);controller.signal.throwIfAborted();
      let result;
      switch(req.url){
        case '/heartbeat': {
          if(!input||typeof input!=='object')throw Error('invalid-heartbeat');
          this.lastSeen=Date.now();this.restarts=0;
          this.runtime={phase:String(input.phase??'off').slice(0,40),microphone:input.microphone===true,lastError:typeof input.lastError==='string'?input.lastError.slice(0,160):null,
            devices:Array.isArray(input.devices)?input.devices.slice(0,120).filter(v=>Number.isInteger(v.id)&&typeof v.name==='string').map(v=>({id:v.id,name:v.name.slice(0,160)})):[],
            voices:Array.isArray(input.voices)?input.voices.slice(0,100).filter(v=>typeof v==='string').map(v=>v.slice(0,160)):[],
            synthesis:{engine:'cosyvoice3',phase:['off','loading','ready','error'].includes(input.synthesis?.phase)?input.synthesis.phase:'off',error:typeof input.synthesis?.error==='string'?input.synthesis.error.slice(0,160):null,device:typeof input.synthesis?.device==='string'?input.synthesis.device.slice(0,160):null}};
          result=this.status();if(this.preview?.expires>Date.now()&&this.settings.enabled)result.preview=this.preview;this.preview=null;break;
        }
        case '/asr': {
          if(!this.settings.enabled||!this.pet()?.snapshot().enabled)throw Error('voice-disabled');
          const service=this.speech(),provider=this.provider();if(!service||!provider)throw Error('official-recognizer-unavailable');
          const audio=Buffer.from(input.audioBase64??'','base64');validateWave(audio);
          const spec=service.resolve({audio,language:'zh',providerId:provider.id});
          const transcript=await service.transcribe(spec,controller.signal);result={text:transcript.text??''};break;
        }
        case '/announce': {
          // Fixed wake acknowledgement only; this route cannot publish arbitrary text.
          if(!this.settings.enabled)throw Error('voice-disabled');this.pet()?.announce('我在。');result={status:'ready'};break;
        }
        case '/command': {
          if(!this.settings.enabled)throw Error('voice-disabled');const pet=this.pet();if(!pet)throw Error('pet-unavailable');
          if(this.turn){result={status:'busy',text:'上一条指令尚未结束。'};break;}
          this.turn=controller;this.activeRequest=input.requestId;
          try{this.turnDone=Promise.resolve(pet.command({requestId:input.requestId,text:input.text},()=>!this.closed&&this.settings.enabled&&!controller.signal.aborted));result=await this.turnDone;}
          finally{if(this.turn===controller){this.turn=null;this.turnDone=null;this.activeRequest=null;}}break;
        }
        case '/cancel': {
          this.turn?.abort();this.pet()?.cancel(this.activeRequest);
          if(this.turnDone)await Promise.race([this.turnDone.catch(()=>{}),new Promise(r=>{const timer=setTimeout(r,2500);timer.unref();})]);
          result={status:this.turn?'cancelling':'cancelled'};break;
        }
        default: json(res,404,{error:'route'});return;
      }
      json(res,200,result);
    }catch(error){json(res,error.message==='body-too-large'?413:400,{error:['body-too-large','voice-disabled','official-recognizer-unavailable','invalid-wave','pet-unavailable'].includes(error.message)?error.message:controller.signal.aborted?'cancelled':'request-failed'});}
    finally{this.pending.delete(controller);}
  }
  async close(){
    if(this.closing)return this.closing;
    this.closing=this.dispose();return this.closing;
  }
  async dispose(){
    this.closed=true;clearInterval(this.watch);for(const controller of this.pending)controller.abort();this.pet()?.cancel(this.activeRequest);
    // Worker heartbeats see connection removal; terminating our own child also releases PortAudio.
    try{if(read(this.connectionPath,null)?.token===this.token)unlinkSync(this.connectionPath);}catch{}
    const child=this.child;
    if(child&&child.exitCode===null)await new Promise(resolve=>{const timer=setTimeout(()=>{if(process.platform==='win32'){try{execFileSync('taskkill.exe',['/PID',String(child.pid),'/T','/F'],{windowsHide:true,stdio:'pipe'});}catch{child.kill();}}else child.kill();resolve();},7000);child.once('exit',()=>{clearTimeout(timer);resolve();});});
    if(this.server?.listening){this.server.closeAllConnections();await new Promise(r=>this.server.close(r));}
  }
}

export function validateWave(audio){
  if(audio.length<44||audio.length>4*1024*1024||audio.toString('ascii',0,4)!=='RIFF'||audio.toString('ascii',8,12)!=='WAVE'||audio.toString('ascii',12,16)!=='fmt '||audio.readUInt32LE(16)!==16||audio.readUInt16LE(20)!==1||audio.readUInt16LE(22)!==1||audio.readUInt32LE(24)!==16000||audio.readUInt16LE(34)!==16||audio.toString('ascii',36,40)!=='data'||audio.readUInt32LE(40)!==audio.length-44||audio.readUInt32LE(4)!==audio.length-8||audio.length%2)throw Error('invalid-wave');
}

export function registerWeb(scope,host){
  const prefix='/api/dsh-companion-voice/';
  function sameOrigin(req){
    try{
      const expected=new URL(scope.webServer.getOrigin());
      if(req.headers.host!==expected.host||req.headers['x-lanxi-request']!=='1')return false;
      if(req.headers.origin!==undefined)return new URL(req.headers.origin).origin===expected.origin;
      // DSH's native transport can omit Origin; only accept local requests
      // with the custom header and no foreign browser fetch context.
      return loopback(req.socket.remoteAddress)&&!['cross-site','same-site'].includes(req.headers['sec-fetch-site']);
    }catch{return false;}
  }
  for(const name of ['status','settings','prepare','preview','settings.js']){
    const stop=scope.webServer.register({kind:'exact',path:prefix+name,async handler(req,res){
      if(name==='settings.js'&&['GET','HEAD'].includes(req.method)){res.writeHead(200,{'content-type':'text/javascript; charset=utf-8','cache-control':'no-cache'});res.end(req.method==='HEAD'?undefined:readFileSync(join(root,'lib','settings.js')));return;}
      if(name==='status'&&req.method==='GET'){json(res,200,host.status());return;}
      if(req.method!=='POST'||!sameOrigin(req)){json(res,403,{error:'authentication'});return;}
      try{const input=await body(req,16384);json(res,200,name==='settings'?await host.update(input):name==='prepare'?host.prepare():name==='preview'?host.previewVoice(input):host.status());}catch{json(res,400,{error:'invalid-request'});}
    }});scope.effect(()=>stop);
  }
}
