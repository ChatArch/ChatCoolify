"""Owner-only native management handoff reuses the existing platform console."""
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
import secrets
import threading

import pytest
from chatcoolify import PlatformError
from chatcoolify.platform_runtime import FrontendHandler, COOKIE
from chatcoolify.platform_web import PlatformHandler, COOKIE as CONTROL_COOKIE
from test_platform_public import public_site, owner_reader, guest
from test_platform_management import local_server


def test_owner_management_metadata_is_project_scoped_even_without_bindings(public_site):
    service, owner, app, private, store, backend = public_site
    for target in [app, private]:
        token = owner_reader(service, target)
        value = service.authorize(target, {'method': 'GET', 'reader_token': token})
        assert value['can_manage_project'] is True
        assert value['management_url'] == service.control_url + '/#project-' + target['project_id']


def test_guest_and_project_viewer_have_no_management_destination(public_site):
    service, owner, app, private, store, backend = public_site
    value, _ = guest(service, app)
    assert not value.get('can_manage_project') and not value.get('management_url')
    member = service.users.create_user(owner, 'reader@example.test', 'Example-reader-password!')
    service.grant(owner, app['project_id'], member.user_id, 'viewer')
    token = owner_reader(service, app, member.username, 'Example-reader-password!')
    value = service.authorize(app, {'method': 'GET', 'reader_token': token,
        'can_manage_project': True, 'management_url': 'https://evil.example/'})
    assert value['can_manage_project'] is False and not value.get('management_url')


@pytest.mark.parametrize('identity,expected', [('owner',303),('viewer',403),('guest',403),('tampered-target',503)])
def test_native_manage_route_uses_verified_owner_only(public_site, monkeypatch, identity, expected):
    service, owner, app, private, store, backend = public_site
    token = ''
    if identity in ['owner','tampered-target']:
        token = owner_reader(service, app)
    elif identity == 'viewer':
        member = service.users.create_user(owner, 'reader@example.test', 'Example-reader-password!')
        service.grant(owner, app['project_id'], member.user_id, 'viewer')
        token = owner_reader(service, app, member.username, 'Example-reader-password!')
    class Runtime(FrontendHandler):
        def broker(self, endpoint, payload):
            if endpoint == 'canonical': return 200, {'url': app['url']}
            assert endpoint == 'authorize'
            value = service.authorize(app, payload)
            if identity == 'tampered-target': value['management_url'] = 'https://evil.example/#project-x'
            return 200, value
    monkeypatch.setenv('PLATFORM_PUBLIC_URLS', app['url'])
    monkeypatch.setenv('PLATFORM_CONTROL_URL', service.control_url)
    with local_server(Runtime) as url:
        from urllib.parse import urlsplit
        parsed = urlsplit(url)
        conn = HTTPConnection(parsed.hostname, parsed.port)
        conn.request('GET', '/__platform/manage', headers={'Host': urlsplit(app['url']).netloc,
            'Cookie': COOKIE+'='+token, 'X-User':'owner','X-Role':'owner'})
        response = conn.getresponse(); body = response.read()
        assert response.status == expected
        if expected == 303: assert response.getheader('Location') == service.control_url+'/#project-'+app['project_id']
        else: assert response.getheader('Location') is None
        conn.close()


def test_native_console_has_exact_project_anchor_and_safe_public_confirmation(public_site):
    service, owner, app, private, store, backend = public_site
    login = service.login('owner@example.test', 'Example-owner-password!')
    with local_server(PlatformHandler, platform=service) as url:
        from urllib.parse import urlsplit
        parsed = urlsplit(url); conn = HTTPConnection(parsed.hostname, parsed.port)
        conn.request('GET','/',headers={'Cookie':CONTROL_COOKIE+'='+login['token']})
        response = conn.getresponse(); body = response.read().decode()
        assert response.status == 200
        assert 'id="project-'+app['project_id']+'"' in body
        assert 'confirm(' in body and '公开' in body
        assert '保存访问设置' in body and '<option value="private" selected>' in body
        conn.close()


def control_login(service, username, password):
    value=service.login(username,password)
    value['csrf_token']=service.control_session(value['token']).csrf_token
    return value


def visibility_http(service, url, project, token, csrf, data, *, spoof=False):
    from urllib.parse import urlsplit
    parsed=urlsplit(url);conn=HTTPConnection(parsed.hostname,parsed.port)
    headers={'Content-Type':'application/json','Origin':service.control_url}
    if token:headers['Cookie']=CONTROL_COOKIE+'='+token
    if csrf:headers['X-CSRF-Token']=csrf
    if spoof:headers.update({'X-User':'owner','X-Role':'owner'})
    conn.request('PATCH','/api/platform/v1/projects/'+project,body=json.dumps(data),headers=headers)
    response=conn.getresponse();status=response.status;body=response.read();conn.close()
    return status,json.loads(body)


def test_visibility_http_rejects_stale_expected_mode_without_reopening(public_site):
    service,owner,app,private,store,backend=public_site
    service.set_visibility(owner,app['project_id'],'private')
    login=control_login(service,'owner@example.test','Example-owner-password!')
    with local_server(PlatformHandler,platform=service) as url:
        status,body=visibility_http(service,url,app['project_id'],login['token'],login['csrf_token'],
            {'visibility':'public','expected_visibility':'public'})
        assert status==409
        assert service.project(owner,app['project_id'])['visibility']=='private'


def test_visibility_http_checks_fresh_expected_mode_for_both_transitions(public_site):
    service,owner,app,private,store,backend=public_site
    login=control_login(service,'owner@example.test','Example-owner-password!')
    with local_server(PlatformHandler,platform=service) as url:
        for old,new in [('public','private'),('private','public'),('public','private')]:
            status,body=visibility_http(service,url,app['project_id'],login['token'],login['csrf_token'],
                {'visibility':new,'expected_visibility':old})
            assert status==200 and body['visibility']==new
            assert service.project(owner,app['project_id'])['visibility']==new
        status,_=visibility_http(service,url,app['project_id'],login['token'],login['csrf_token'],
            {'visibility':'public','expected_visibility':'not-a-mode'})
        assert status==422
        assert service.project(owner,app['project_id'])['visibility']=='private'


@pytest.mark.parametrize('identity,csrf_ok,spoof,expected',[
    ('guest',False,False,401),('guest',False,True,401),('viewer',True,True,403),('owner',False,False,403)])
def test_visibility_http_keeps_owner_and_csrf_gate(public_site,identity,csrf_ok,spoof,expected):
    service,owner,app,private,store,backend=public_site
    service.set_visibility(owner,app['project_id'],'private')
    login={}
    if identity=='owner':login=control_login(service,'owner@example.test','Example-owner-password!')
    if identity=='viewer':
        member=service.users.create_user(owner,'reader@example.test','Example-reader-password!')
        service.grant(owner,app['project_id'],member.user_id,'viewer')
        login=control_login(service,member.username,'Example-reader-password!')
    with local_server(PlatformHandler,platform=service) as url:
        status,_=visibility_http(service,url,app['project_id'],login.get('token'),login.get('csrf_token') if csrf_ok else None,
            {'visibility':'public','expected_visibility':'private'},spoof=spoof)
        assert status==expected
        assert service.project(owner,app['project_id'])['visibility']=='private'

