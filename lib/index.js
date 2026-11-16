import {join} from 'node:path';
import {VoiceHost,registerWeb} from './host.js?cosyvoice-20261116-r3';

export const name='companion-voice';
export function apply(ctx){
  ctx.inject(['webServer'],async scope=>{
    const profile=scope.get('profileContext');
    if(!profile?.dir)throw Error('profile-context-missing');
    const host=new VoiceHost(scope,{directory:join(profile.dir,'data','dsh-companion-voice')});
    // Bind disposal before asynchronous startup to cover reloads during listen().
    let disposed=false;scope.effect(()=>async()=>{disposed=true;await host.close();});
    await host.start();if(disposed){await host.close();return;}
    registerWeb(scope,host);
  });
}
