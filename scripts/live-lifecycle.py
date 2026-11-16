"""Verify that production switches release and restore the native microphone."""
import json
from pathlib import Path
import time
from urllib.request import Request, build_opener, ProxyHandler

root=Path(__file__).resolve().parents[1]
connection=json.loads(next((Path.home()/'.dsh-companion/connections').glob('*.json')).read_text())
origin=connection['origin']
opener=build_opener(ProxyHandler({}))


def api(route, data=None):
    request=Request(origin+'/api/'+route, data=None if data is None else json.dumps(data).encode(),
                    headers={'Content-Type':'application/json','Origin':origin,'x-lanxi-request':'1'})
    with opener.open(request,timeout=20) as response:
        return json.load(response)


def voice():
    return api('dsh-companion-voice/status')


def save(settings):
    current=voice()
    result=api('dsh-companion-voice/settings',{'expectedRevision':current['revision'],'settings':settings})
    assert result['status']=='saved',result['status']


def until(check,seconds=90):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        current=voice()
        if check(current):
            return current
        time.sleep(.2)
    raise RuntimeError('microphone-lifecycle-timeout')


current=voice()
settings=dict(current['settings'])
pet=api('dsh-companion-lanxi/companion/status')
assert not pet['desktopTools']['busy'],'An existing task is still running'
report={'verifiedAt':time.strftime('%Y-%m-%d %H:%M:%S')}
try:
    save({**settings,'enabled':False})
    until(lambda value:not value['runtime']['microphone'] and value['runtime']['phase']=='off' and value['runtime']['synthesis']['phase']=='off')
    report['microphoneReleasedOnVoiceOff']=True
    report['synthesisReleasedOnVoiceOff']=True
    # Persist the selected physical endpoint by name, so enumerated indices may change after reboot.
    device=settings['device']
    if isinstance(device,int):
        device=next(d['name'] for d in current['runtime']['devices'] if d['id']==device)
    settings['device']=device
    save({**settings,'enabled':True})
    until(lambda value:value['runtime']['microphone'] and value['runtime']['phase']=='standby')
    report['microphoneResumedOnVoiceOn']=True
    api('dsh-companion-lanxi/companion/pet-settings',{'profileId':pet['profileId'],'enabled':False})
    until(lambda value:not value['runtime']['microphone'] and value['runtime']['phase']=='pet-offline' and value['runtime']['synthesis']['phase']=='off')
    report['microphoneReleasedOnPetOff']=True
    report['synthesisReleasedOnPetOff']=True
finally:
    api('dsh-companion-lanxi/companion/pet-settings',{'profileId':pet['profileId'],'enabled':pet['enabled']})
    save(settings)
if settings['enabled'] and pet['enabled']:
    final=until(lambda value:value['runtime']['microphone'] and value['runtime']['phase']=='standby')
    report['restoredToStandby']=True
else:
    final=voice()
report['finalRuntime']=final['runtime']
report['officialModelPhase']=final['recognizer']['preparation']['phase']
(root/'qa/live-lifecycle.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
