"""Account/ACL/SSO boundary tests; native lifecycle is separately live-probed."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import secrets

import pytest

from chatcoolify import PlatformService, PlatformError
from chatcoolify.platform_artifact import make_archive, validate_archive


class NativeFixture:
    """A deterministic adapter fixture, never evidence of a real deployment."""
    team_id=7
    def __init__(self):self.client=self;self.calls=[];self.sequence=0
    def create_project(self,name,marker):return {'uuid':'native-project','environments':[{'name':'production','uuid':'prod-env'},{'name':'preview','uuid':'dev-env'}]}
    def get_project(self,uuid):return self.create_project('','')
    def environments(self,project):return {e['name']:e for e in project['environments']}
    def create_source_application(self,*args):self.sequence+=1;return {'uuid':'native-app-'+str(self.sequence),'domains':'https://app'+str(self.sequence)+'.example.net'}
    def update_application(self,*args,**kwargs):self.calls.append(('update',args,kwargs))
    def native_domains(self,url):return url
    def env(self,*args):self.calls.append(('env',args))
    def deploy(self,app):self.sequence+=1;return 'native-deployment-'+str(self.sequence)
    def deployment(self,uuid):return {'status':'finished','logs':[{'output':'native build completed'}]}


@pytest.fixture
def setup(tmp_path):
    service=PlatformService(tmp_path.resolve()/'platform',NativeFixture(),control_url='https://platform.example.net')
    service.users.bootstrap_owner('owner@example.net','Example-owner-password!')
    owner=service.users.authenticate('owner@example.net','Example-owner-password!')
    a=service.users.create_user(owner,'alice@example.net','Example-alice-password!')
    b=service.users.create_user(owner,'bobby@example.net','Example-bobby-password!')
    aa=service.users.authenticate(a.username,'Example-alice-password!')
    bb=service.users.authenticate(b.username,'Example-bobby-password!')
    pa=service.create_project(aa,'alice-project',request_key='alice-create')
    pb=service.create_project(bb,'bobby-project',request_key='bobby-create')
    return service,owner,aa,bb,pa,pb


def artifact(tmp_path,text='A'):
    site=tmp_path/text;site.mkdir();(site/'index.html').write_text(text)
    return make_archive(site)


def test_real_managed_accounts_project_acl_collaboration_and_admin_boundary(setup):
    s,admin,a,b,pa,pb=setup
    assert len(s.projects(a))==len(s.projects(b))==1
    assert not s.projects(admin)
    for actor,other in [(a,pb),(b,pa),(admin,pa)]:
        for action in ['read','deploy','grant','manage_services']:
            with pytest.raises(PlatformError) as error:s.check(actor,other['id'],action)
            assert error.value.status==404
    s.grant(a,pa['id'],b.user_id,'viewer')
    assert s.check(b,pa['id'])['role']=='viewer'
    with pytest.raises(PlatformError):s.check(b,pa['id'],'deploy')
    s.grant(a,pa['id'],b.user_id,'deployer')
    assert s.check(b,pa['id'],'deploy')['role']=='deployer'
    with pytest.raises(PlatformError):s.check(b,pa['id'],'manage_services')
    s.grant(a,pa['id'],b.user_id,'none')
    with pytest.raises(PlatformError):s.check(b,pa['id'])


def test_idempotent_native_registration_artifact_commit_deploy_and_provenance(setup,tmp_path):
    s,admin,a,b,pa,pb=setup
    assert s.create_project(a,'alice-project',request_key='alice-create')['id']==pa['id']
    raw=artifact(tmp_path)
    r=s.upload(a,pa['id'],raw)
    assert s.upload(a,pa['id'],raw)['id']==r['id']
    assert len(r['source_commit'])==40
    d=s.deploy(a,pa['id'],r['id'],environment='preview',request_key='preview-A')
    assert d['backend_ref']['deployment_uuid'].startswith('native-deployment')
    assert s.deploy(a,pa['id'],r['id'],environment='preview',request_key='preview-A')['id']==d['id']
    with pytest.raises(PlatformError):s.deploy(b,pa['id'],r['id'],environment='production',request_key='invalid')
    with pytest.raises(PlatformError):s.deployment(a,pa['id'],'native-deployment-2')
    assert d['source_commit']==r['source_commit']


def test_sso_atomic_app_and_transaction_binding_parent_logout_and_revoke(setup,tmp_path):
    s,admin,a,b,pa,pb=setup
    r=s.upload(a,pa['id'],artifact(tmp_path))
    s.deploy(a,pa['id'],r['id'],environment='preview',request_key='preview')
    with s.connection() as db:app=dict(db.execute('SELECT * FROM apps WHERE project_id=?',(pa['id'],)).fetchone())
    login=s.login('alice@example.net','Example-alice-password!');state=secrets.token_urlsafe(40)
    ticket=s.issue_ticket(login['token'],app['id'],state,'/index.html')
    with pytest.raises(PlatformError):s.exchange(app,ticket['code'],secrets.token_urlsafe(40))
    with pytest.raises(PlatformError):s.application_auth(app['id'],app['secret'],'other.example.net')
    def consume():
        try:return s.exchange(app,ticket['code'],state)
        except PlatformError:return None
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:consume(),range(2)))
    assert sum(result is not None for result in results)==1
    reader=next(result['token'] for result in results if result)
    assert s.reader(app,reader)[0].principal.user_id==a.user_id
    with pytest.raises(PlatformError):s.control_session(reader)
    s.users.sessions.revoke(login['token'])
    with pytest.raises(PlatformError):s.reader(app,reader)
    login=s.login('alice@example.net','Example-alice-password!')
    ticket=s.issue_ticket(login['token'],app['id'],state,'/')
    reader=s.exchange(app,ticket['code'],state)['token']
    s.logout(login['token'])
    with pytest.raises(PlatformError):s.reader(app,reader)
    login=s.login('alice@example.net','Example-alice-password!')
    ticket=s.issue_ticket(login['token'],app['id'],state,'/')
    s.users.update_user(admin,a.user_id,enabled=False)
    with pytest.raises(PlatformError):s.exchange(app,ticket['code'],state)


def test_artifact_bounds_credentials_and_no_links(tmp_path):
    site=tmp_path/'site';site.mkdir();(site/'index.html').write_text('public dummy')
    (site/'.env').write_text('PRIVATE=never-upload')
    raw=make_archive(site)
    assert '.env' not in validate_archive(raw)
    assert b'never-upload' not in raw
    (site/'credentials.json').write_text('{}')
    with pytest.raises(PlatformError):make_archive(site)
    (site/'credentials.json').unlink()
    (site/'link').symlink_to(site/'index.html')
    with pytest.raises(PlatformError):make_archive(site)


def test_trusted_email_alias_site_reauthentication_and_email_revision_revokes_children(setup,tmp_path):
    s,admin,a,b,pa,pb=setup
    user=s.create_user(admin,username='alias-owner',password='Example-alias-password!',email='trusted-owner@example.net')
    actor=s.users.authenticate('alias-owner','Example-alias-password!')
    project=s.create_project(actor,'alias-project',request_key='alias-project')
    release=s.upload(actor,project['id'],artifact(tmp_path,'alias'))
    s.deploy(actor,project['id'],release['id'],environment='preview',request_key='alias-preview')
    with s.connection(True) as db:
        app=dict(db.execute('SELECT * FROM apps WHERE project_id=?',(project['id'],)).fetchone())
        db.execute('INSERT INTO services(id,project_id,site_id,native_uuid,upstream,adapter,secret) VALUES(?,?,?,?,?,?,?)',
            ('comments',project['id'],'alias-site','native-comments','http://native-comments:8000','chatcomment','dummy-signing-key-'*3))
    central=s.login('alias-owner','Example-alias-password!');state=secrets.token_urlsafe(40)
    ticket=s.issue_ticket(central['token'],app['id'],state,'/')
    reader=s.exchange(app,ticket['code'],state)['token']
    session=s.reader(app,reader)[0]
    payload={'reader_token':reader,'method':'POST','origin':app['url'],'csrf':session.csrf_token,
        'payload':{'site':'alias-site','email':'trusted-owner@example.net','password':'Example-alias-password!'}}
    result=s.reauth(app,payload)
    assert result['management_until']>0
    assert s.trusted_email(actor)=='trusted-owner@example.net'
    payload['payload']['email']='alias-owner'
    with pytest.raises(PlatformError):s.reauth(app,payload)
    s.set_email(admin,actor.user_id,'changed-owner@example.net')
    with pytest.raises(PlatformError):s.reader(app,reader)


def test_http_sdk_named_profile_and_cookie_csrf(setup,tmp_path,monkeypatch):
    import threading
    from http.server import ThreadingHTTPServer
    from urllib.request import Request,urlopen
    from urllib.error import HTTPError
    import json
    from chatcoolify import PlatformClient
    from chatcoolify.platform_web import PlatformHandler,COOKIE
    s,admin,a,b,pa,pb=setup
    server=ThreadingHTTPServer(('127.0.0.1',0),PlatformHandler);server.platform=s
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    origin='http://127.0.0.1:'+str(server.server_port)
    try:
        api=PlatformClient(origin);login=api.login('alice@example.net','Example-alice-password!')
        assert [p['id'] for p in api.request('/projects')]==[pa['id']]
        with pytest.raises(PlatformError) as error:api.request('/projects/'+pb['id'])
        assert error.value.status==404
        home=tmp_path.resolve()/'client-home';api.save('alice',home=home)
        monkeypatch.setenv('CHATCOOLIFY_PLATFORM_URL','https://wrong-profile.invalid')
        restored=PlatformClient.from_profile('alice',home=home)
        assert restored.url==origin
        assert restored.request('/session')['principal']['user_id']==a.user_id
        request=Request(origin+'/api/platform/v1/projects/'+pa['id']+'/grants/'+b.user_id,
            method='PUT',data=json.dumps({'role':'viewer'}).encode(),
            headers={'Cookie':COOKIE+'='+login['token'],'Content-Type':'application/json',
                'Origin':'https://attacker.example.net'})
        with pytest.raises(HTTPError) as rejected:urlopen(request)
        assert rejected.value.code==403
        assert api.request('/projects/'+pa['id'])['role']=='owner'
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)


def test_corrupt_deflate_and_file_directory_conflicts_are_client_errors():
    import io,struct,zipfile
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('index.html','a frontend payload long enough to deflate')
    raw=bytearray(stream.getvalue())
    name_length,extra_length=struct.unpack_from('<HH',raw,26)
    raw[30+name_length+extra_length]=0x07
    with pytest.raises(PlatformError) as error:validate_archive(bytes(raw))
    assert error.value.status==422
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as archive:
        archive.writestr('index.html','dummy')
        archive.writestr('assets','a file')
        archive.writestr('assets/a.js','nested conflict')
    with pytest.raises(PlatformError) as error:validate_archive(stream.getvalue())
    assert error.value.status==422
