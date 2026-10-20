"""Bounded HTTP boundary for the importable platform service."""
from __future__ import annotations

from dataclasses import asdict
import html
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import secrets
import time
from urllib.parse import parse_qs, urlsplit

from chatlogin import ManagedError
from .client import CoolifyError
from .platform_artifact import PlatformError, MAX_UPLOAD

COOKIE='__Host-platform-control'
LOGIN_COOKIE='__Host-platform-login-csrf'


class PlatformHandler(BaseHTTPRequestHandler):
    server_version='ChatCoolifyPlatform'

    @property
    def service(self):return self.server.platform

    def log_message(self,*args):pass

    def respond(self,status,value=b'',kind='application/json; charset=utf-8',headers=None):
        body=value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False,default=str).encode()
        self.send_response(status)
        self.send_header('Content-Type',kind)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','private, no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','strict-origin-when-cross-origin')
        self.send_header('X-Frame-Options','DENY')
        for key,value in (headers or {}).items():
            for item in value if isinstance(value,list) else [value]:self.send_header(key,item)
        self.end_headers()
        if self.command!='HEAD':self.wfile.write(body)

    def cookie(self,name=COOKIE):
        try:
            cookies=SimpleCookie(self.headers.get('Cookie',''))
            return cookies[name].value if name in cookies else ''
        except Exception:return ''

    def body(self):
        try:size=int(self.headers.get('Content-Length','0'))
        except ValueError:raise PlatformError(422,'Invalid request length') from None
        if not 0<=size<=MAX_UPLOAD:raise PlatformError(413,'Request exceeds upload limit')
        return self.rfile.read(size)

    def json(self):
        try:value=json.loads(self.body() or b'{}')
        except (ValueError,UnicodeError):raise PlatformError(422,'Invalid JSON request') from None
        if not isinstance(value,dict):raise PlatformError(422,'JSON object required')
        return value

    def token(self):
        auth=self.headers.get('Authorization','')
        if auth.startswith('Bearer '):return auth[7:],True
        return self.cookie(),False

    def session(self,*,write=False):
        token,bearer=self.token()
        session=self.service.control_session(token)
        if write and not bearer:
            if (self.headers.get('Origin')!=self.service.control_url
                    or not hmac.compare_digest(self.headers.get('X-CSRF-Token',''),session.csrf_token)):
                raise PlatformError(403,'Same-origin CSRF validation required')
        return session

    def do_GET(self):self.boundary()
    def do_HEAD(self):self.boundary()
    def do_POST(self):self.boundary()
    def do_PUT(self):self.boundary()
    def do_PATCH(self):self.boundary()
    def do_DELETE(self):self.boundary()

    def boundary(self):
        try:self.dispatch()
        except PlatformError as exc:self.respond(exc.status,{'error':str(exc)})
        except ManagedError as exc:self.respond(exc.status_code,{'error':exc.detail})
        except CoolifyError:self.respond(502,{'error':'Native execution backend rejected the request; reconcile its state'})
        except (TypeError,KeyError,ValueError):self.respond(422,{'error':'Invalid request fields'})
        except Exception:self.respond(503,{'error':'Platform operation unavailable; retained state can be reconciled'})

    def internal(self,path):
        if self.command!='POST':raise PlatformError(405,'POST required')
        value=self.json()
        app=self.service.application_auth(value.get('application_id',''),self.headers.get('Authorization','').removeprefix('Bearer '),value.get('host'))
        if path=='authorize':result=self.service.authorize(app,value)
        elif path=='exchange':result=self.service.exchange(app,value.get('code'),value.get('state'))
        elif path=='reauth':result=self.service.reauth(app,value)
        elif path=='service':result=self.service.service_request(app,value)
        elif path=='logout':
            result=self.service.logout_reader(app,value)
        else:raise PlatformError(404,'Internal operation unavailable')
        self.respond(200,result)

    def login_page(self):
        query={k:v[0] for k,v in parse_qs(urlsplit(self.path).query,max_num_fields=8).items()}
        application=query.get('application','');state=query.get('state','');target=query.get('return_path','/')
        if self.command=='POST':
            if self.headers.get('Origin')!=self.service.control_url:raise PlatformError(403,'Invalid login origin')
            form={k:v[0] for k,v in parse_qs(self.body().decode(),max_num_fields=12).items()}
            if not form.get('csrf') or not hmac.compare_digest(form['csrf'],self.cookie(LOGIN_COOKIE)):
                raise PlatformError(403,'Invalid login form transaction')
            result=self.service.login(form.get('username',''),form.get('password',''))
            token=result['token']
            application=form.get('application','');state=form.get('state','');target=form.get('return_path','/')
            headers={'Set-Cookie':[f'{COOKIE}={token}; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=86400',
                f'{LOGIN_COOKIE}=; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=0']}
        else:
            token=self.cookie();headers={}
        try:self.service.control_session(token)
        except PlatformError:
            nonce=secrets.token_urlsafe(40)
            hidden=''.join(f'<input type="hidden" name="{k}" value="{html.escape(v,quote=True)}">'
                for k,v in {'csrf':nonce,'application':application,'state':state,'return_path':target}.items())
            page=f'''<!doctype html><html lang="zh"><meta name="viewport" content="width=device-width, initial-scale=1"><title>平台登录</title>
            <style>body{{font:17px system-ui;max-width:380px;margin:12vh auto;padding:24px}}input,button{{box-sizing:border-box;width:100%;padding:12px;margin:8px 0;font:inherit}}</style>
            <h1>平台登录</h1><form method="post" action="/login">{hidden}<label>账号<input name="username" autocomplete="username" required></label>
            <label>密码<input name="password" type="password" autocomplete="current-password" required></label><button>登录</button></form></html>'''.encode()
            return self.respond(200,page,'text/html; charset=utf-8',{'Set-Cookie':f'{LOGIN_COOKIE}={nonce}; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=300'})
        if not application:return self.respond(303,b'',headers={**headers,'Location':'/'})
        ticket=self.service.issue_ticket(token,application,state,target)
        nonce=secrets.token_urlsafe(24)
        page=(f'<!doctype html><meta name="referrer" content="strict-origin-when-cross-origin"><title>正在返回项目</title>'
            f'<form method="post" action="{html.escape(ticket["callback"],quote=True)}">'
            f'<input type="hidden" name="code" value="{ticket["code"]}"><input type="hidden" name="state" value="{state}">'
            f'<button>继续</button></form><script nonce="{nonce}">document.forms[0].submit()</script>').encode()
        headers['Content-Security-Policy']=f"default-src 'none'; script-src 'nonce-{nonce}'; form-action {ticket['callback']}; base-uri 'none'"
        self.respond(200,page,'text/html; charset=utf-8',headers)

    def console(self):
        try:session=self.session()
        except PlatformError:return self.respond(303,b'',headers={'Location':'/login'})
        projects=self.service.projects(session.principal)
        rows=''.join(f'<tr><td>{html.escape(p["name"])}</td><td>{p["visibility"]}</td><td>{p["role"]}</td>'
            f'<td><code>{p["id"]}</code></td><td>'+ ' '.join(f'<a href="{html.escape(a["url"],quote=True)}">{a["environment"]}</a>' for a in p['applications'])+'</td></tr>' for p in projects)
        page=f'''<!doctype html><html lang="zh"><meta name="viewport" content="width=device-width, initial-scale=1"><title>项目平台</title>
        <style>body{{font:16px system-ui;margin:4vw}}table{{border-collapse:collapse;width:100%}}td,th{{text-align:left;padding:14px;border-bottom:1px solid #ddd}}code{{font-size:12px}}</style>
        <h1>项目</h1><p>{html.escape(self.service.live(session.principal).display_name or self.service.live(session.principal).username)}</p>
        <table><tr><th>项目</th><th>访问</th><th>权限</th><th>ID</th><th>应用</th></tr>{rows}</table>
        <p>用 <code>coolify platform</code> 注册、上传、预览、发布、查看日志及回退。</p></html>'''.encode()
        self.respond(200,page,'text/html; charset=utf-8')

    def dispatch(self):
        path=urlsplit(self.path).path
        if path=='/__platform/health' and self.command in {'GET','HEAD'}:return self.respond(200,{'ok':True})
        if path.startswith('/internal/v1/'):return self.internal(path[len('/internal/v1/'):])
        if path=='/login' and self.command in {'GET','POST'}:return self.login_page()
        if path=='/' and self.command=='GET':return self.console()
        prefix='/api/platform/v1'
        if not path.startswith(prefix+'/'):raise PlatformError(404,'Route unavailable')
        route=path[len(prefix):].strip('/').split('/')
        if route==['login'] and self.command=='POST':
            if self.headers.get('X-Platform-Client')!='cli':raise PlatformError(403,'Use the platform login form')
            value=self.json()
            return self.respond(200,self.service.login(value.get('username',''),value.get('password','')))
        session=self.session(write=self.command not in {'GET','HEAD'})
        actor=session.principal
        if route==['session'] and self.command=='GET':return self.respond(200,{'principal':asdict(self.service.live(actor)),'csrf_token':session.csrf_token})
        if route==['logout'] and self.command=='POST':return self.respond(200,self.service.logout(self.token()[0]),headers={'Set-Cookie':f'{COOKIE}=; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=0'})
        if route[0]=='users':
            self.service.admin(actor)
            if len(route)==1 and self.command=='GET':result=[asdict(u) for u in self.service.users.list_users(actor)]
            elif len(route)==1 and self.command=='POST':result=self.service.create_user(actor,**self.json())
            elif len(route)==2 and self.command=='PATCH':result=self.service.update_user(actor,route[1],**self.json())
            else:raise PlatformError(405,'Account operation unavailable')
            return self.respond(200,result)
        if route[0]!='projects':raise PlatformError(404,'Resource unavailable')
        if len(route)==1:
            if self.command=='GET':result=self.service.projects(actor)
            elif self.command=='POST':result=self.service.create_project(actor,**self.json())
            else:raise PlatformError(405,'Project operation unavailable')
            return self.respond(200,result)
        project_id=route[1]
        if len(route)==2 and self.command=='GET':return self.respond(200,self.service.project(actor,project_id))
        self.service.check(actor,project_id)
        if len(route)==4 and route[2]=='grants' and self.command in {'PUT','DELETE'}:
            role='none' if self.command=='DELETE' else self.json().get('role')
            result=self.service.grant(actor,project_id,route[3],role)
        elif len(route)==3 and route[2]=='releases':
            if self.command=='GET':result=self.service.releases(actor,project_id)
            elif self.command=='POST':result=self.service.upload(actor,project_id,self.body(),original_commit=self.headers.get('X-Source-Commit'))
            else:raise PlatformError(405,'Release operation unavailable')
        elif len(route)==3 and route[2] in {'preview','publish','rollback'} and self.command=='POST':
            value=self.json()
            result=self.service.deploy(actor,project_id,value['release_id'],environment='preview' if route[2]=='preview' else 'production',
                request_key=value['request_key'],rollback=route[2]=='rollback')
        elif route[2]=='deployments' and self.command=='GET':
            if len(route)==3:result=self.service.deployments(actor,project_id)
            elif len(route)==4:result=self.service.deployment(actor,project_id,route[3])
            elif len(route)==5 and route[4]=='logs':result=self.service.logs(actor,project_id,route[3])
            else:raise PlatformError(404,'Deployment unavailable')
        elif route[2]=='services':
            if len(route)==4 and route[3]=='candidates' and self.command=='GET':result=self.service.service_candidates(actor,project_id)
            elif len(route)==3 and self.command=='GET':result=self.service.services(actor,project_id)
            elif len(route)==3 and self.command=='POST':result=self.service.register_service(actor,project_id,**self.json())
            else:raise PlatformError(405,'Service operation unavailable')
        else:raise PlatformError(404,'Operation unavailable')
        self.respond(200,result)


def serve(service,host='127.0.0.1',port=8080):
    server=ThreadingHTTPServer((host,port),PlatformHandler)
    server.daemon_threads=True
    server.platform=service
    server.serve_forever()
