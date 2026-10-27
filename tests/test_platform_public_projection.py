"""Opt-in /api/public projections relay as signed read-only guests only."""
import base64
import json
from email.message import Message
import pytest
from chatcoolify import PlatformError
from chatcomment.access import verify_context
from test_platform_public import public_site,guest


@pytest.mark.parametrize('path',[
    '/api/public/catalog?offset=0&limit=100',
    '/api/public/state',
    '/api/public/projects/0123456789abcdefabcd',
])
@pytest.mark.parametrize('method',['GET','HEAD'])
def test_guest_projection_is_signed_scoped_read_only(public_site,monkeypatch,path,method):
    import chatcoolify.platform as platform
    service,owner,app,private,store,backend=public_site
    access,context=guest(service,app)
    captured=[]
    class Response:
        code=200
        headers={'Content-Type':'application/json'}
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,limit):return b'{"public_read_only":true}'
    class Opener:
        def open(self,request,timeout):
            captured.append(request)
            return Response()
    monkeypatch.setattr(platform,'build_opener',lambda *args:Opener())
    response=service.service_request(app,{**context,'method':method,
        'path':'/__platform/services/comments'+path,'body_b64':'',
        'subject':owner.user_id,'authenticated':True,
        'site_permissions':{'public-site':{'owner':True,'manage':True}}})
    assert response['status']==200 and len(captured)==1
    with service.connection() as db:
        key=db.execute('SELECT secret FROM services WHERE project_id=?',(app['project_id'],)).fetchone()[0]
    headers=Message()
    for name,value in captured[0].header_items():headers[name]=value
    signed=verify_context(headers,key=key,method=method,path=path,body=b'')
    assert not signed.authenticated and signed.subject.startswith('guest:')
    scope=signed.scope('public-site')
    assert scope.read and not scope.owner and not scope.manage and scope.management_until==0
    assert not signed.scope('other-site').read
    with service.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM readers').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM management').fetchone()[0]==0


@pytest.mark.parametrize('path,method',[
    ('/api/catalog','GET'),('/api/state','GET'),
    ('/api/projects/project-id','GET'),('/api/public/directions','GET'),
    ('/api/public/projects/../../state','GET'),
    ('/api/public/projects/project-id/notes','GET'),
    ('/api/public/catalog/','GET'),('/api/public/state','POST'),
    ('/api/public/catalog','POST'),('/api/public/projects/project-id','PATCH'),
    ('/api/public/state','DELETE'),('/api/public/projects/project-id','PUT'),
])
def test_guest_projection_cannot_expand_private_paths_or_write(public_site,monkeypatch,path,method):
    import chatcoolify.platform as platform
    service,owner,app,private,store,backend=public_site
    access,context=guest(service,app)
    def forbidden(*args,**kwargs):raise AssertionError('forbidden request reached backend')
    monkeypatch.setattr(platform,'build_opener',forbidden)
    with pytest.raises(PlatformError) as error:
        service.service_request(app,{**context,'method':method,
            'path':'/__platform/services/comments'+path,'body_b64':''})
    assert error.value.status==403


def test_public_projection_never_opens_private_project(public_site,monkeypatch):
    import chatcoolify.platform as platform
    service,owner,app,private,store,backend=public_site
    access,context=guest(service,app)
    def forbidden(*args,**kwargs):raise AssertionError('private project reached backend')
    monkeypatch.setattr(platform,'build_opener',forbidden)
    with pytest.raises(PlatformError) as error:
        service.service_request(private,{**context,'method':'GET',
            'path':'/__platform/services/comments/api/public/catalog','body_b64':''})
    assert error.value.status==401
