import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../',import.meta.url));
const python=fileURLToPath(new URL(process.platform==='win32'?'../.venv/Scripts/python.exe':'../.venv/bin/python',import.meta.url));
const result=spawnSync(python,['-m','unittest','discover','-s','tests','-p','test_*.py'],{cwd:root,stdio:'inherit',windowsHide:true,env:{...process.env,PYTHONUTF8:'1'}});
if(result.error)console.error(result.error.message);process.exit(result.status??1);
