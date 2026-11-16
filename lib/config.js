export const defaults = Object.freeze({enabled:false,wakeWords:['嗨大肥鱼','大肥鱼'],followupSeconds:15,device:null,voice:'',rate:0,volume:80,silenceMs:800});
export function validate(input) {
  if(!input||typeof input!=='object'||Array.isArray(input)||Object.keys(input).some(k=>!Object.hasOwn(defaults,k)))throw Error('invalid-settings');
  const value={...defaults,...input};
  if(typeof value.enabled!=='boolean'||!Array.isArray(value.wakeWords)||!value.wakeWords.length||value.wakeWords.length>12||value.wakeWords.some(w=>typeof w!=='string'||w.trim().length<2||w.length>30)||!Number.isInteger(value.followupSeconds)||value.followupSeconds<3||value.followupSeconds>120||value.device!==null&&!(Number.isInteger(value.device)&&value.device>=0||typeof value.device==='string'&&value.device.length>0&&value.device.length<=160)||typeof value.voice!=='string'||value.voice.length>160||!Number.isInteger(value.rate)||value.rate< -10||value.rate>10||!Number.isInteger(value.volume)||value.volume<0||value.volume>100||!Number.isInteger(value.silenceMs)||value.silenceMs<300||value.silenceMs>3000)throw Error('invalid-settings');
  return {...value,wakeWords:[...new Set(value.wakeWords.map(w=>w.trim()))]};
}
