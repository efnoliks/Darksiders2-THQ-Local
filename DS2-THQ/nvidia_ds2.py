"""Inspect and reversibly set the DS2-only NVIDIA frame rate profile using NVAPI."""
import ctypes as C
import json, pathlib, argparse, datetime
SCRIPT_DIR=pathlib.Path(__file__).resolve().parent
ROOT=(SCRIPT_DIR.parent/'bin' if SCRIPT_DIR.name=='extras' else SCRIPT_DIR)/'data'
ROOT.mkdir(parents=True,exist_ok=True)
U=C.c_uint32; H=C.c_void_p; W=C.c_wchar*2048
class Binary(C.Structure):
    _pack_=4
    _fields_=[('length',U),('data',C.c_ubyte*4096)]
class Value(C.Union):
    _pack_=4
    _fields_=[('dword',U),('binary',Binary),('text',W),('qword',C.c_uint64)]
class Setting(C.Structure):
    _pack_=4
    _fields_=[('version',U),('name',W),('id',U),('type',U),('location',U),('predefined',U),('predefinedValid',U),('default',Value),('current',Value)]
class App(C.Structure):
    _fields_=[('version',U),('predefined',U),('name',W),('friendly',W),('launcher',W),('fileInFolder',W),('flags',U)]
class Profile(C.Structure):
    _fields_=[('version',U),('name',W),('gpu',U),('predefined',U),('apps',U),('settings',U)]
def version(obj,n=1):obj.version=C.sizeof(obj)|(n<<16);return obj
DLL=C.CDLL(r'C:\Windows\System32\nvapi64.dll')
DLL.nvapi_QueryInterface.argtypes=[U];DLL.nvapi_QueryInterface.restype=H
def fn(i,*args):
    ptr=DLL.nvapi_QueryInterface(i)
    if not ptr:raise RuntimeError('NVAPI function unavailable: '+hex(i))
    return C.CFUNCTYPE(C.c_int,*args)(ptr)
def ok(status,label):
    if status!=0:raise RuntimeError(label+': NVAPI status '+str(status))
initialize=fn(0x0150e828)
create=fn(0x0694d52e,C.POINTER(H));destroy=fn(0xdad9cff8,H)
load=fn(0x375dbd6b,H);save=fn(0xfcbc7e14,H)
find=fn(0xeee566b2,H,C.c_wchar_p,C.POINTER(H),C.POINTER(App))
info=fn(0x61cd6fd6,H,H,C.POINTER(Profile))
enumapps=fn(0x7fa2173a,H,H,U,C.POINTER(U),C.POINTER(App))
get=fn(0x73bf8338,H,H,U,C.POINTER(Setting))
setvalue=fn(0x577dd202,H,H,C.POINTER(Setting))
delete=fn(0xe4a26362,H,H,U)
FPS=0x10835002
def setting(session,profile,id):
    s=version(Setting());s.id=id;r=get(session,profile,id,C.byref(s))
    if r not in (0,-160):ok(r,'GetSetting')
    if r==0 and s.type!=0:raise RuntimeError('Unexpected non-DWORD setting')
    return dict(status=r,id=hex(id),name=s.name,value=int(s.current.dword),location=int(s.location),predefined=int(s.predefined)),s
def main():
    ap=argparse.ArgumentParser();ap.add_argument('action',choices=['inspect','apply','restore'],default='inspect',nargs='?')
    ap.add_argument('--game',required=True);args=ap.parse_args();GAME=pathlib.Path(args.game).resolve()
    if GAME.name.lower()!='darksiders2.exe' or not GAME.is_file():raise RuntimeError('Invalid game executable')
    ok(initialize(),'Initialize');session=H();ok(create(C.byref(session)),'CreateSession')
    try:
        ok(load(session),'LoadSettings');profile=H();app=version(App(),3)
        ok(find(session,str(GAME),C.byref(profile),C.byref(app)),'FindApplicationByName')
        p=version(Profile());ok(info(session,profile,C.byref(p)),'GetProfileInfo')
        # Never modify the global/base driver profile.
        if not p.name or 'darksiders' not in p.name.lower():raise RuntimeError('Unexpected profile '+p.name)
        apps=[]
        for start in range(p.apps):
            entry=version(App(),3);count=U(1);ok(enumapps(session,profile,start,C.byref(count),C.byref(entry)),'EnumApplications');apps.append(entry.name)
        current,_=setting(session,profile,FPS)
        result=dict(profile=p.name,applications=apps,matchedApplication=app.name,fps=current)
        backup=ROOT/'nvidia-ds2-before.json'
        if args.action=='inspect':
            (ROOT/'nvidia-ds2-inspect.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        elif args.action=='apply':
            if any(pathlib.PureWindowsPath(a).name.lower()!='darksiders2.exe' for a in apps):raise RuntimeError('Profile also covers other executables; refusing to change it')
            if backup.exists():raise RuntimeError('A backup already exists; inspect or restore before another change')
            backup.write_text(json.dumps(result,indent=2),encoding='utf-8')
            s=version(Setting());s.id=FPS;s.type=0;s.current.dword=60
            ok(setvalue(session,profile,C.byref(s)),'SetSetting');ok(save(session),'SaveSettings')
            ok(load(session),'ReloadSettings');after,_=setting(session,profile,FPS)
            if after['value']!=60 or after['location']!=0:raise RuntimeError('Frame limit was not persisted in the application profile')
            result['after']=after;result['applied']=True
        else:
            if any(pathlib.PureWindowsPath(a).name.lower()!='darksiders2.exe' for a in apps):raise RuntimeError('Profile now covers other executables; refusing to change it')
            old=json.loads(backup.read_text(encoding='utf-8'))
            if old['profile']!=p.name:raise RuntimeError('Backup profile mismatch')
            if current['value']!=60 or current['location']!=0:raise RuntimeError('Setting changed since our apply; refusing to overwrite it')
            before=old['fps']
            if before['status']==0 and before['location']==0 and before['predefined']==0:
                s=version(Setting());s.id=FPS;s.type=0;s.current.dword=before['value'];ok(setvalue(session,profile,C.byref(s)),'RestoreSetting')
            else:ok(delete(session,profile,FPS),'DeleteOverride')
            ok(save(session),'SaveSettings');ok(load(session),'ReloadSettings')
            after,_=setting(session,profile,FPS)
            if before['status']==0 and before['location']==0 and before['predefined']==0:
                if after['value']!=before['value'] or after['location']!=0:raise RuntimeError('Restore verification failed')
            elif after['status']==0 and after['location']==0:raise RuntimeError('Local override still present after restore')
            archive=ROOT/('nvidia-ds2-restored-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.json')
            backup.replace(archive);result['restored']=True;result['after']=after
        print(json.dumps(result,ensure_ascii=True,indent=2))
    finally:destroy(session)
if __name__=='__main__':main()
