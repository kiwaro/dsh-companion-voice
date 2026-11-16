/** Optional card embedded in the existing pet settings, using its Claude theme tokens. */
export function createVoiceManagement(React){
  const h=React.createElement;
  const labels={off:'已关闭',standby:'等待唤醒',listening:'请讲',thinking:'正在处理',speaking:'正在回答',preparing:'正在准备本地识别',error:'需要检查麦克风','voice-preparing':'正在加载 CosyVoice','voice-error':'声音加载失败','pet-offline':'请先开启宠物','recognizer-unavailable':'官方识别服务未启用'};
    const errors={'microphone-unavailable':'无法打开所选麦克风，请检查设备和系统权限。','recognition-failed':'本地识别未完成，请重新准备模型后再试。','python-runtime-missing':'语音运行环境尚未安装。','host-disconnected':'语音进程与 DSH 的连接已断开。','command-failed':'指令未能完成，请检查模型连接。','local-synthesis-failed':'本地播报失败，请检查所选音色和扬声器。','audio-overflow':'收音出现中断，本段语音已丢弃，请重新说。','recognition-backlog':'本地识别暂时跟不上收音，请稍后重新说。','previous-command-cancelling':'上一条指令正在停止，请稍后重新说。'};
  return function VoiceManagement(){
    const [state,setState]=React.useState(null),[draft,setDraft]=React.useState(null),[notice,setNotice]=React.useState(''),[busy,setBusy]=React.useState(false);
    const dirty=React.useRef(false),revision=React.useRef(null);
    const api=async(name,input)=>{const response=await fetch('/api/dsh-companion-voice/'+name,{method:input?'POST':'GET',credentials:'same-origin',headers:input?{'content-type':'application/json','x-lanxi-request':'1'}:{},...input?{body:JSON.stringify(input)}:{}});if(!response.ok)throw Error(response.status===403?'语音请求未通过本机验证，请重新打开插件设置。':response.status===400?'语音参数无效，请检查唤醒词和数值范围。':'语音服务请求失败（HTTP '+response.status+'），请检查插件状态。');return response.json();};
    React.useEffect(()=>{let live=true;const check=()=>api('status').then(value=>{if(!live)return;setState(value);if(!dirty.current){revision.current=value.revision;setDraft({...value.settings,wakeWords:value.settings.wakeWords.join('，')});}}).catch(()=>{});check();const timer=setInterval(check,2000);return()=>{live=false;clearInterval(timer);};},[]);
    function change(key,value){dirty.current=true;setDraft(old=>({...old,[key]:value}));}
    async function save(){setBusy(true);setNotice('');try{const result=await api('settings',{expectedRevision:revision.current,settings:{...draft,wakeWords:draft.wakeWords.split(/[,，\n]/).map(w=>w.trim()).filter(Boolean)}});setState(result);if(result.status==='conflict'){dirty.current=false;revision.current=result.revision;setDraft({...result.settings,wakeWords:result.settings.wakeWords.join('，')});setNotice('设置已在其他页面修改，已载入当前版本，请核对后再保存。');return;}dirty.current=false;revision.current=result.revision;setNotice('语音设置已保存。');}catch(error){setNotice(error.message);}finally{setBusy(false);}}
    if(!state||!draft)return null;
    const field=(label,control)=>h('label',{className:'lx-form-label'},label,control);
    return h('section',{className:'lx-card','aria-label':'宠物语音'},
      h('div',{className:'lx-card-head'},h('h3',null,'宠物语音'),h('span',{className:'lx-badge'},labels[state.runtime.phase]??'检查中')),
      h('div',{className:'lx-switch-row'},h('b',{className:'lx-switch-label'},'启用语音'),h('label',{className:'lx-switch'},h('input',{type:'checkbox','aria-label':'启用语音',checked:draft.enabled,onChange:e=>change('enabled',e.target.checked)}),h('span',{className:'lx-switch-track','aria-hidden':true}))),
      h('div',{className:'lx-form-grid',style:{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(min(100%,220px),1fr))',gap:12,margin:'14px 0'}},
        field('唤醒词',h('input',{'aria-label':'唤醒词',value:draft.wakeWords,onChange:e=>change('wakeWords',e.target.value)})),
        field('麦克风',h('select',{'aria-label':'语音麦克风',value:typeof draft.device==='number'?state.runtime.devices.find(d=>d.id===draft.device)?.name??'':draft.device??'',onChange:e=>change('device',e.target.value||null)},h('option',{value:''},'系统默认'),...(state.runtime.devices??[]).map(d=>h('option',{key:d.id,value:d.name},d.name)))),
        field('本地音色',h('select',{'aria-label':'本地音色',value:(state.runtime.voices??[]).includes(draft.voice)?draft.voice:'',onChange:e=>change('voice',e.target.value)},h('option',{value:''},'CosyVoice · 默认参考女声'),...(state.runtime.voices??[]).map(v=>h('option',{key:v,value:v},v)))),
        field('连续对话等待（秒）',h('input',{type:'number',min:3,max:120,value:draft.followupSeconds,onChange:e=>change('followupSeconds',Number(e.target.value))})),
        field('音量',h('input',{type:'range',style:{accentColor:'var(--lx-accent)'},min:0,max:100,value:draft.volume,onChange:e=>change('volume',Number(e.target.value))})),
        field('语速',h('input',{type:'range',style:{accentColor:'var(--lx-accent)'},min:-10,max:10,value:draft.rate,onChange:e=>change('rate',Number(e.target.value))}))),
      !state.officialAvailable&&h('p',{className:'lx-notice'},'请启用 DSH 官方语音输入组件。'),
      h('p',{className:'lx-notice'},'CosyVoice 3 本地生成声音'+(state.runtime.synthesis?.phase==='ready'?' · 已就绪':state.runtime.synthesis?.phase==='loading'?' · 首次加载中':'')),
      state.runtime.lastError&&h('p',{className:'lx-notice',role:'alert'},state.runtime.lastError.startsWith('cosy-')?'CosyVoice 本地声音未能生成，请检查模型和运行环境。':errors[state.runtime.lastError]??'语音运行遇到问题，请检查本地设备和服务。'),
      h('div',{className:'lx-actions'},h('button',{type:'button',className:'lx-primary',disabled:busy,onClick:save},busy?'正在保存……':'保存语音设置'),h('button',{type:'button',disabled:busy||!draft.enabled||state.runtime.synthesis?.phase!=='ready',onClick:()=>api('preview',{voice:(state.runtime.voices??[]).includes(draft.voice)?draft.voice:'',rate:draft.rate,volume:draft.volume}).then(()=>setNotice('正在试听当前音色。')).catch(()=>setNotice('请等声音就绪、当前指令结束后再试听。'))},'试听音色'),h('button',{type:'button',disabled:busy||!state.officialAvailable,onClick:()=>api('prepare',{}).then(()=>setNotice('正在准备本地识别模型。')).catch(e=>setNotice(e.message))},'准备识别模型')),
      h('p',{className:'lx-notice',role:'status'},notice));
  };
}
