"""Public visitors use scoped guest transport, never fake platform accounts."""
import base64
from http.client import HTTPConnection
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer
import json
import secrets
import threading
from urllib.parse import parse_qs,urlsplit

import pytest

from chatcoolify import PlatformService,PlatformError
from chatcoolify.platform_runtime import FrontendHandler,GUEST_COOKIE,STATE_COOKIE
from chatcomment.server import make_handler
from chatcomment.store import Store


class Native:
    def create_project(self,*args):
        return {'uuid':secrets.token_hex(12),'environments':[]}


@pytest.fixture
def public_site(tmp_path):
    service=PlatformService(tmp_path/'platform',Native(),control_url='https://platform.example.test')
    service.users.bootstrap_owner('owner@example.test','Example-owner-password!')
    owner=service.users.authenticate('owner@example.test','Example-owner-password!')
    public=service.create_project(owner,'public-site',visibility='public',request_key='public')
    private=service.create_project(owner,'private-site',visibility='private',request_key='private')
    apps=[]
    with service.connection(True) as db:
        for project in [public,private]:
            app={'id':secrets.token_hex(16),'project_id':project['id'],'environment':'production',
                'native_uuid':secrets.token_hex(12),'environment_uuid':'native-environment',
                'url':'https://'+project['slug']+'.example.test','secret':secrets.token_urlsafe(48)}
            db.execute('INSERT INTO apps(id,project_id,environment,native_uuid,environment_uuid,url,secret) VALUES(?,?,?,?,?,?,?)',
                tuple(app[k] for k in ['id','project_id','environment','native_uuid','environment_uuid','url','secret']))
            service._claim_domain(db,project['id'],'production',app['url'])
            apps.append(app)
    store=Store(tmp_path/'comments.sqlite3')
    store.register('public-site',title='Public comments',origins=[apps[0]['url']],pages=['/'],private=False)
    key=secrets.token_urlsafe(48)
    backend=ThreadingHTTPServer(('127.0.0.1',0),make_handler(store,gateway_key=key))
    thread=threading.Thread(target=backend.serve_forever,daemon=True);thread.start()
    with service.connection(True) as db:
        db.execute('INSERT INTO services VALUES(?,?,?,?,?,?,?,?,?)',(
            'comments',public['id'],'public-site','native-comments',
            'http://127.0.0.1:'+str(backend.server_port),'chatcomment',key,None,'ready'))
    try:yield service,owner,apps[0],apps[1],store,backend
    finally:
        backend.shutdown();backend.server_close();thread.join(timeout=5)


def guest(service,app):
    access=service.authorize(app,{'method':'GET','path':'/__platform/session'})
    assert not access['authenticated'] and access['read']
    return access,{'reader_token':'','guest_token':access['_guest_cookie'],
        'csrf':access['csrf_token'],'origin':app['url']}


def comment_payload(context,content='A public visitor comment'):
    raw=json.dumps({'page':'/','nickname':'Visitor','content':content}).encode()
    return {**context,'method':'POST','path':'/__platform/services/comments/api/sites/public-site/comments',
        'body_b64':base64.b64encode(raw).decode(),'content_type':'application/json'}


def owner_reader(service,app,username='owner@example.test',password='Example-owner-password!'):
    login=service.login(username,password)
    state=secrets.token_urlsafe(40)
    ticket=service.issue_ticket(login['token'],app['id'],state,'/')
    return service.exchange(app,ticket['code'],state)['token']


def test_public_guest_can_read_and_comment_without_platform_account(public_site):
    service,owner,app,private,store,backend=public_site
    with service.connection() as db:before=[db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ['controls','readers']]
    access,context=guest(service,app)
    assert access['site_permissions']['public-site']=={
        'read':True,'comment':True,'manage':False,'owner':False,'management_until':0}
    response=service.service_request(app,{**context,'method':'GET',
        'path':'/__platform/services/comments/api/sites/public-site/config'})
    assert response['status']==200
    assert not json.loads(base64.b64decode(response['body_b64']))['can_manage']
    response=service.service_request(app,{**comment_payload(context),
        'subject':owner.user_id,'email':'owner@example.test','site_permissions':{'public-site':{'owner':True}}})
    assert response['status']==201
    with store.connect() as db:
        row=db.execute('SELECT authenticated,content FROM comments').fetchone()
    assert row['authenticated']==0 and row['content']=='A public visitor comment'
    with service.connection() as db:after=[db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ['controls','readers']]
    assert before==after==[0,0]
    # The independent backend still refuses an unsigned caller.
    conn=HTTPConnection('127.0.0.1',backend.server_port)
    conn.request('GET','/api/sites/public-site/config');r=conn.getresponse();r.read()
    assert r.status==403;conn.close()


@pytest.mark.parametrize('fault',['missing-cookie','wrong-origin','missing-csrf','other-cookie','tampered-cookie'])
def test_guest_write_requires_bound_cookie_and_exact_origin_csrf(public_site,fault):
    service,owner,app,private,store,backend=public_site
    access,context=guest(service,app)
    if fault=='missing-cookie':context.pop('guest_token')
    if fault=='wrong-origin':context['origin']='https://attacker.example.test'
    if fault=='missing-csrf':context.pop('csrf')
    if fault=='other-cookie':context['guest_token']=guest(service,app)[1]['guest_token']
    if fault=='tampered-cookie':context['guest_token']=context['guest_token'][:-1]+'X'
    with pytest.raises(PlatformError) as error:service.service_request(app,comment_payload(context))
    assert error.value.status==403
    with store.connect() as db:assert db.execute('SELECT COUNT(*) FROM comments').fetchone()[0]==0


def test_guest_cookie_is_expiring_and_app_bound(public_site,monkeypatch):
    import chatcoolify.platform as platform
    service,owner,app,private,store,backend=public_site
    access,context=guest(service,app)
    with pytest.raises(PlatformError):service._guest_cookie(private,context['guest_token'])
    now=platform.time.time()
    monkeypatch.setattr(platform.time,'time',lambda:now+1801)
    with pytest.raises(PlatformError) as error:service.service_request(app,comment_payload(context))
    assert error.value.status==403


@pytest.mark.parametrize('path,method',[
    ('/admin?site=public-site','GET'),('/login?site=public-site','GET'),
    ('/api/admin/entry','POST'),('/api/sites/public-site/settings','POST'),
    ('/api/sites/public-site/export?page=/','GET'),('/api/sites/other-site/comments?page=/','GET')])
def test_guest_cannot_reach_management_or_other_site(public_site,path,method):
    service,owner,app,private,store,backend=public_site
    access,context=guest(service,app)
    payload={**comment_payload(context),'path':'/__platform/services/comments'+path,'method':method}
    with pytest.raises(PlatformError) as error:service.service_request(app,payload)
    assert error.value.status==403
    for operation in [service.reauth,service.logout_reader]:
        with pytest.raises(PlatformError):operation(app,{**context,'method':'POST','payload':{}})


def test_private_acl_and_public_stale_or_foreign_reader_behavior(public_site):
    service,owner,app,private,store,backend=public_site
    access,context=guest(service,app)
    with pytest.raises(PlatformError):service.authorize(private,{**context,'method':'GET'})
    for token in ['stale-cookie',owner_reader(service,private)]:
        value=service.authorize(app,{'reader_token':token,'method':'GET'})
        assert value['read'] and not value['authenticated']
        assert not value['site_permissions']['public-site']['owner']
    token=owner_reader(service,app)
    value=service.authorize(app,{'reader_token':token,'method':'GET'})
    assert value['authenticated'] and value['site_permissions']['public-site']['owner']
    # Existing owner management is distinct from anonymous public reading.
    member=service.users.create_user(owner,'member@example.test','Example-member-password!')
    service.grant(owner,app['project_id'],member.user_id,'viewer')
    token=owner_reader(service,app,member.username,'Example-member-password!')
    service.users.update_user(owner,member.user_id,enabled=False)
    value=service.authorize(app,{'reader_token':token,'method':'GET'})
    assert value['read'] and not value['authenticated']
    with pytest.raises(PlatformError):service.authorize(private,{'reader_token':token,'method':'GET'})


def test_guest_submission_rate_limit_does_not_create_account_or_grants(public_site):
    service,owner,app,private,store,backend=public_site
    access,context=guest(service,app)
    for i in range(10):
        assert service.service_request(app,comment_payload(context,str(i)))['status']==201
    with pytest.raises(PlatformError) as error:service.service_request(app,comment_payload(context,'eleventh'))
    assert error.value.status==429
    with service.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM management').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM readers').fetchone()[0]==0


def test_runtime_guest_cookie_is_http_only_not_json_and_public_owner_login_is_explicit(public_site,monkeypatch):
    service,owner,app,private,store,backend=public_site
    class Runtime(FrontendHandler):
        def broker(self,endpoint,payload):
            try:
                if endpoint=='canonical':return 200,{'url':app['url']}
                if endpoint=='authorize':return 200,service.authorize(app,payload)
                if endpoint=='service':return 200,service.service_request(app,payload)
                raise AssertionError(endpoint)
            except PlatformError as error:return error.status,{'error':str(error)}
    monkeypatch.setenv('PLATFORM_PUBLIC_URLS',app['url'])
    monkeypatch.setenv('PLATFORM_CONTROL_URL',service.control_url)
    monkeypatch.setenv('PLATFORM_APPLICATION_ID',app['id'])
    server=ThreadingHTTPServer(('127.0.0.1',0),Runtime)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    host=urlsplit(app['url']).netloc
    def request(method,path,headers=None,body=None):
        conn=HTTPConnection('127.0.0.1',server.server_port)
        conn.request(method,path,body=body,headers={'Host':host,**(headers or {})})
        r=conn.getresponse();result=(r.status,r.getheaders(),r.read());conn.close();return result
    try:
        code,headers,body=request('GET','/__platform/session')
        assert code==200
        values=json.loads(body)
        assert values['read'] and not values['authenticated'] and values['csrf_token']
        assert '_guest_cookie' not in values and '_guest_max_age' not in values
        cookie=next(v for k,v in headers if k.lower()=='set-cookie' and v.startswith(GUEST_COOKIE+'='))
        assert 'Secure' in cookie and 'HttpOnly' in cookie and 'Path=/' in cookie and 'Domain=' not in cookie
        raw=SimpleCookie(cookie)[GUEST_COOKIE].value
        assert raw not in body.decode()
        code,_,body=request('POST','/__platform/services/comments/api/sites/public-site/comments',
            {'Cookie':GUEST_COOKIE+'='+raw,'Origin':app['url'],'X-CSRF-Token':values['csrf_token'],
                'Content-Type':'application/json'},
            json.dumps({'page':'/','nickname':'HTTP visitor','content':'HTTP cookie and CSRF gateway'}))
        assert code==201 and json.loads(body)['content']=='HTTP cookie and CSRF gateway'
        code,headers,body=request('POST','/__platform/logout',
            {'Cookie':GUEST_COOKIE+'='+raw,'Origin':app['url'],'X-CSRF-Token':values['csrf_token']},'{}')
        assert code==403
        code,headers,body=request('GET','/__platform/login?return_path=%2Fnotes%3Fview%3Dmap')
        assert code==303
        location=next(v for k,v in headers if k.lower()=='location')
        assert location.startswith(service.control_url+'/login?')
        assert parse_qs(urlsplit(location).query)['return_path']==['/notes?view=map']
        assert any(k.lower()=='set-cookie' and v.startswith(STATE_COOKIE+'=') for k,v in headers)
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)
