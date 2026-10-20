"""Domain policy/lifecycle fixtures are local boundary tests, not live evidence."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import json
from pathlib import Path
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

import pytest

from chatcoolify import PlatformService, PlatformError
from chatcoolify.platform_artifact import make_archive
from chatcoolify.platform_runtime import FrontendHandler


class NativeDomains:
    team_id=7
    def __init__(self):
        self.client=self;self.apps={};self.jobs={};self.running={};self.artifacts={}
        self.occupied={};self.next_status='finished';self.fail_configuration=False;self.sequence=0

    def number(self):self.sequence+=1;return str(self.sequence)
    def create_project(self,name,marker):return {'uuid':'project-'+self.number(),'environments':[
        {'name':'production','uuid':'prod-env'},{'name':'preview','uuid':'preview-env'}]}
    def get_project(self,uuid):return {'uuid':uuid,'environments':[
        {'name':'production','uuid':'prod-env'},{'name':'preview','uuid':'preview-env'}]}
    def environments(self,project):return {e['name']:e for e in project['environments']}
    def domain_inventory(self):
        result={host:set(ids) for host,ids in self.occupied.items()}
        for uuid,app in self.apps.items():
            for url in app['domains'].split(','):result.setdefault(urlsplit(url).hostname,set()).add(uuid)
        return result
    def create_source_application(self,*args,domains=None,**kwargs):
        assert domains is not None
        uuid='app-'+self.number()
        self.apps[uuid]={'uuid':uuid,'domains':domains,'env':{}}
        return dict(self.apps[uuid])
    def update_application(self,uuid,**values):
        if self.fail_configuration:raise PlatformError(502,'Fixture native configuration failure')
        self.apps[uuid].update(values)
    def native_domains(self,urls):return urls
    def env(self,uuid,values):self.apps[uuid]['env'].update(values)
    def deploy(self,uuid):
        job='job-'+self.number();app=self.apps[uuid]
        self.jobs[job]={'status':self.next_status,'commit':app['git_commit_sha'],'app':uuid,
            'snapshot':dict(app['env'])}
        if self.next_status=='finished':self.finish(job)
        return job
    def finish(self,job):
        item=self.jobs[job];item['status']='finished'
        self.running[item['app']]={'artifact_sha256':self.artifacts[item['commit']],
            'runtime_sha256':hashlib.sha256(Path(__file__).parents[1].joinpath('src/chatcoolify/platform_runtime.py').read_bytes()).hexdigest(),
            'domain_generation':item['snapshot']['PLATFORM_DOMAIN_GENERATION'],
            'public_urls':item['snapshot']['PLATFORM_PUBLIC_URLS'].split(',')}
    def deployment(self,job):return dict(self.jobs[job])
    def runtime_domain_state(self,url,app_id,secret):
        uuid=next((key for key,value in self.apps.items() if value['env'].get('PLATFORM_APPLICATION_ID')==app_id),None)
        return self.running.get(uuid)
    def runtime_artifact(self,*args):return (self.runtime_domain_state(*args) or {}).get('artifact_sha256')


@pytest.fixture
def setup(tmp_path):
    backend=NativeDomains()
    service=PlatformService(tmp_path/'platform',backend,control_url='https://platform.example.test')
    service.users.bootstrap_owner('admin','Example-admin-password!')
    admin=service.users.authenticate('admin','Example-admin-password!')
    service.users.create_user(admin,'alice','Example-alice-password!')
    service.users.create_user(admin,'bobby','Example-bobby-password!')
    alice=service.users.authenticate('alice','Example-alice-password!')
    bob=service.users.authenticate('bobby','Example-bobby-password!')
    return service,backend,alice,bob


def release(service,backend,tmp_path,project):
    site=tmp_path/'site';site.mkdir(exist_ok=True);(site/'index.html').write_text('private fixture')
    value=service.upload(project['actor'],project['id'],make_archive(site))
    backend.artifacts[value['source_commit']]=value['artifact_sha256']
    return value


def environment(value,name='production'):
    return next(row for row in value['environments'] if row['environment']==name)


def test_readable_defaults_reserve_both_environments_before_any_build(setup):
    s,n,a,b=setup
    p=s.create_project(a,'my-site',request_key='create')
    assert environment(p['domains'])['desired_url']=='https://my-site.example.test'
    assert environment(p['domains'],'preview')['desired_url']=='https://my-site-preview.example.test'
    assert environment(p['domains'])['current_url'] is None
    assert not n.apps
    assert s.create_project(a,'my-site',request_key='create')['id']==p['id']
    with pytest.raises(PlatformError) as error:s.create_project(b,'my-site-preview',request_key='other')
    assert error.value.status==409
    with pytest.raises(PlatformError):s.create_project(b,'bad-site-',request_key='invalid')
    with pytest.raises(PlatformError):s.create_project(b,'platform',request_key='reserved')


@pytest.mark.parametrize('hostname',['platform','ADMIN','wrong.example.test.evil.test','nested.app.example.test',
    'https://app.example.test','app.example.test:443','app.example.test/path','*.example.test',
    '-bad','bad-','a'*64,' app','app.','外部','other.example.org'])
def test_domain_input_and_reserved_names_are_rejected(setup,hostname):
    s,n,a,b=setup;p=s.create_project(a,'my-site',request_key='create')
    with pytest.raises(PlatformError):s.set_domain(a,p['id'],hostname)


def test_owner_only_domain_changes_and_no_cross_project_takeover(setup):
    s,n,a,b=setup;p=s.create_project(a,'my-site',request_key='create')
    q=s.create_project(b,'your-site',request_key='create')
    with pytest.raises(PlatformError) as error:s.set_domain(b,p['id'],'new-name')
    assert error.value.status==404
    for role in ['viewer','deployer']:
        s.grant(a,p['id'],b.user_id,role)
        assert s.domains(b,p['id'])['project_id']==p['id']
        with pytest.raises(PlatformError) as error:s.set_domain(b,p['id'],'new-name')
        assert error.value.status==403
    with pytest.raises(PlatformError) as error:s.set_domain(b,q['id'],'my-site-preview')
    assert error.value.status==409
    value=s.set_domain(a,p['id'],'Nice-Site')
    assert environment(value)['desired_url']=='https://nice-site.example.test'
    assert environment(value)['generation']==1
    assert s.set_domain(a,p['id'],'nice-site.example.test')==value
    with pytest.raises(PlatformError):s.set_domain(b,q['id'],'my-site')


def test_native_inventory_collisions_and_operator_reservations(setup):
    s,n,a,b=setup
    n.occupied['existing.example.test']={'outside-platform-app'}
    with pytest.raises(PlatformError) as error:s.create_project(a,'existing',request_key='create')
    assert error.value.status==409
    p=s.create_project(a,'my-site',request_key='create')
    with pytest.raises(PlatformError):s.set_domain(a,p['id'],'existing')
    s.reserved_hostnames.add('operator.example.test')
    with pytest.raises(PlatformError):s.set_domain(a,p['id'],'operator')


def test_native_inventory_includes_compose_and_service_children_without_returning_credentials():
    from chatcoolify.platform_backend import CoolifyBackend
    class Client:
        def list_applications(self):
            return [{'uuid':'frontend','fqdn':'http://frontend.example.test','docker_compose_domains':'[]'},
                {'uuid':'compose','fqdn':None,'docker_compose_domains':json.dumps({
                    'web':{'domain':'http://compose.example.test,https://compose-alias.example.test','redirect':'both'}})}]
        def _request(self,method,path):
            assert method=='GET'
            if path=='/api/v1/services':return [{'uuid':'service-1'}]
            assert path=='/api/v1/services/service-1'
            return {'applications':[{'fqdn':'http://backend.example.test'}],'password':'not-returned'}
    backend=CoolifyBackend(Client(),server_uuid='server',external_tls=True)
    assert backend.domain_inventory()=={'frontend.example.test':{'frontend'},
        'compose.example.test':{'compose'},'compose-alias.example.test':{'compose'},
        'backend.example.test':{'service:service-1'}}
    assert backend.native_domains('https://one.example.test,https://two.example.test')=='http://one.example.test,http://two.example.test'


def test_global_claims_are_transactional_across_service_instances(setup):
    s,n,a,b=setup;p=s.create_project(a,'my-site',request_key='create')
    q=s.create_project(b,'your-site',request_key='create')
    second=PlatformService(s.root,n,control_url=s.control_url)
    def claim(item):
        service,actor,project=item
        try:service.set_domain(actor,project['id'],'shared-name');return True
        except PlatformError as error:assert error.status==409;return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        result=list(pool.map(claim,[(s,a,p),(second,b,q)]))
    assert sorted(result)==[False,True]


def test_stage_then_native_activation_keeps_old_primary_until_proven(setup,tmp_path):
    s,n,a,b=setup;p=s.create_project(a,'my-site',request_key='create');p['actor']=a
    r=release(s,n,tmp_path,p)
    first=s.deploy(a,p['id'],r['id'],environment='production',request_key='first')
    assert first['state']=='finished' and not first['domain']['pending']
    with s.connection() as db:app=dict(db.execute('SELECT * FROM apps WHERE project_id=?',(p['id'],)).fetchone())
    staged=s.set_domain(a,p['id'],'readable')
    assert environment(staged)['pending']
    assert environment(staged)['current_url']=='https://my-site.example.test'
    assert s.application_auth(app['id'],app['secret'],'my-site.example.test')['url']==app['url']
    n.next_status='in_progress'
    pending=s.deploy(a,p['id'],r['id'],environment='production',request_key='rename')
    assert pending['domain']['pending']
    assert s.canonical_origin(app,'readable.example.test')['url']=='https://my-site.example.test'
    assert n.apps[app['native_uuid']]['domains']=='https://readable.example.test,https://my-site.example.test'
    for hostname in ['another-name','readable-preview']:
        with pytest.raises(PlatformError) as error:s.set_domain(a,p['id'],hostname)
        assert error.value.status==409
    with pytest.raises(PlatformError):s.deploy(a,p['id'],r['id'],environment='production',request_key='concurrent')
    n.finish(pending['native_uuid'])
    finished=s.deployment(a,p['id'],pending['id'])
    assert finished['state']=='finished' and not finished['domain']['pending']
    assert finished['url']=='https://readable.example.test'
    assert finished['domain']['legacy_urls']==['https://my-site.example.test']
    current=s.application_auth(app['id'],app['secret'],'readable.example.test')
    assert s.canonical_origin(current,'my-site.example.test')['url']==finished['url']
    with pytest.raises(PlatformError):s.application_auth(app['id'],app['secret'],'my-site.example.test')
    with pytest.raises(PlatformError):s.canonical_origin(current,'unrelated.example.test')
    assert environment(s.domains(a,p['id']),'preview')['current_url'] is None


def test_failed_native_build_or_configuration_preserves_active_domain(setup,tmp_path):
    s,n,a,b=setup;p=s.create_project(a,'my-site',request_key='create');p['actor']=a
    r=release(s,n,tmp_path,p)
    original=s.deploy(a,p['id'],r['id'],environment='production',request_key='first')
    s.set_domain(a,p['id'],'readable')
    assert s.deployment(a,p['id'],original['id'])['state']=='finished'
    n.next_status='failed'
    failed=s.deploy(a,p['id'],r['id'],environment='production',request_key='failed')
    assert failed['state']=='failed' and failed['domain']['pending']
    assert failed['domain']['current_url']=='https://my-site.example.test'
    assert s.deployment(a,p['id'],original['id'])['state']=='finished'
    s.set_domain(a,p['id'],'another-name')
    n.fail_configuration=True
    with pytest.raises(PlatformError):s.deploy(a,p['id'],r['id'],environment='production',request_key='config-failure')
    assert environment(s.domains(a,p['id']))['current_url']=='https://my-site.example.test'
    with s.connection() as db:
        assert db.execute("SELECT state FROM deployments WHERE request_key='config-failure'").fetchone()[0]=='configuration_failed'


def test_same_artifact_old_runtime_cannot_activate_domain_generation(setup,tmp_path):
    s,n,a,b=setup;p=s.create_project(a,'my-site',request_key='create');p['actor']=a
    r=release(s,n,tmp_path,p)
    first=s.deploy(a,p['id'],r['id'],environment='production',request_key='first')
    s.set_domain(a,p['id'],'readable');n.next_status='in_progress'
    job=s.deploy(a,p['id'],r['id'],environment='production',request_key='rename')
    # Native API can report finished just before a same-content old container
    # disappears. Artifact equality alone must not activate new origin policy.
    n.jobs[job['native_uuid']]['status']='finished'
    result=s.deployment(a,p['id'],job['id'])
    assert result['state']=='verifying_domain' and result['domain']['pending']
    assert result['domain']['current_url']==first['url']
    n.finish(job['native_uuid'])
    assert not s.deployment(a,p['id'],job['id'])['domain']['pending']


def test_legacy_runtime_requires_explicit_reupload_not_silent_source_rewrite(setup,tmp_path):
    s,n,a,b=setup;p=s.create_project(a,'my-site',request_key='create');p['actor']=a
    r=release(s,n,tmp_path,p)
    s.deploy(a,p['id'],r['id'],environment='production',request_key='first')
    s.set_domain(a,p['id'],'readable')
    with s.connection(True) as db:db.execute('UPDATE releases SET dockerfile_sha256=? WHERE id=?',('old-runtime',r['id']))
    with pytest.raises(PlatformError) as error:s.deploy(a,p['id'],r['id'],environment='production',request_key='old-source')
    assert error.value.status==409 and 'Upload the site again' in str(error.value)
    with s.connection() as db:assert not db.execute("SELECT 1 FROM deployments WHERE request_key='old-source'").fetchone()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args):return None


def test_runtime_pending_canonical_redirect_and_host_bound_fail_closed(monkeypatch):
    from http.server import ThreadingHTTPServer
    canonical=['https://old.example.test']
    class Handler(FrontendHandler):
        def broker(self,endpoint,payload):
            if endpoint=='canonical':return 200,{'url':canonical[0]}
            return 403,{'error':'Fixture reached the normal authorization boundary'}
    monkeypatch.setenv('PLATFORM_PUBLIC_URLS','https://new.example.test,https://old.example.test')
    monkeypatch.setenv('PLATFORM_DOMAIN_GENERATION','4')
    monkeypatch.setenv('PLATFORM_APPLICATION_ID','fixture-app')
    monkeypatch.setenv('PLATFORM_APPLICATION_KEY','fixture-secret-which-is-never-real')
    monkeypatch.setenv('PLATFORM_ARTIFACT_SHA256','artifact-fixture')
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    origin='http://127.0.0.1:'+str(server.server_port);opener=build_opener(NoRedirect())
    def request(host,path='/',method='GET',headers=None):
        try:return opener.open(Request(origin+path,method=method,data=b'' if method=='POST' else None,
            headers={'Host':host,**(headers or {})}))
        except HTTPError as error:return error
    try:
        assert request('old.example.test').code==403
        pending=request('new.example.test','/notes?a=1')
        assert pending.code==308 and pending.headers['Location']=='https://old.example.test/notes?a=1'
        canonical[0]='https://new.example.test'
        old=request('old.example.test','/notes?a=1')
        assert old.code==308 and old.headers['Location']=='https://new.example.test/notes?a=1'
        assert request('old.example.test',method='POST').code==421
        assert request('not-registered.example.test').code==421
        stamp=str(int(time.time()))
        signature=hmac.new(b'fixture-secret-which-is-never-real',('artifact|'+stamp+'|fixture-app').encode(),hashlib.sha256).hexdigest()
        proof=request('old.example.test','/__platform/artifact',headers={'X-Platform-Probe':stamp+':'+signature})
        value=json.load(proof)
        assert value['domain_generation']=='4' and value['public_urls']==['https://new.example.test','https://old.example.test']
        assert value['runtime_sha256']==hashlib.sha256(Path(__file__).parents[1].joinpath('src/chatcoolify/platform_runtime.py').read_bytes()).hexdigest()
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)
