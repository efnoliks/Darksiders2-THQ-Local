"""Build the portable mod from source. Requires Windows .NET Framework compiler.
Use --runtime with the runtime directory from the ready-to-run release.
No game executable or personal data is read/copied by this builder.
"""
import argparse,hashlib,json,pathlib,shutil,subprocess,zipfile

ROOT=pathlib.Path(__file__).resolve().parent
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--runtime',required=True,type=pathlib.Path)
    ap.add_argument('--output',type=pathlib.Path,default=ROOT/'build'/'Darksiders2-THQ-Portable-v1.0')
    args=ap.parse_args();runtime=args.runtime.resolve();output=args.output.resolve()
    archive=output.parent/(output.name+'.zip')
    if output.exists() or archive.exists():raise SystemExit('Output already exists; refusing to overwrite it.')
    for required in ('python.exe','python312._pth','Lib/ssl.py','Lib/codex-rejected-cas.pem'):
        if not (runtime/required).is_file():raise SystemExit('Incomplete bundled runtime: '+required)
    mod=output/'bin';mod.mkdir(parents=True)
    info=output/'info';info.mkdir()
    extras=output/'extras';extras.mkdir()
    for name in ('server.py','cloud_store.py','probe-responses.json'):
        shutil.copy2(ROOT/'DS2-THQ'/name,mod/name)
    shutil.copy2(ROOT/'DS2-THQ'/'nvidia_ds2.py',extras/'nvidia_ds2.py')
    shutil.copytree(ROOT/'DS2-THQ'/'licenses',info/'licenses')
    shutil.copytree(runtime,mod/'runtime',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    (info/'assets').mkdir()
    shutil.copy2(ROOT/'assets'/'logo.png',info/'assets'/'logo.png')
    for name in ('README-RU.md','README-EN.md','readme.txt'):
        shutil.copy2(ROOT/name,info/name)
    csc=pathlib.Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe')
    common=[str(csc),'/nologo','/target:winexe','/platform:x86','/reference:System.Windows.Forms.dll','/reference:System.Web.Extensions.dll','/reference:System.Management.dll']
    sources=ROOT/'DS2-THQ'/'source'
    subprocess.run(common+['/win32icon:'+str(ROOT/'assets/launcher.ico'),'/out:'+str(output/'DS2-THQ.exe')]+[str(sources/n) for n in ('GameLocator.cs','NativeTrust.cs','PortableLauncher.cs')],check=True)
    subprocess.run(common+['/win32icon:'+str(ROOT/'assets/offline.ico'),'/out:'+str(mod/'DS2-Offline.exe')]+[str(sources/n) for n in ('GameLocator.cs','OfflineLauncher.cs')],check=True)
    commands={'Choose-Game.cmd':'--choose-game','Check-Mod.cmd':'--check','Stop-Server.cmd':'--stop-server','Start-Darksiders2-Offline.cmd':'--offline','Set-60FPS-NVIDIA.cmd':'--nvidia60','Restore-FPS-NVIDIA.cmd':'--restore-fps'}
    for name,flags in commands.items():
        (extras/name).write_bytes(('@echo off\r\nstart "" "%~dp0..\\DS2-THQ.exe" '+flags+'\r\n').encode('ascii'))
    subprocess.run([str(mod/'runtime'/'python.exe'),'-B','-I','-c','import ssl,sqlite3,cryptography,cffi;ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)'],check=True)
    files=[p for p in sorted(output.rglob('*')) if p.is_file()]
    for p in files:
        rel=p.relative_to(output)
        if 'data' in rel.parts or p.name in ('Darksiders2.exe','local-key.pem','local-cert.pem','cloud.sqlite') or p.suffix.lower() in ('.dsav','.dopt','.log','.jsonl','.pyc'):
            raise SystemExit('Private/generated data in build: '+str(rel))
    manifest=info/'FILES-SHA256.txt'
    manifest.write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(output).as_posix()+'\n' for p in files),encoding='utf-8')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p in files+[manifest]:z.write(p,p.relative_to(output).as_posix())
    with zipfile.ZipFile(archive) as z:assert z.testzip() is None
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_name(archive.name+'.sha256').write_text(digest+'  '+archive.name+'\n',encoding='ascii')
    print(json.dumps({'output':str(output),'archive':str(archive),'bytes':archive.stat().st_size,'sha256':digest,'runtime_tls':'passed'}))

if __name__=='__main__':main()
