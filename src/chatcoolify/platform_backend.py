"""Platform adapter: Coolify owns every build, image and container lifecycle."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import quote,urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

from .platform_artifact import PlatformError


class CoolifyBackend:
    def __init__(self, client, *, server_uuid, team_id=None, source_url_base=None, source_key_uuid=None, external_tls=False):
        self.client = client
        self.server_uuid = server_uuid
        self.team_id = team_id
        self.source_url_base = source_url_base
        self.source_key_uuid = source_key_uuid
        self.external_tls=external_tls

    def native_domains(self,url):
        """When an existing edge terminates TLS, native routing stays HTTP."""
        return url.replace('https://','http://',1) if self.external_tls else url

    def create_project(self, name, marker):
        # A native description marker recovers an interrupted create response.
        for item in self.client.list_projects():
            if item.get('description') == marker:
                return self.client.get_project(item['uuid'])
        project = self.client.create_project(name, description=marker)
        return self.client.get_project(project['uuid'])

    def environments(self, project):
        envs = {e['name']: e for e in project['environments']}
        if 'preview' not in envs:
            value = self.client._request('POST', f"/api/v1/projects/{project['uuid']}/environments",
                                         payload={'name': 'preview'}, write=True)
            envs['preview'] = value
        return envs

    def update_application(self, application_uuid, **values):
        return self.client._request('PATCH', f'/api/v1/applications/{quote(application_uuid, safe="")}',
                                    payload=values, write=True)

    def create_source_application(self, project_uuid, environment_uuid, environment, name, source_id, commit, *, port=8080, health_path='/__platform/health', health_command='python /app/runtime.py health'):
        payload = {
            'project_uuid': project_uuid, 'server_uuid': self.server_uuid,
            'environment_name': environment, 'environment_uuid': environment_uuid,
            'private_key_uuid': self.source_key_uuid,
            'git_repository': self.source_url_base.rstrip('/') + '/' + source_id + '.git',
            'git_branch': 'main', 'git_commit_sha': commit, 'build_pack': 'dockerfile',
            'name': name, 'autogenerate_domain': True, 'instant_deploy': False,
            'ports_exposes': str(port), 'health_check_enabled': True,
            'health_check_path': health_path, 'health_check_port': str(port),
            'health_check_type': 'cmd',
            'health_check_command': health_command,
            'health_check_interval': 5, 'health_check_timeout': 3,
            'health_check_retries': 3, 'health_check_start_period': 5,
            'connect_to_docker_network': True,
        }
        return self.client._request('POST', '/api/v1/applications/private-deploy-key', payload=payload, write=True)

    def env(self, application_uuid, values):
        return self.client._request('PATCH', f'/api/v1/applications/{application_uuid}/envs/bulk',
                                    payload={'data': [{'key': k, 'value': str(v), 'is_preview': False,
                                                       'is_buildtime': False, 'is_runtime': True}
                                                      for k, v in values.items()]}, write=True)

    def bind_directory(self, application_uuid, host_path, mount_path):
        return self.client._request('POST', f'/api/v1/applications/{application_uuid}/storages',
                                    payload={'type': 'file', 'is_directory': True,
                                             'fs_path': host_path, 'mount_path': mount_path}, write=True)

    def deploy(self, application_uuid):
        result = self.client.deploy(application_uuid)
        entries = result.get('deployments', [])
        native = result.get('deployment_uuid') or (entries[0].get('deployment_uuid') if entries else None)
        if not native:
            raise PlatformError(502, 'Coolify did not return a native deployment reference')
        return native

    def deployment(self, native_uuid):
        return self.client._request('GET', f'/api/v1/deployments/{quote(native_uuid, safe="")}')

    def application(self, uuid):
        return self.client.get_application(uuid)

    def logs(self, uuid):
        return self.client._request('GET', f'/api/v1/applications/{quote(uuid, safe="")}/logs?lines=100')

    def runtime_artifact(self,url,app_id,secret):
        stamp=str(int(time.time()))
        signature=hmac.new(secret.encode(),('artifact|'+stamp+'|'+app_id).encode(),hashlib.sha256).hexdigest()
        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self,*args):return None
        try:
            request=Request('http://platform-front-'+app_id+':8080/__platform/artifact',
                headers={'Host':urlsplit(url).netloc,'X-Platform-Probe':stamp+':'+signature})
            with build_opener(NoRedirect()).open(request,timeout=15) as response:
                return json.loads(response.read(1024)).get('artifact_sha256')
        except Exception:return None
