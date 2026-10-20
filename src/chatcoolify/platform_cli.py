"""Thin CLI adapters for the public platform SDK and operator service API."""
import functools
import json
import os
import sys

import click
from chatstyle import prompt_sensitive_value

from .platform_artifact import PlatformError
from .platform_client import PlatformClient, configured_service


def output(value):click.echo(json.dumps(value,ensure_ascii=False,indent=2,default=str))

def boundary(function):
    @functools.wraps(function)
    def wrapped(*args,**kwargs):
        try:return function(*args,**kwargs)
        except PlatformError as exc:raise click.ClickException(str(exc)) from None
    return wrapped

def client(ctx):return PlatformClient.from_profile(ctx.obj['platform_profile'],home=ctx.obj['platform_home'])

def password_value(key):
    if key:
        value=os.environ.get(key)
        if not value:raise click.ClickException('Password environment variable is empty')
        return value
    if not sys.stdin.isatty():raise click.ClickException('Supply --password-env KEY for non-interactive use')
    value=prompt_sensitive_value('Password',None)
    if not value:raise click.ClickException('Password required')
    return value


@click.group()
@click.option('--profile',default='default',show_default=True)
@click.option('--home',type=click.Path(file_okay=False),help='ChatArch home for endpoint profiles and private sessions.')
@click.pass_context
def platform(ctx,profile,home):
    """Register local frontends and deploy them through native Coolify."""
    ctx.ensure_object(dict);ctx.obj.update(platform_profile=profile,platform_home=home)


@platform.command()
@click.option('--url',required=True)
@click.option('--username',required=True)
@click.option('--password-env',help='Environment variable name containing the password.')
@click.pass_context
@boundary
def login(ctx,url,username,password_env):
    """Sign in to an invited account and save a private session."""
    api=PlatformClient(url);result=api.login(username,password_value(password_env))
    api.save(ctx.obj['platform_profile'],home=ctx.obj['platform_home'])
    output({'authenticated':True,'url':api.url,'principal':result['principal']})


@platform.command()
@click.pass_context
@boundary
def logout(ctx):
    """Revoke this control session and all its app reader children."""
    output(client(ctx).request('/logout',method='POST',payload={}))


@platform.command()
@click.pass_context
@boundary
def whoami(ctx):
    """Show current account metadata without session/CSRF secrets."""
    output(client(ctx).request('/session')['principal'])


@platform.group()
def projects():
    """List and register projects owned by or shared with this account."""


@projects.command('list')
@click.pass_context
@boundary
def project_list(ctx):output(client(ctx).request('/projects'))


@projects.command('create')
@click.argument('slug')
@click.option('--name')
@click.option('--visibility',type=click.Choice(['private','public']),default='private')
@click.option('--request-key',help='Stable idempotency key; default is derived from slug.')
@click.pass_context
@boundary
def project_create(ctx,slug,name,visibility,request_key):
    """Create one native-backed project; repeat registration is idempotent."""
    output(client(ctx).create_project(slug,name=name,visibility=visibility,request_key=request_key))


@platform.command()
@click.argument('project')
@click.argument('directory',type=click.Path(exists=True,file_okay=False))
@click.option('--preview',is_flag=True,help='Also queue a native preview build after upload.')
@click.pass_context
@boundary
def upload(ctx,project,directory,preview):
    """Upload a local frontend artifact; production stays unchanged."""
    api=client(ctx);release=api.upload(project,directory)
    output({'release':release,'deployment':api.deploy(project,release['id'])} if preview else release)


def deploy_command(action):
    @platform.command(action)
    @click.argument('project')
    @click.argument('release')
    @click.option('--request-key',help='Reuse this key to recover an interrupted request.')
    @click.pass_context
    @boundary
    def command(ctx,project,release,request_key):
        output(client(ctx).deploy(project,release,environment='preview' if action=='preview' else 'production',
            request_key=request_key,rollback=action=='rollback'))
    command.help={'preview':'Build and run a selected release at its native preview application.',
        'publish':'Explicitly deploy a selected immutable release to production.',
        'rollback':'Redeploy a previously successful production release through Coolify.'}[action]
    return command


for _action in ['preview','publish','rollback']:deploy_command(_action)


@platform.command()
@click.argument('project')
@click.pass_context
@boundary
def status(ctx,project):
    """Reconcile project deployments with actual native Coolify status."""
    api=client(ctx);output({'project':api.request(f'/projects/{project}'),
        'deployments':api.request(f'/projects/{project}/deployments')})


@platform.command()
@click.argument('project')
@click.pass_context
@boundary
def releases(ctx,project):
    """List immutable artifacts and their native build source commits."""
    output(client(ctx).request(f'/projects/{project}/releases'))


@platform.command()
@click.argument('project')
@click.argument('deployment')
@click.pass_context
@boundary
def logs(ctx,project,deployment):
    """Read sanitized native deployment logs for an authorized project."""
    output(client(ctx).request(f'/projects/{project}/deployments/{deployment}/logs'))


@platform.command()
@click.argument('project')
@click.argument('user_id')
@click.option('--role',type=click.Choice(['viewer','deployer','none']),required=True)
@click.pass_context
@boundary
def grant(ctx,project,user_id,role):
    """Project owner: grant collaboration or revoke it immediately."""
    output(client(ctx).request(f'/projects/{project}/grants/{user_id}',method='PUT',payload={'role':role}))


@platform.group()
def users():
    """Administrator account provisioning; no public signup."""


@users.command('list')
@click.pass_context
@boundary
def user_list(ctx):output(client(ctx).request('/users'))


@users.command('create')
@click.argument('username')
@click.option('--password-env')
@click.option('--display-name',default='')
@click.option('--email',help='Trusted email assigned by the inviting administrator.')
@click.pass_context
@boundary
def user_create(ctx,username,password_env,display_name,email):
    """Provision an invited ordinary account."""
    output(client(ctx).request('/users',method='POST',payload={'username':username,
        'password':password_value(password_env),'display_name':display_name,'email':email}))


@users.command('disable')
@click.argument('user_id')
@click.option('--enable',is_flag=True,help='Re-enable instead of disabling.')
@click.pass_context
@boundary
def user_disable(ctx,user_id,enable):
    """Change enabled state; ChatLogin revokes affected sessions."""
    output(client(ctx).request('/users/'+user_id,method='PATCH',payload={'enabled':enable}))


@platform.group()
def services():
    """Project owner: associate independent native backend resources."""


@services.command('list')
@click.argument('project')
@click.option('--candidates',is_flag=True,help='List verified native resources under this project.')
@click.pass_context
@boundary
def services_list(ctx,project,candidates):
    output(client(ctx).request(f'/projects/{project}/services'+('/candidates' if candidates else '')))


@services.command('register')
@click.argument('project')
@click.argument('binding_id')
@click.option('--registration-id',required=True,help='Opaque candidate ID returned by services list --candidates.')
@click.option('--site-id',required=True)
@click.option('--adapter',type=click.Choice(['chatcomment']),required=True)
@click.pass_context
@boundary
def service_register(ctx,project,binding_id,registration_id,site_id,adapter):
    output(client(ctx).request(f'/projects/{project}/services',method='POST',payload={
        'binding_id':binding_id,'registration_id':registration_id,'site_id':site_id,'adapter':adapter}))


@platform.command()
@click.option('--host',default='127.0.0.1')
@click.option('--port',default=8080,type=click.IntRange(1,65535))
@boundary
def serve(host,port):
    """Operator: run the control plane using server-only typed configuration."""
    from .platform_web import serve as run_server
    run_server(configured_service(),host,port)


@platform.command('bootstrap-owner')
@click.argument('username')
@click.option('--password-env')
@boundary
def bootstrap_owner(username,password_env):
    """Operator-only first account bootstrap; never exposed as an HTTP route."""
    from dataclasses import asdict
    output(asdict(configured_service().users.bootstrap_owner(username,password_value(password_env))))


@platform.command('health')
@click.option('--port',default=8080,type=click.IntRange(1,65535))
def health(port):
    """Check a local control runtime; exits nonzero on unhealthy HTTP status."""
    from urllib.request import urlopen
    try:
        with urlopen(f'http://127.0.0.1:{port}/__platform/health',timeout=2) as response:
            if response.status!=200:raise click.ClickException('Control runtime is unhealthy')
    except OSError:raise click.ClickException('Control runtime health check failed') from None
    output({'ok':True})
