"""Integration check against the disposable extracted-package test server."""
import hashlib
import http.client
import json
import pathlib
import ssl
import sys
import urllib.parse
import warnings

warnings.filterwarnings('ignore', category=DeprecationWarning)
root = pathlib.Path(sys.argv[1]).resolve()
port = int(sys.argv[2])
write = '--write' in sys.argv
cert = root / 'DS2-THQ' / 'data' / 'local-cert.pem'
assert cert.stat().st_size + 1 <= 0x4e2
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
ctx.load_verify_locations(str(cert))
ctx.minimum_version = ctx.maximum_version = ssl.TLSVersion.TLSv1
ctx.set_ciphers('ALL:@SECLEVEL=0')
payload = 'Package validation item, quotes " and Unicode: РїРѕРґР°СЂРѕРє'

def request(op, profile='__package_test_recipient__', value=''):
    query = urllib.parse.urlencode(dict(ops=op, profileNames=profile,
                                       docKeys='__package_test_mail__', keys='test-item',
                                       values=value, policy='0'))
    connection = http.client.HTTPSConnection('127.0.0.1', port, context=ctx, timeout=5)
    connection.set_tunnel('thqc-darksiders2-pc.thqconnect.com', 8443)
    connection.request('GET', '/thqconnect/cloud/execute?' + query)
    response = connection.getresponse()
    assert response.status == 200, response.status
    value = json.loads(response.read())
    connection.close()
    return value

if write:
    assert request('MAP_SET', value=payload)[0] == 0
records = json.loads(request('MAP_GET')[1][0][1])
assert records[0][0] == 'test-item'
assert records[0][1][0] == payload
assert request('MAP_GET', profile='__other_package_test_recipient__') == [0, [[0, '', 0, 0, '']]]
print('Packaged TLSv1 CONNECT, committed item, read-back and recipient isolation OK')
print('Certificate fingerprint:', hashlib.sha256(cert.read_bytes()).hexdigest())
