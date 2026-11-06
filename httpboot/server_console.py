"""Private, routed KagNode HTTP Boot console backed by the existing authority."""
import hmac
import json
import re
import secrets
import sqlite3
import sys
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer as BaseHTTPServer
from urllib.parse import urlsplit
from common import atomic
from control_transport import issue,storage_failure
from server_web_assets import HTML,ASSETS,UI_VERSION

PAGES={'/','/overview','/clients','/accounts','/reports','/access'}
CSP="default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"


class ThreadingHTTPServer(BaseHTTPServer):
    """Bound connection count and header-read lifetime for the local listener."""
    daemon_threads=True
    def __init__(self,*args,**kwargs):
        self.permits=threading.BoundedSemaphore(16)
        super().__init__(*args,**kwargs)
    def process_request(self,request,address):
        if not self.permits.acquire(blocking=False):
            try:request.sendall(b'HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
            finally:self.shutdown_request(request)
            return
        try:super().process_request(request,address)
        except BaseException:self.permits.release();raise
    def process_request_thread(self,*args):
        try:super().process_request_thread(*args)
        finally:self.permits.release()


def read_state(authority):
    from boot_reports import sanitize,health
    from approval_wizard import approval_defaults
    from product_version import VERSION
    with authority.db(write=False) as db:
        clients=[dict(row) for row in db.execute('SELECT id,hardware,code,approved,expires FROM devices')]
        accounts=[dict(row) for row in db.execute('SELECT name,system_admin FROM accounts ORDER BY uid')]
    reports=[]
    paths=(authority.database.parent/'reports').glob('*/*.json')
    for path in sorted(paths,key=lambda item:item.stat().st_mtime,reverse=True)[:30]:
        try:
            if path.is_symlink() or path.stat().st_size>256*1024:continue
            reports.append(sanitize(json.loads(path.read_text())))
        except (ValueError,OSError):continue
    return {'health':'Server authority ready','clients':clients,'accounts':accounts,'reports':reports,
            'boothealth':health(authority),'defaults':approval_defaults(authority),
            'console_version':UI_VERSION,'authority_version':VERSION}


def existing_authority(database):
    """Attach console operations without running schema or image initialization."""
    from server_v2 import Authority
    from pathlib import Path
    import time
    class ConsoleAuthority(Authority):
        def __init__(self,path):
            self.database=Path(path).resolve(strict=True)
            if not self.database.is_file():raise ValueError('An existing Server authority is required')
            self.clock=time.time
            # Never create or migrate a database when starting this web service.
            with sqlite3.connect(self.database.as_uri()+'?mode=ro',uri=True) as db:
                db.execute('SELECT name,uid,system_admin FROM accounts LIMIT 0')
                db.execute('SELECT id,code,approved FROM devices LIMIT 0')
                db.execute('SELECT name,device FROM assignments LIMIT 0')
        def close(self):pass
    return ConsoleAuthority(database)


def serve(authority,pki,port=8081,credential_name='console-token'):
    if credential_name not in ('console-token','web-console-token'):
        raise ValueError('Invalid console credential name')
    token=secrets.token_urlsafe(32)
    atomic(authority.database.parent/credential_name,token)
    class Handler(BaseHTTPRequestHandler):
        server_version='KagNodeHTTPBoot'
        sys_version=''
        def setup(self):
            super().setup();self.connection.settimeout(10)
        def log_message(self,*args):pass
        def do_GET(self):self.respond()
        def do_HEAD(self):self.respond()
        def do_POST(self):self.respond()
        def send(self,status,raw,mime='application/json',immutable=False,retry_after=None):
            self.send_response(status)
            for key,value in [('Content-Type',mime),('Content-Length',str(len(raw))),('Cache-Control','public, max-age=31536000, immutable' if immutable else 'no-store'),('Content-Security-Policy',CSP),('X-Content-Type-Options','nosniff'),('X-Frame-Options','DENY'),('Referrer-Policy','no-referrer'),('Permissions-Policy','camera=(), microphone=(), geolocation=()')]:self.send_header(key,value)
            if retry_after:self.send_header('Retry-After',str(retry_after))
            self.end_headers()
            if self.command!='HEAD':self.wfile.write(raw)
        def respond(self):
            try:
                host=self.headers.get('Host','')
                parsed=urlsplit('http://'+host)
                if parsed.hostname not in ('127.0.0.1','localhost','::1') or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
                    self.send(400,b'{"error":"Unrecognized console host."}');return
                if parsed.port is not None and not 1<=parsed.port<=65535:
                    self.send(400,b'{"error":"Unrecognized console host."}');return
                path=urlsplit(self.path).path
                if self.command in ('GET','HEAD') and path in PAGES:
                    self.send(200,HTML.encode(),'text/html; charset=utf-8');return
                if self.command in ('GET','HEAD') and path in ASSETS:
                    mime,body=ASSETS[path];self.send(200,body,mime,True);return
                if self.command in ('GET','HEAD') and path=='/healthz':
                    self.send(200,json.dumps({'ok':True,'service':'kagnode-httpboot-web','version':UI_VERSION}).encode());return
                if not path.startswith('/api/'):
                    self.send(404,b'{"error":"Console page not found."}');return
                received=self.headers.get('Authorization','').encode()
                if not hmac.compare_digest(received,('Bearer '+token).encode()):
                    self.send(401,b'{"error":"Local console credential required."}');return
                origin=self.headers.get('Origin')
                if self.headers.get('Sec-Fetch-Site')=='cross-site' or origin and origin!='http://'+host:
                    self.send(403,b'{"error":"Same-origin console requests are required."}');return
                if self.command in ('GET','HEAD') and path=='/api/state':
                    result=read_state(authority)
                elif self.command=='POST' and path=='/api/approve':
                    lengths=self.headers.get_all('Content-Length',[])
                    if len(lengths)!=1 or self.headers.get('Transfer-Encoding'):
                        raise ValueError('A bounded JSON approval request is required.')
                    size=int(lengths[0])
                    if not 0<size<=4096 or self.headers.get_content_type() not in ('text/plain','application/json'):
                        raise ValueError('Invalid approval request.')
                    data=json.loads(self.rfile.read(size))
                    if not isinstance(data,dict) or set(data)!=set(('code','accounts')) or not isinstance(data['code'],str) or not re.fullmatch(r'[A-Za-z0-9]{6}',data['code']):
                        raise ValueError('Enter the six-character Client pairing code.')
                    if not isinstance(data['accounts'],list) or len(data['accounts'])>64 or not all(isinstance(name,str) and 0<len(name)<=128 for name in data['accounts']):
                        raise ValueError('Choose existing Client accounts.')
                    result={'device':authority.approve(data['code'],lambda csr,name:issue(pki,csr,name),data['accounts'])}
                else:
                    self.send(404,b'{"error":"Unknown console operation."}');return
                raw=json.dumps(result).encode()
                if len(raw)>2*1024*1024:raise ValueError('Console response exceeds the safe size limit.')
                self.send(200,raw)
            except sqlite3.OperationalError as error:
                body,status,retry=storage_failure(error);self.close_connection=True;self.send(status,json.dumps(body).encode(),retry_after=retry)
            except (ValueError,KeyError,TypeError,json.JSONDecodeError):
                self.send(400,b'{"error":"Check the pairing code, selected accounts, and request format."}')
            except (BrokenPipeError,ConnectionResetError):pass
            except Exception:
                self.send(500,b'{"error":"The Server could not complete this console request."}')
    if sys.stdout.isatty():print(f'Open http://127.0.0.1:{port}/#{token}',flush=True)
    else:print(f'HTTP Boot local console listening at http://127.0.0.1:{port}/; credential stored in the protected Server state',flush=True)
    with ThreadingHTTPServer(('127.0.0.1',port),Handler) as server:server.serve_forever()
