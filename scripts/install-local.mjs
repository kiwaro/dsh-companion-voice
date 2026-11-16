/** Register this local checkout without stopping DSH or rewriting unrelated profile entries. */
import {readFileSync,writeFileSync,copyFileSync,existsSync,lstatSync,realpathSync,mkdirSync} from 'node:fs';
import {join,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {homedir} from 'node:os';
import {execFileSync} from 'node:child_process';

if(process.platform!=='win32')throw Error('本地部署脚本仅支持 Windows。');
const root=dirname(dirname(fileURLToPath(import.meta.url)));
const profile=process.argv[2]??join(homedir(),'.dsh','profiles','desktop');
const target=join(profile,'node_modules','dsh-companion-voice');
if(!existsSync(join(profile,'cordis.patch.yml')))throw Error('未找到 DSH profile。');
if(!existsSync(join(root,'.venv','Scripts','python.exe')))throw Error('请先运行 scripts/setup.ps1。');
if(existsSync(target)){
  if(!lstatSync(target).isSymbolicLink()||realpathSync(target).toLowerCase()!==realpathSync(root).toLowerCase())throw Error('已存在其他插件安装，未覆盖。');
}else execFileSync('cmd.exe',['/d','/c','mklink','/J',target,root],{windowsHide:true,stdio:'pipe'});
const patchPath=join(profile,'cordis.patch.yml');let patch=readFileSync(patchPath,'utf8');const manifestPath=join(profile,'package.json');const manifest=JSON.parse(readFileSync(manifestPath,'utf8'));
const officialBundle=manifest.dsh?.profile?.bundles?.includes('@deepseek-ai/dsh-experimental-voice-input-bundle');
const entries=[];
if(!officialBundle&&!patch.includes("name: '@deepseek-ai/dsh-experimental-speech-to-text'"))entries.push("    - id: pet-voice-official-service\n      name: '@deepseek-ai/dsh-experimental-speech-to-text'\n      config:\n        defaultProvider: sensevoice-local");
if(!officialBundle&&!patch.includes("name: '@deepseek-ai/dsh-experimental-speech-to-text-sensevoice'"))entries.push("    - id: pet-voice-official-recognizer\n      name: '@deepseek-ai/dsh-experimental-speech-to-text-sensevoice'\n      config:\n        dataRoot: !!js dshHomePath('speech-to-text', 'sensevoice')");
if(!officialBundle&&!patch.includes("name: '@deepseek-ai/dsh-experimental-api-speech-to-text'"))entries.push("    - id: pet-voice-official-api\n      name: '@deepseek-ai/dsh-experimental-api-speech-to-text'");
if(!patch.includes('id: dsh-companion-voice'))entries.push('    - id: dsh-companion-voice\n      name: dsh-companion-voice');
if(entries.length){
  const backup=join(root,'qa','profile-before-'+Date.now()+'.yml');mkdirSync(dirname(backup),{recursive:true});copyFileSync(patchPath,backup);
  patch=patch.trimEnd()+'\n# Local pet voice services.\n- insert:\n'+entries.join('\n')+'\n';
  writeFileSync(patchPath,patch,'utf8');
}
console.log('本地语音插件已注册：'+root+'。DSH 会热加载新增条目，运行状态可在宠物设置中检查。');
