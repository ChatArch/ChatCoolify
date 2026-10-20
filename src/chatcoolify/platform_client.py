"""Reusable platform SDK with endpoint profiles and private opaque sessions."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
import uuid

from chatenv import EnvStore, get_paths
from chatenv.tokens import TokenStore

from .config import PlatformConfig
from .platform_artifact import PlatformError, make_archive
from .platform import identifier


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args):return None


class PlatformClient:
    def __init__(self,url,token=None):
        parsed=urlsplit(url)
        if (parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path not in {'','/'}):
            raise PlatformError(422,'Platform URL must be an HTTPS origin')
        if parsed.scheme=='http' and parsed.hostname not in {'localhost','127.0.0.1','::1'}:
            raise PlatformError(422,'Remote platform requires HTTPS')
        self.url=url.rstrip('/');self.token=token
        self.opener=build_opener(NoRedirect())

    def request(self,path,*,method='GET',payload=None,data=None,original_commit=None):
        headers={'Accept':'application/json','X-Platform-Client':'cli'}
        if self.token:headers['Authorization']='Bearer '+self.token
        if original_commit is not None:
            if not isinstance(original_commit,str) or not re.fullmatch(r'[0-9a-f]{40,64}',original_commit):
                raise PlatformError(422,'Invalid original source commit')
            headers['X-Source-Commit']=original_commit
        if payload is not None:
            data=json.dumps(payload).encode();headers['Content-Type']='application/json'
        elif data is not None:headers['Content-Type']='application/zip'
        try:
            with self.opener.open(Request(self.url+'/api/platform/v1'+path,data=data,headers=headers,method=method),timeout=90) as response:
                raw=response.read(8*1024*1024+1)
                if len(raw)>8*1024*1024:raise PlatformError(502,'Platform response exceeds limit')
                return json.loads(raw)
        except HTTPError as exc:
            # No upstream response is echoed, including potential credentials/private content.
            raise PlatformError(exc.code,f'Platform request rejected (HTTP {exc.code})') from None
        except (URLError,OSError,ValueError):
            raise PlatformError(502,'Could not reach project platform') from None

    def login(self,username,password):
        value=self.request('/login',method='POST',payload={'username':username,'password':password})
        self.token=value['token'];return value

    def create_project(self,slug,*,name=None,visibility='private',request_key=None):
        return self.request('/projects',method='POST',payload={'slug':slug,'name':name,'visibility':visibility,
            'request_key':request_key or 'create-'+slug})

    def domains(self,project_id):
        """Read desired and active addresses for an authorized project."""
        identifier(project_id)
        return self.request(f'/projects/{project_id}/domains')

    def set_domain(self,project_id,hostname,*,environment='production'):
        """Reserve a managed hostname for the next explicit native deployment."""
        identifier(project_id)
        if environment not in {'preview','production'}:
            raise PlatformError(422,'Invalid environment')
        return self.request(f'/projects/{project_id}/domains/{environment}',method='PUT',
                            payload={'hostname':hostname})

    def upload(self,project_id,directory,*,original_commit=None):
        identifier(project_id)
        data=make_archive(Path(directory))
        return self.request(f'/projects/{project_id}/releases',method='POST',data=data,original_commit=original_commit)

    def deploy(self,project_id,release_id,*,environment='preview',request_key=None,rollback=False):
        identifier(project_id);identifier(release_id)
        if environment not in {'preview','production'}:raise PlatformError(422,'Invalid environment')
        action='rollback' if rollback else ('preview' if environment=='preview' else 'publish')
        key=request_key or uuid.uuid4().hex
        try:return self.request(f'/projects/{project_id}/{action}',method='POST',payload={'release_id':release_id,'request_key':key})
        except PlatformError as exc:
            raise PlatformError(exc.status,str(exc)+'; retry with request key '+key) from None

    @classmethod
    def from_profile(cls,profile='default',*,home=None):
        values=EnvStore(get_paths(home).envs_dir).load_profile(PlatformConfig,profile)
        tokens=TokenStore(home=home).read('ChatCoolifyPlatform',profile).get('values',{})
        if not values.get('CHATCOOLIFY_PLATFORM_URL') or not tokens.get('token'):
            raise PlatformError(401,'Run coolify platform login for this profile')
        return cls(values['CHATCOOLIFY_PLATFORM_URL'],tokens['token'])

    def save(self,profile='default',*,home=None):
        EnvStore(get_paths(home).envs_dir).save_profile(PlatformConfig,profile,{'CHATCOOLIFY_PLATFORM_URL':self.url})
        TokenStore(home=home).write('ChatCoolifyPlatform',profile,values={'token':self.token},token_type='session',
            source='coolify-platform-login',summary={'url':self.url})


def configured_service():
    from .client import CoolifyClient
    from .config import PlatformServerConfig
    from .platform import PlatformService
    from .platform_backend import CoolifyBackend
    values=EnvStore(get_paths().envs_dir).load_active(PlatformServerConfig)
    def value(name):return os.environ.get(name) or values.get(name)
    native=CoolifyClient(value('COOLIFY_BASE_URL'),token=value('COOLIFY_API_TOKEN'),allow_write=True,timeout=90)
    backend=CoolifyBackend(native,server_uuid=value('CHATCOOLIFY_SERVER_UUID'),team_id=int(value('CHATCOOLIFY_TEAM_ID')),
        source_url_base=value('CHATCOOLIFY_SOURCE_URL'),source_key_uuid=value('CHATCOOLIFY_SOURCE_KEY_UUID'),
        external_tls=str(value('CHATCOOLIFY_EXTERNAL_TLS')).lower() in {'true','1'})
    return PlatformService(value('CHATCOOLIFY_PLATFORM_DATA'),backend,control_url=value('CHATCOOLIFY_CONTROL_URL'),
        internal_url=value('CHATCOOLIFY_INTERNAL_URL'),domain_suffix=value('CHATCOOLIFY_DOMAIN_SUFFIX'),
        reserved_hostnames=[h.strip() for h in (value('CHATCOOLIFY_RESERVED_HOSTS') or '').split(',') if h.strip()])
