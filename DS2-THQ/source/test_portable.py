"""Integration tests against a disposable built/extracted mod, not a live install.
Usage: python test_portable.py MOD_DIR ORIGINAL_GAME_EXE SECOND_TEST_DIR
The two supplied mod directories must contain only disposable test data.
"""
import concurrent.futures
import hashlib
import http.client
import json
import pathlib
import shutil
import ssl
import subprocess
import sys
import urllib.parse
import warnings
warnings.filterwarnings('ignore',category=DeprecationWarning)
A=B=GAME=None
PORT=18088
checks=[]
def native(root,*args,expected=0):
    result=subprocess.run([str(root/'DS2-THQ.exe'),*args,'--quiet'],timeout=25,
                          stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    assert result.returncode==expected,(args,result.returncode,expected)
def mark(label):checks.append(label);print('PASS '+label,flush=True)
def call(root,op,profile='__portable_recipient__',key='item',value=''):
    ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT);ctx.load_verify_locations(str(root/'bin/data/local-cert.pem'))
    ctx.minimum_version=ctx.maximum_version=ssl.TLSVersion.TLSv1;ctx.set_ciphers('ALL:@SECLEVEL=0')
    c=http.client.HTTPSConnection('127.0.0.1',PORT,context=ctx,timeout=10)
    c.set_tunnel('thqc-darksiders2-pc.thqconnect.com',8443)
    query=urllib.parse.urlencode(dict(ops=op,profileNames=profile,docKeys='__portable_test_mail__',keys=key,values=value,policy='0',auth='PRIVATE_TEST_TOKEN'))
    try:
        c.request('GET','/thqconnect/cloud/execute?'+query);r=c.getresponse();assert r.status==200,r.status
        return json.loads(r.read())
    finally:c.close()
def raw(method,path,headers,expected):
    c=http.client.HTTPConnection('127.0.0.1',PORT,timeout=5)
    try:c.request(method,path,headers=headers);r=c.getresponse();assert r.status==expected,(path,r.status,expected);r.read()
    finally:c.close()
def stop(root):native(root,'--stop-server','--port',str(PORT))

def main():
    global A,B,GAME
    if len(sys.argv)!=4:raise SystemExit("Usage: test_portable.py MOD_DIR GAME_EXE SECOND_TEST_DIR")
    A=pathlib.Path(sys.argv[1]).resolve();GAME=pathlib.Path(sys.argv[2]).resolve();B=pathlib.Path(sys.argv[3]).resolve()
    try:
        native(A,'--check','--game',str(GAME));mark('explicit game path outside game directory')
        config=A/'bin/data/game-path.txt';saved=config.read_bytes()
        native(A,'--check');mark('remembered game path')
        config.unlink();native(A,'--check');mark('automatic Steam detection')
        saved=config.read_bytes();bad=A/'invalid/Darksiders2.exe';bad.parent.mkdir(exist_ok=True);bad.write_bytes(b'not the game')
        native(A,'--check','--game',str(bad),expected=1);assert config.read_bytes()==saved;mark('unsupported EXE refused without replacing saved path')
        native(A,'--unknown-option',expected=1);native(A,'--server-only','--stop-server',expected=1);native(A,'--server-only','--port','0',expected=1);mark('unknown/conflicting options and invalid port refused')
        native(A,'--server-only','--port',str(PORT));native(A,'--server-only','--port',str(PORT));mark('first server start and verified reuse')
        fixture='Portable test gift, quotes " and Unicode: подарок'
        call(A,'MAP_SET',value=fixture);assert json.loads(call(A,'MAP_GET')[1][0][1])[0][1][0]==fixture;mark('TLS 1.0 gift commit/read-back')
        assert call(A,'MAP_GET',profile='__other_portable_recipient__')==[0,[[0,'',0,0,'']]];mark('recipient isolation')
        assert not B.exists(),'Second test directory already exists'
        shutil.copytree(A,B,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        native(B,'--server-only','--port',str(PORT),expected=1);assert call(A,'MAP_GET')[0]==0;mark('another mod folder cannot reuse or kill foreign server')
        stop(A);native(B,'--server-only','--port',str(PORT));assert json.loads(call(B,'MAP_GET')[1][0][1])[0][1][0]==fixture;mark('copied/moved folder preserves mailbox and certificate')
        raw('GET','/version',{'Content-Length':'-1'},400)
        raw('GET','/version',{'Content-Length':'invalid'},400)
        raw('GET','/version',{'Content-Length':'1048577'},413)
        raw('GET','/version',{'Origin':'https://example.invalid'},403)
        raw('CONNECT','example.invalid:443',{},403);mark('malformed requests, oversized body, browser origin and foreign CONNECT rejected')
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(lambda n:call(B,'MAP_SET',profile='__concurrent__',key=str(n),value='item-'+str(n)),range(6)))
        assert len(json.loads(call(B,'MAP_GET',profile='__concurrent__')[1][0][1]))==6;mark('concurrent durable writes')
        log=(B/'bin/data/server.jsonl').read_text(encoding='utf-8')
        assert 'PRIVATE_TEST_TOKEN' not in log and fixture not in log;mark('logs omit authentication and gift payload')
        cert=B/'bin/data/local-cert.pem';public=cert.read_bytes();cert.write_bytes(public+b'changed')
        native(B,'--server-only','--port',str(PORT),expected=1);cert.write_bytes(public);mark('certificate mismatch refuses server reuse')
        cert.write_bytes(public+b'corrupt');stop(B);native(B,'--server-only','--port',str(PORT))
        assert cert.read_bytes()!=public and b'corrupt' not in cert.read_bytes();public=cert.read_bytes()
        mark('owned server can stop and recover even when its public certificate is damaged')
        stop(B);(B/'bin/data/local-key.pem').write_bytes(b'invalid key')
        native(B,'--server-only','--port',str(PORT));assert cert.read_bytes()!=public;assert json.loads(call(B,'MAP_GET')[1][0][1])[0][1][0]==fixture;mark('damaged certificate key regenerated without losing mailbox')
        native(B,'--verify-memory','--port',str(PORT));mark('original game suspended trust-memory verification from relocated mod')
        offline=subprocess.run([str(B/'bin/DS2-Offline.exe'),'--self-test','--quiet'],timeout=10)
        assert offline.returncode==0;assert 'SELFTEST PASS' in (B/'bin/data/offline-selftest.log').read_text(encoding='utf-8-sig');mark('offline proxy self-test')
        stop(B);mark('verified owned server stop')
    finally:
        # Never guess/kill a PID: stop only a server whose folder identity and Python
        # command line pass the launcher's own checks.
        for root in (B,A):
            if root.exists():
                subprocess.run([str(root/'DS2-THQ.exe'),'--stop-server','--port',str(PORT),'--quiet'],timeout=20,
                               stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    print(json.dumps({'passed':len(checks),'checks':checks},ensure_ascii=False),flush=True)

if __name__=="__main__":main()
