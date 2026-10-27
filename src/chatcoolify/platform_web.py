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
        app=self.service.application_auth(value.get('application_id',''),self.headers.get('Authorization','').removeprefix('Bearer '),
            None if path=='canonical' else value.get('host'))
        if path=='canonical':result=self.service.canonical_origin(app,value.get('host'))
        elif path=='authorize':result=self.service.authorize(app,value)
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
        actor=session.principal
        account=self.service.live(actor)
        projects=self.service.projects(actor)
        cards=[]
        role_names={'owner':'所有者','deployer':'可部署','viewer':'可阅读'}
        for project in projects:
            addresses=self.service.domains(actor,project['id'])
            project_id=html.escape(project['id'],quote=True)
            links=[]
            for domain in addresses['environments']:
                environment=domain['environment']
                label='正式网站' if environment=='production' else '预览环境'
                current=domain.get('current_url')
                value=(f'<a href="{html.escape(current,quote=True)}">{html.escape(current)}</a>'
                       if current else '<span class="muted">尚未发布</span>')
                desired=domain.get('desired_url')
                pending=(f'<small>待生效：{html.escape(desired)}</small>' if domain.get('pending') and desired else '')
                edit=''
                if project['role']=='owner':
                    host=urlsplit(desired or '').hostname or ''
                    suffix='.'+addresses['domain_suffix']
                    prefix=host[:-len(suffix)] if host.endswith(suffix) else host
                    button='保存并应用域名' if current else '保存域名'
                    edit=(f'<form class="domain-form" data-kind="domain" data-project="{project_id}" '
                          f'data-environment="{environment}" data-live="{1 if current else 0}">'
                          f'<label>域名前缀<input name="hostname" aria-label="{label}域名前缀" '
                          f'value="{html.escape(prefix,quote=True)}" required maxlength="63" autocomplete="off"></label>'
                          f'<span class="suffix">.{html.escape(addresses["domain_suffix"])}</span>'
                          f'<button>{button}</button><p class="feedback" role="status"></p></form>')
                links.append(f'<section class="address"><strong>{label}</strong><div>{value}{pending}{edit}</div></section>')
            visibility='公开' if project['visibility']=='public' else '私有'
            role=role_names.get(project['role'],project['role'])
            policy=''
            if project['role']=='owner':
                public_selected=' selected' if project['visibility']=='public' else ''
                private_selected=' selected' if project['visibility']=='private' else ''
                policy=(f'<form class="visibility-form" data-kind="visibility" data-project="{project_id}" data-current-visibility="{project["visibility"]}">'
                        '<label>整站访问方式<select name="visibility">'
                        f'<option value="public"{public_selected}>公开：任何人可访问</option>'
                        f'<option value="private"{private_selected}>仅登录：仅已授权用户</option></select></label>'
                        '<button>保存访问设置</button><span class="policy-note">正式网站与预览环境共用此设置；仅登录时限已授权账号访问。</span><p class="feedback" role="status"></p></form>')
            cards.append(f'<article id="project-{project_id}"><div class="card-title"><h2>{html.escape(project["name"])}</h2>'
                         f'<span class="badge">{visibility} · {html.escape(role)}</span></div>'
                         f'<p class="slug">{html.escape(project["slug"])}</p>{policy}'+''.join(links)+
                         f'<details><summary>上传与发布命令</summary><pre>'
                         f'coolify platform upload {project_id} ./dist\n'
                         f'coolify platform preview {project_id} RELEASE_ID\n'
                         f'coolify platform publish {project_id} RELEASE_ID</pre></details></article>')
        name=html.escape(account.display_name or account.username)
        empty='<p class="empty">还没有项目。在下方创建网站，再上传本地构建目录。</p>'
        style='''*{box-sizing:border-box}body{margin:0;background:#f5f6f3;color:#202b24;font:16px/1.6 system-ui,sans-serif}
        header,main{max-width:1080px;margin:auto;padding:24px}header{display:flex;justify-content:space-between;align-items:center;gap:16px;border-bottom:1px solid #dce2d8}header a{color:inherit;text-decoration:none;font-weight:700}.account{display:flex;align-items:center;gap:14px;min-width:0;font-size:14px}.account span{overflow-wrap:anywhere}
        button{background:white;border:1px solid #b9c7b5;padding:8px 14px;border-radius:7px;color:inherit;cursor:pointer;white-space:nowrap}button:disabled{opacity:.6;cursor:wait}h1{font-size:32px;margin:20px 0 6px}h2{margin:0;font-size:21px;overflow-wrap:anywhere}.intro,.muted,.slug{color:#64705e}.intro{margin:0 0 28px}.cards{display:grid;gap:18px}article,.create{background:white;border:1px solid #dce2d8;border-radius:12px;padding:24px;min-width:0}.card-title{display:flex;align-items:start;justify-content:space-between;gap:16px}.badge{background:#eef2e9;border-radius:6px;padding:3px 9px;white-space:nowrap;font-size:13px}.slug{margin:6px 0 18px;font-size:14px}.address{display:grid;grid-template-columns:100px minmax(0,1fr);gap:12px;margin:24px 0}.address a{color:#355d36;overflow-wrap:anywhere}small{display:block;color:#7a631e;overflow-wrap:anywhere}form{display:flex;align-items:end;gap:10px;flex-wrap:wrap}label{display:grid;gap:5px;color:#53614e;font-size:13px;min-width:0}input,select{font:15px system-ui;padding:9px 10px;border:1px solid #becab7;border-radius:6px;background:white;color:#202b24;min-width:0;max-width:100%}.domain-form{margin-top:12px}.domain-form input{width:190px}.suffix{font-size:13px;color:#64705e;align-self:center;overflow-wrap:anywhere}.feedback{flex-basis:100%;margin:0;color:#715a1d;font-size:13px;overflow-wrap:anywhere}.feedback:empty{display:none}.policy-note{flex-basis:100%;font-size:13px;color:#64705e}.visibility-form{padding:14px;background:#f5f7f1;border-radius:8px}.create{margin-top:24px}.create h2{margin-bottom:14px}.create p{color:#64705e;font-size:14px}details{margin-top:20px;border-top:1px solid #e6ebe2;padding-top:14px;font-size:13px}summary{cursor:pointer;color:#64705e}code,pre{overflow-wrap:anywhere;white-space:pre-wrap;font-size:12px}aside{margin-top:24px;padding:18px;background:#edf1e8;border-radius:10px;font-size:14px}.empty{padding:24px;background:white;border-radius:12px}
        @media(max-width:540px){header,main{padding:18px}.card-title{display:block}.badge{display:inline-block;margin-top:8px}article,.create{padding:18px}.address{grid-template-columns:1fr;gap:6px}header{align-items:start}.account{flex-wrap:wrap;justify-content:end}.domain-form label,.domain-form input,.visibility-form label,.visibility-form select,.create label,.create input,.create select{width:100%}.suffix{flex-basis:100%}form button{width:100%}}'''
        script=r'''const csrf=__CSRF__;
        async function request(path,method,payload){const r=await fetch(path,{method,headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:payload===undefined?undefined:JSON.stringify(payload)});let data={};try{data=await r.json()}catch(e){}if(!r.ok)throw new Error(data.error||'请求失败，请重试');return data}
        document.getElementById('logout').onclick=async function(){this.disabled=true;try{await request('/api/platform/v1/logout','POST');location.href='/login'}catch(e){this.disabled=false;this.textContent='退出失败，请重试'}};
        document.querySelectorAll('form[data-kind]').forEach(form=>{form.onsubmit=async event=>{event.preventDefault();const button=form.querySelector('button'),message=form.querySelector('.feedback'),data=Object.fromEntries(new FormData(form));button.disabled=true;message.textContent='正在保存…';try{
          const base='/api/platform/v1/projects',id=form.dataset.project,kind=form.dataset.kind;
          if(kind==='create'){await request(base,'POST',{slug:data.slug,name:data.name||data.slug,visibility:data.visibility,request_key:'create-'+data.slug});location.reload();return}
          if(kind==='visibility'){if(data.visibility==='public'&&!confirm('确认公开此项目的正式网站和预览环境？公开后的读写仍按应用权限执行。')){message.textContent='已取消，访问设置未修改。';return}await request(base+'/'+id,'PATCH',{visibility:data.visibility,expected_visibility:form.dataset.currentVisibility});const saved=await request(base+'/'+id,'GET');if(saved.visibility!==data.visibility)throw new Error('访问设置生效状态未确认，请刷新核对');location.reload();return}
          const route=base+'/'+id+'/domains/'+form.dataset.environment;
          await request(route,'PUT',{hostname:data.hostname});
          if(form.dataset.live!=='1'){message.textContent='域名已预留。首次上传并发布后即可访问。';return}
          if(form.dataset.requestHost!==data.hostname){delete form.dataset.requestKey;form.dataset.requestHost=data.hostname}
          form.dataset.requestKey=form.dataset.requestKey||('domain-ui-'+crypto.randomUUID());
          const job=await request(route+'/apply','POST',{request_key:form.dataset.requestKey});
          message.textContent='正在更新域名；验证成功前保持原入口。';
          for(let n=0;n<60;n++){await new Promise(resolve=>setTimeout(resolve,2500));const result=await request(base+'/'+id+'/deployments/'+job.id,'GET');if(result.state==='finished'&&result.runtime_active&&result.runtime_verified&&!result.domain.pending){location.reload();return}if(['failed','cancelled','configuration_failed','provenance_mismatch'].includes(result.state)){delete form.dataset.requestKey;throw new Error('域名更新未完成，原入口保留。可重试或查看部署状态。')}}
          message.textContent='部署仍在进行，可稍后刷新查看。';
        }catch(error){message.textContent=form.dataset.kind==='visibility'?'未确认设置生效，请刷新核对当前访问方式后再操作；请勿直接重复保存。':error.message}finally{button.disabled=false}}});'''.replace('__CSRF__',json.dumps(session.csrf_token).replace('<','\\u003c'))
        page=f'''<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>我的网站 · ChatCoolify</title><style>{style}</style>
        <header><a href="/">ChatCoolify</a><div class="account"><span>{name}</span><button id="logout">退出</button></div></header>
        <main><h1>我的网站</h1><p class="intro">{len(projects)} 个项目 · 这里管理你的网站；访客访问公开网站无需登录。</p><section class="cards">{''.join(cards) or empty}</section>
        <section class="create"><h2>创建网站</h2><form data-kind="create"><label>网站名称<input name="name" placeholder="我的网站" maxlength="160"></label><label>默认域名前缀<input name="slug" placeholder="my-site" pattern="[a-z][a-z0-9-]{{1,47}}[a-z0-9]" required maxlength="49"></label><label>访客访问<select name="visibility"><option value="public" selected>公开：任何人可访问</option><option value="private">仅登录：仅已授权用户</option></select></label><button>创建网站</button><p class="feedback" role="status"></p></form><p>创建后上传本地构建目录，先预览，再发布。公开网站可直接分享，访客不需要平台账号。</p></section>
        <aside>账号登录保护网站管理、部署与设置。公开阅读与普通留言独立于管理账号；选择私有时才要求授权访问。构建和运行使用同一套 Coolify 基础设施。</aside></main><script>{script}</script></html>'''.encode()
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
        if len(route)==2 and self.command=='PATCH':
            value=self.json()
            return self.respond(200,self.service.set_visibility(actor,project_id,value.get('visibility'),expected_visibility=value.get('expected_visibility')))
        self.service.check(actor,project_id)
        if len(route)==3 and route[2]=='domains' and self.command=='GET':
            result=self.service.domains(actor,project_id)
        elif len(route)==4 and route[2]=='domains' and self.command=='PUT':
            result=self.service.set_domain(actor,project_id,self.json().get('hostname'),environment=route[3])
        elif len(route)==5 and route[2]=='domains' and route[4]=='apply' and self.command=='POST':
            result=self.service.apply_domain(actor,project_id,environment=route[3],request_key=self.json().get('request_key'))
        elif len(route)==4 and route[2]=='grants' and self.command in {'PUT','DELETE'}:
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
