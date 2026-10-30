"""Loopback-only THQ Connect protocol probe. No achievement API or game patches."""
import argparse, datetime, json, pathlib, socket, ssl, threading, http.server, time, ipaddress
import sqlite3, hashlib, os, sys, traceback
from cloud_store import CloudStore, UnsupportedRequest
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ROOT = pathlib.Path(__file__).resolve().parent
DATA = ROOT / 'data'
DATA.mkdir(parents=True,exist_ok=True)
LOG = DATA / 'server.jsonl'
LOCK = threading.Lock()
HOSTS = ['ds2.gds.thqconnect.com', 'ds2.thqconnect.com', 'thqc-darksiders2-pc.thqconnect.com', '38.103.18.186']
def log(kind, **fields):
    row = dict(time=datetime.datetime.now(datetime.timezone.utc).isoformat(), event=kind, **fields)
    with LOCK:
        with LOG.open('a', encoding='utf-8') as out: out.write(json.dumps(row, ensure_ascii=False)+'\n')
    if sys.stdout is not None:
        try: print(json.dumps(row, ensure_ascii=True), flush=True)
        except (OSError,ValueError): pass

def cert():
    pem, keyfile = DATA/'local-cert.pem', DATA/'local-key.pem'
    if pem.exists() and keyfile.exists():
        try:
            raw=pem.read_bytes();existing=x509.load_pem_x509_certificate(raw)
            private=serialization.load_pem_private_key(keyfile.read_bytes(),password=None)
            sans=existing.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            now=datetime.datetime.now(datetime.timezone.utc)
            if (raw==existing.public_bytes(serialization.Encoding.PEM) and len(raw)+1<=0x4e2
                and existing.not_valid_before_utc<=now<existing.not_valid_after_utc-datetime.timedelta(days=7)
                and existing.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)==private.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
                and all(h in sans.get_values_for_type(x509.DNSName) or h in [str(ip) for ip in sans.get_values_for_type(x509.IPAddress)] for h in HOSTS)):
                return pem,keyfile
        except (ValueError,TypeError,x509.ExtensionNotFound): pass
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, HOSTS[0])])
    now = datetime.datetime.now(datetime.timezone.utc)
    c = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
         .serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(days=1))
         .not_valid_after(now+datetime.timedelta(days=365))
         .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(h)) if h[0].isdigit() else x509.DNSName(h) for h in HOSTS]), False)
         .add_extension(x509.BasicConstraints(ca=True, path_length=0), True)
         .sign(key, hashes.SHA256()))
    public=c.public_bytes(serialization.Encoding.PEM)
    if len(public)+1>0x4e2: raise ValueError('Certificate exceeds game certificate buffer')
    for path,contents in ((keyfile,key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.TraditionalOpenSSL,serialization.NoEncryption())),(pem,public)):
        temporary=path.with_suffix(path.suffix+'.tmp');temporary.write_bytes(contents);os.replace(temporary,path)
    return pem, keyfile

def shape(value):
    # Do not retain Steam tickets, auth tokens, cookies, or account identifiers.
    if isinstance(value, dict): return {k: shape(v) if not any(s in k.lower() for s in ('auth','ticket','token','password','session','account','profile','key')) else '<redacted>' for k,v in value.items()}
    if isinstance(value, list): return [shape(v) for v in value[:20]]
    if isinstance(value,str) and len(value)>160: return '<string length=%d>'%len(value)
    return value

class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *args): pass
    def do_CONNECT(self):
        host=self.path.rsplit(':',1)[0].rstrip('.').lower()
        if host not in HOSTS:
            log('proxy_rejected',host=host);self.send_error(403);return
        log('proxy_connect',host=host,target=self.path)
        self.send_response(200,'Connection established');self.end_headers()
        try:
            self.connection=self.server.ctx.wrap_socket(self.connection,server_side=True)
            log('tls_ok',port=self.server.server_port,version=self.connection.version(),cipher=self.connection.cipher()[0])
            self.rfile=self.connection.makefile('rb',self.rbufsize)
            self.wfile=self.connection.makefile('wb',self.wbufsize)
            self.close_connection=False
        except Exception as e:
            log('tls_error',port=self.server.server_port,error=str(e));self.close_connection=True
    def do_POST(self): self.do_GET()
    def do_GET(self):
        from urllib.parse import urlsplit, parse_qs
        # The game is not a browser. Reject browser-origin requests to this
        # loopback-only service; no web page needs mailbox write access.
        if self.headers.get('Origin') or self.headers.get('Sec-Fetch-Site'):
            self.send_error(403);return
        u=urlsplit(self.path)
        try: n=int(self.headers.get('Content-Length','0'))
        except ValueError: self.send_error(400);return
        if n<0: self.send_error(400);return
        if self.headers.get('Transfer-Encoding'): self.send_error(501);return
        if n>1024*1024: self.send_error(413); return
        body=self.rfile.read(n)
        try: value=json.loads(body) if body else None
        except ValueError:
            try: value=parse_qs(body.decode('utf-8'),keep_blank_values=True)
            except UnicodeDecodeError: value={'bytes':len(body)}
        query=parse_qs(u.query,keep_blank_values=True)
        params=query or value or {}
        operations=params.get('ops',[]) if isinstance(params,dict) else []
        operations=[op for op in operations if op in ('MAP_GET','MAP_SET','MAP_REMOVE','GET','SET')] if isinstance(operations,list) else []
        log('request',port=self.server.server_port,method=self.command,path=u.path[:160],ops=operations)
        # Explicit research responses can be revised without restarting the game.
        # Cloud writes are acknowledged only after the durable store commits.
        overrides={}
        response_file=ROOT/'probe-responses.json'
        if response_file.exists(): overrides=json.loads(response_file.read_text(encoding='utf-8'))
        if u.path=='/health':
            response={'service':'DS2-THQ-Portable-1.0','pid':os.getpid(),'port':self.server.server_port,
                      'instance':hashlib.sha256(str(ROOT.resolve()).lower().encode('utf-8')).hexdigest(),
                      'certificate_sha256':self.server.certificate_digest};status=200
        elif u.path=='/version':
            response=[0,[],[],[],[]]
            status=200
        elif u.path=='/thqconnect/cloud/execute':
            params=query or value or {}
            try:
                if not isinstance(params,dict): raise UnsupportedRequest('Invalid parameters')
                response=self.server.cloud.execute(params); status=200
                log('cloud_committed',ops=params.get('ops'),results=len(response[1]))
            except UnsupportedRequest as exc:
                response={'error':str(exc)}; status=501
            except (sqlite3.Error,OSError):
                # Never return success if a durable commit failed.
                log('cloud_storage_error');response={'error':'Local storage failed'};status=503
        elif u.path in overrides and not u.path.startswith('/thqconnect/cloud/'):
            response=overrides[u.path]; status=200
        else: response={'error':'Protocol not implemented'}; status=501
        payload=json.dumps(response,separators=(',',':')).encode()
        log('response',path=u.path,status=status,bytes=len(payload),format='array' if isinstance(response,list) else 'object')
        self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)))
        self.send_header('Connection','close');self.end_headers();self.wfile.write(payload);self.close_connection=True

class Server(http.server.ThreadingHTTPServer):
    daemon_threads=True
    allow_reuse_address=False
    def server_bind(self):
        if hasattr(socket,'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        super().server_bind()
    def get_request(self):
        sock,addr=super().get_request();sock.settimeout(10)
        try:
            first=sock.recv(5,socket.MSG_PEEK)
            log('connection',port=self.server_port,prefix=first.hex())
            if first[:1]==b'\x16':
                sock=self.ctx.wrap_socket(sock,server_side=True)
                log('tls_ok',port=self.server_port,version=sock.version(),cipher=sock.cipher()[0])
            return sock,addr
        except Exception as e:
            log('tls_error',port=self.server_port,error=str(e));sock.close();raise

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--cert-only',action='store_true')
    ap.add_argument('--ports',type=int,nargs='+',default=[18086]);args=ap.parse_args()
    pem,key=cert()
    if args.cert_only:return
    ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);ctx.minimum_version=ssl.TLSVersion.TLSv1
    ctx.set_ciphers('ALL:@SECLEVEL=0');ctx.load_cert_chain(pem,key)
    cloud=CloudStore(DATA/'cloud.sqlite')
    servers=[]
    for port in args.ports:
        if not 1024<=port<=65535: raise ValueError('Invalid port')
        server=Server(('127.0.0.1',port),Handler);server.ctx=ctx;server.cloud=cloud
        server.certificate_digest=hashlib.sha256(pem.read_bytes()).hexdigest();servers.append(server)
    for server in servers:
        threading.Thread(target=server.serve_forever,daemon=True).start();log('listening',host='127.0.0.1',port=server.server_port)
    try:
        while True:time.sleep(1)
    except KeyboardInterrupt:
        for server in servers:server.shutdown();server.server_close()
if __name__=='__main__':
    try: main()
    except Exception:
        with (DATA/'server-error.log').open('a',encoding='utf-8') as error: traceback.print_exc(file=error)
        raise
