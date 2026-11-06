"""HTTP boundaries for the routed local console, using a disposable authority."""
import http.client,json,sys,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'httpboot'))
import server_console
from server_v2 import Authority

class RoutedConsoleTests(unittest.TestCase):
 def setUp(self):
  self.folder=tempfile.TemporaryDirectory();self.root=Path(self.folder.name);self.authority=Authority(self.root/'authority.db')
  with self.authority.db() as db:db.execute("INSERT INTO accounts (name,uid,gid,password_hash,access) VALUES ('fixture',1001,1001,'PRIVATE-HASH','local')")
  self.ready=threading.Event();self.server=None;original=server_console.ThreadingHTTPServer
  def factory(*args):self.server=original(*args);self.ready.set();return self.server
  self.patch=patch.object(server_console,'ThreadingHTTPServer',side_effect=factory);self.patch.start()
  self.thread=threading.Thread(target=server_console.serve,args=(self.authority,self.root/'pki',0,'web-console-token'),daemon=True);self.thread.start();self.assertTrue(self.ready.wait(5));self.token=(self.root/'web-console-token').read_text()
 def tearDown(self):
  self.server.shutdown();self.thread.join(3);self.patch.stop();self.authority.close();self.folder.cleanup()
 def request(self,method,path,body=None,headers=None):
  c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=4)
  try:c.request(method,path,body=body,headers=headers or {});r=c.getresponse();return r.status,dict(r.getheaders()),r.read()
  finally:c.close()
 def test_pages_assets_and_private_manifest(self):
  for path in ('/overview','/clients','/accounts','/reports','/access'):
   status,headers,body=self.request('GET',path);self.assertEqual(status,200);self.assertIn(b'kn-ui',body);self.assertNotIn('unsafe-inline',headers['Content-Security-Policy']);self.assertNotIn(self.token.encode(),body)
  for path in ('/missing','/assets/console.js','/assets/console.js.map','/server_console.py'):
   self.assertEqual(self.request('GET',path)[0],404)
  for path in server_console.ASSETS:
   status,headers,body=self.request('GET',path);self.assertEqual(status,200);self.assertIn('immutable',headers['Cache-Control'])
  self.assertEqual(self.request('HEAD','/clients')[2],b'')
 def test_state_requires_credential_and_omits_password_hash(self):
  self.assertEqual(self.request('GET','/api/state')[0],401)
  status,_,body=self.request('GET','/api/state',headers={'Authorization':'Bearer '+self.token});self.assertEqual(status,200)
  state=json.loads(body);self.assertEqual(state['accounts'][0]['name'],'fixture');self.assertNotIn(b'PRIVATE-HASH',body);self.assertNotIn(b'password_hash',body)
 def test_host_origin_and_approval_validation(self):
  auth={'Authorization':'Bearer '+self.token,'Content-Type':'application/json'}
  self.assertEqual(self.request('GET','/clients',headers={'Host':'evil.example'})[0],400)
  self.assertEqual(self.request('GET','/api/state',headers={**auth,'Origin':'https://evil.example'})[0],403)
  self.assertEqual(self.request('GET','/api/state',headers={**auth,'Sec-Fetch-Site':'cross-site'})[0],403)
  with patch.object(self.authority,'approve',return_value='fixture-client') as approve:
   for body in ('[]','{"code":"A1B2C3","accounts":"fixture"}','{"code":"A1B2C3","accounts":[],"extra":1}'):
    self.assertEqual(self.request('POST','/api/approve',body,auth)[0],400)
   approve.assert_not_called()
   self.assertEqual(self.request('POST','/api/approve','{"code":"A1B2C3","accounts":["fixture"]}',auth)[0],200);approve.assert_called_once()

class AttachedAuthorityTests(unittest.TestCase):
 def test_attach_requires_existing_database_and_preserves_schema(self):
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'authority.sqlite3'
   with self.assertRaises(FileNotFoundError):server_console.existing_authority(path)
   self.assertFalse(path.exists())
   original=Authority(path)
   with original.db(write=False) as db:before=list(db.execute("SELECT sql FROM sqlite_master ORDER BY name"))
   attached=server_console.existing_authority(path)
   with attached.db(write=False) as db:after=list(db.execute("SELECT sql FROM sqlite_master ORDER BY name"))
   self.assertEqual([tuple(row) for row in before],[tuple(row) for row in after]);attached.close();original.close()

class ConsoleCredentialTests(unittest.TestCase):
 def test_routed_credential_survives_restart_and_legacy_rotation_is_retained(self):
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'web-console-token';first=server_console.console_credential(path,persist=True)
   self.assertEqual(first,server_console.console_credential(path,persist=True));self.assertEqual(path.stat().st_mode&0o777,0o600)
   self.assertNotEqual(first,server_console.console_credential(path,persist=False))
 def test_invalid_permissions_and_symlinks_fail_without_replacing_secrets(self):
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'web-console-token';first=server_console.console_credential(path,persist=True);path.chmod(0o644)
   with self.assertRaises(ValueError):server_console.console_credential(path,persist=True)
   self.assertEqual(path.read_text().strip(),first);path.unlink();target=Path(folder)/'target';target.write_text('retained');path.symlink_to(target)
   with self.assertRaises(ValueError):server_console.console_credential(path,persist=True)
   self.assertEqual(target.read_text(),'retained')
