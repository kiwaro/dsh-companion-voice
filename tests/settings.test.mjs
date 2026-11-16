import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {mkdtempSync,rmSync,readFileSync,mkdirSync} from 'node:fs';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {chromium} from 'playwright';
import {VoiceHost,registerWeb} from '../lib/host.js';

test('voice card renders with pet theme, saves settings, handles conflicts and narrow screens',async()=>{
 const dir=mkdtempSync(join(tmpdir(),'voice-settings-')),routes=new Map(),cleanups=[];
 const host=new VoiceHost({get:name=>name==='companionLanxi'?{snapshot:()=>({enabled:true}),cancel(){}}:undefined},{directory:dir,launch:false});
 host.runtime.devices=[{id:14,name:'测试麦克风'}];host.runtime.voices=['CosyVoice · 官方参考女声'];host.runtime.synthesis={engine:'cosyvoice3',phase:'ready',error:null,device:'test-gpu'};
 registerWeb({webServer:{getOrigin:()=>origin,register(route){routes.set(route.path,route.handler);return()=>routes.delete(route.path);}},effect(fn){cleanups.push(fn());}},host);
 // Reuse the actual pet theme CSS, not an imitation of its styles.
 const client=readFileSync(new URL('../../dsh-companion-lanxi/lib/client.js',import.meta.url),'utf8');
 const css=client.match(/h\('style',null,`([\s\S]*?\.lx-settings[\s\S]*?)`\)/)?.[1];assert(css,'Pet settings theme unavailable');
 const html=`<!doctype html><meta charset="utf-8"><style>body{margin:24px;background:#faf9f5;font-family:"Segoe UI","Microsoft YaHei",sans-serif}${css}</style><div class="lx-settings"><div id="mount"></div></div><script src="/react.js"></script><script src="/react-dom.js"></script><script type="module">import{createVoiceManagement}from'/api/dsh-companion-voice/settings.js';ReactDOM.createRoot(document.getElementById('mount')).render(React.createElement(createVoiceManagement(React)));</script>`;
 const server=createServer((req,res)=>{const path=new URL(req.url,'http://local').pathname;if(routes.has(path))return routes.get(path)(req,res);const file=({'/react.js':'../node_modules/react/umd/react.development.js','/react-dom.js':'../node_modules/react-dom/umd/react-dom.development.js'})[path];res.setHeader('content-type',file?'text/javascript':'text/html; charset=utf-8');res.end(file?readFileSync(new URL(file,import.meta.url)):html);});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const origin='http://127.0.0.1:'+server.address().port;
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 try{
  const page=await browser.newPage({viewport:{width:1000,height:850}}),errors=[];page.on('pageerror',e=>errors.push(String(e)));
  await page.goto('http://127.0.0.1:'+server.address().port);
  await page.getByRole('heading',{name:'宠物语音'}).waitFor();
  assert.equal(await page.getByRole('textbox').count(),1,'Only the wake-word setting is editable text; no chat composer');
  await page.getByRole('checkbox',{name:'启用语音'}).check();await page.getByLabel('唤醒词',{exact:true}).fill('嗨大肥鱼，大肥鱼');
  await page.getByLabel('语音麦克风').selectOption('测试麦克风');await page.getByRole('button',{name:'保存语音设置'}).click();
  await page.getByText('语音设置已保存。',{exact:true}).waitFor();assert.equal(host.settings.enabled,true);assert.equal(host.settings.device,'测试麦克风');
  await page.getByRole('button',{name:'试听音色'}).click();await page.getByText('正在试听当前音色。',{exact:true}).waitFor();assert(host.preview);
  await page.getByLabel('唤醒词',{exact:true}).fill('小鲸鱼');
  await host.update({expectedRevision:host.revision,settings:{...host.settings,volume:60}});
  await page.getByRole('button',{name:'保存语音设置'}).click();await page.getByText('设置已在其他页面修改，已载入当前版本，请核对后再保存。',{exact:true}).waitFor();
  assert.deepEqual(host.settings.wakeWords,['嗨大肥鱼','大肥鱼']);
  await page.setViewportSize({width:390,height:844});assert(await page.locator('.lx-settings').evaluate(e=>e.scrollWidth<=e.clientWidth+1));
  mkdirSync(new URL('../qa',import.meta.url),{recursive:true});await page.screenshot({path:new URL('../qa/voice-settings-narrow.png',import.meta.url).pathname.replace(/^\/(\w:)/,'$1'),fullPage:true});
  await page.setViewportSize({width:1000,height:850});await page.screenshot({path:new URL('../qa/voice-settings.png',import.meta.url).pathname.replace(/^\/(\w:)/,'$1'),fullPage:true});
  assert.deepEqual(errors,[]);
 }finally{await browser.close();for(const cleanup of cleanups)cleanup();await host.close();await new Promise(r=>server.close(r));rmSync(dir,{recursive:true,force:true});}
});
