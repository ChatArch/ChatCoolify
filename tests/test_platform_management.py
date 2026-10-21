"""Owner console/policy/apply integration tests; all servers and data are local."""
from contextlib import contextmanager
from copy import deepcopy
from html.parser import HTMLParser
from http.server import ThreadingHTTPServer
import json
import secrets
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from chatcoolify import PlatformClient, PlatformError
from chatcoolify.platform_artifact import make_archive, validate_archive
from chatcoolify.platform_web import COOKIE, PlatformHandler
from test_platform_domains import environment, setup


@contextmanager
def local_server(handler, **attributes):
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    for key, value in attributes.items():
        setattr(server, key, value)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield 'http://127.0.0.1:' + str(server.server_port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def upload(s, native, actor, project, tmp_path, text):
    site = tmp_path / text
    site.mkdir()
    (site / 'index.html').write_text(text)
    result = s.upload(actor, project['id'], make_archive(site), original_commit='a' * 40)
    native.artifacts[result['source_commit']] = result['artifact_sha256']
    return result


def test_service_and_http_sdk_default_public_and_explicit_private(setup, monkeypatch):
    from click.testing import CliRunner
    from chatcoolify.cli import main

    s, native, owner, other = setup
    assert s.create_project(owner, 'default-public', request_key='default')['visibility'] == 'public'
    assert s.create_project(owner, 'explicit-private', visibility='private', request_key='private')['visibility'] == 'private'
    with local_server(PlatformHandler, platform=s) as origin:
        client = PlatformClient(origin)
        client.login('alice', 'Example-alice-password!')
        # The bare API and SDK each have a default; neither should silently
        # restore the old private default when a client omits the field.
        assert client.request('/projects', method='POST', payload={
            'slug': 'http-default', 'request_key': 'http-default'})['visibility'] == 'public'
        assert client.create_project('sdk-default')['visibility'] == 'public'
        private = client.create_project('sdk-private', visibility='private')
        assert private['visibility'] == 'private'
        assert client.set_visibility(private['id'], 'public')['visibility'] == 'public'
        monkeypatch.setattr(PlatformClient, 'from_profile', classmethod(lambda cls, *args, **kwargs: client))
        for slug, options, expected in [
            ('cli-default', [], 'public'),
            ('cli-private', ['--visibility', 'private'], 'private'),
        ]:
            created = CliRunner().invoke(main, ['platform', 'projects', 'create', slug, *options])
            assert created.exit_code == 0, created.output
            assert json.loads(created.output)['visibility'] == expected


@pytest.mark.parametrize('role', [None, 'viewer', 'deployer', 'account-admin'])
def test_visibility_and_domain_apply_require_project_owner(setup, role):
    s, native, owner, other = setup
    project = s.create_project(owner, 'owner-policy', visibility='private', request_key='owner-policy')
    actor = other
    if role == 'account-admin':
        actor = s.users.authenticate('admin', 'Example-admin-password!')
    elif role:
        s.grant(owner, project['id'], other.user_id, role)
    expected = 403 if role in {'viewer', 'deployer'} else 404
    for operation in [
        lambda: s.set_visibility(actor, project['id'], 'public'),
        lambda: s.set_domain(actor, project['id'], 'should-not-bind'),
        lambda: s.apply_domain(actor, project['id'], request_key='must-not-deploy'),
    ]:
        with pytest.raises(PlatformError) as error:
            operation()
        assert error.value.status == expected
    assert s.project(owner, project['id'])['visibility'] == 'private'
    assert not native.jobs
    assert environment(s.domains(owner, project['id']))['desired_url'] == 'https://owner-policy.example.test'


def test_signed_owner_policy_sync_is_not_a_password_reauthentication(setup, tmp_path, monkeypatch):
    from chatcomment import access
    from chatcomment.server import make_handler
    from chatcomment.store import Store

    s, native, owner, other = setup
    project = s.create_project(owner, 'policy-sync', visibility='private', request_key='policy-sync')
    store = Store(tmp_path / 'comments.sqlite3')
    initial = store.register('policy-site', title='Existing settings', origins=['https://policy-sync.example.test'],
                             pages=['/'], private=True)
    store.register('unrelated-site', title='Other project', origins=['https://other.example.test'], pages=['/'])
    key = secrets.token_urlsafe(48)
    captured = []
    original = access.sign_context

    def sign(context, **kwargs):
        headers = original(context, **kwargs)
        checked = access.verify_context(headers, **kwargs)
        assert checked.subject == owner.user_id
        assert checked.authenticated and checked.csrf_verified
        assert set(checked.sites) == {'policy-site'}
        assert checked.permits('policy-site', 'visibility')
        assert not checked.permits('policy-site', 'manage')
        assert checked.scope('policy-site').management_until == 0
        assert kwargs['method'] == 'POST' and kwargs['path'] == '/api/sites/policy-site/visibility'
        captured.append(json.loads(kwargs['body']))
        return headers

    monkeypatch.setattr(access, 'sign_context', sign)
    with local_server(make_handler(store, gateway_key=key)) as upstream:
        with s.connection(True) as db:
            db.execute('INSERT INTO services(id,project_id,site_id,native_uuid,upstream,adapter,secret) VALUES(?,?,?,?,?,?,?)',
                       ('comments', project['id'], 'policy-site', 'local-comments', upstream, 'chatcomment', key))
        assert s.set_visibility(owner, project['id'], 'public')['visibility'] == 'public'
        assert not store.site('policy-site')['private']
        assert s.set_visibility(owner, project['id'], 'private')['visibility'] == 'private'
        assert store.site('policy-site')['private']
        assert store.site('policy-site')['settings'] == initial['settings']
        assert store.site('unrelated-site')['private']
        assert captured == [{'private': False}, {'private': True}]
        with s.connection() as db:
            assert db.execute('SELECT COUNT(*) FROM management').fetchone()[0] == 0


@pytest.mark.parametrize('initial', ['public', 'private'])
@pytest.mark.parametrize('target', ['public', 'private'])
def test_policy_sync_backend_failure_never_opens_frontend(setup, initial, target):
    from http.server import BaseHTTPRequestHandler

    class FailedBackend(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.send_response(503)
            self.end_headers()

    s, native, owner, other = setup
    project = s.create_project(owner, 'failing-policy', visibility=initial, request_key='failing-policy')
    with local_server(FailedBackend) as upstream:
        with s.connection(True) as db:
            db.execute('INSERT INTO services(id,project_id,site_id,native_uuid,upstream,adapter,secret) VALUES(?,?,?,?,?,?,?)',
                       ('comments', project['id'], 'policy-site', 'local-comments', upstream,
                        'chatcomment', secrets.token_urlsafe(48)))
        with pytest.raises(PlatformError) as error:
            s.set_visibility(owner, project['id'], target)
        assert error.value.status == 502
        # Tightening must happen first. Failed opening retains the prior
        # policy; public->public does not undo a previously public website.
        expected = 'private' if target == 'private' else initial
        assert s.project(owner, project['id'])['visibility'] == expected


def test_apply_domain_uses_verified_published_bytes_not_preview_or_draft(setup, tmp_path, monkeypatch):
    s, native, owner, other = setup
    project = s.create_project(owner, 'published-bytes', request_key='published-bytes')
    published = upload(s, native, owner, project, tmp_path, 'published')
    first = s.deploy(owner, project['id'], published['id'], environment='production', request_key='first')
    # Model an immutable release built by an older runtime. Applying its domain
    # may create a new release, but must never rewrite the historical record.
    with s.connection(True) as db:
        db.execute('UPDATE releases SET dockerfile_sha256=? WHERE id=?', ('historical-runtime', published['id']))
    preview = upload(s, native, owner, project, tmp_path, 'preview-only')
    s.deploy(owner, project['id'], preview['id'], environment='preview', request_key='preview')
    draft = upload(s, native, owner, project, tmp_path, 'unpublished-draft')
    # A failed deployment with forged legacy finished metadata must not be
    # promoted to the verified current source merely because it is newest.
    native.next_status = 'failed'
    failed = s.deploy(owner, project['id'], draft['id'], environment='production', request_key='failed-draft')
    with s.connection(True) as db:
        db.execute("UPDATE deployments SET state='finished' WHERE id=?", (failed['id'],))
    native.next_status = 'finished'
    s.set_domain(owner, project['id'], 'new-published')
    original_upload = s.upload
    repackaged = []

    def observe_repackage(actor, project_id, data, **kwargs):
        value = original_upload(actor, project_id, data, **kwargs)
        native.artifacts[value['source_commit']] = value['artifact_sha256']
        repackaged.append((data, kwargs, value))
        return value

    monkeypatch.setattr(s, 'upload', observe_repackage)
    applied = s.apply_domain(owner, project['id'], request_key='apply-published')
    assert applied['state'] == 'finished' and applied['runtime_active'] and applied['runtime_verified']
    assert applied['artifact_sha256'] == published['artifact_sha256']
    assert applied['artifact_sha256'] not in {preview['artifact_sha256'], draft['artifact_sha256']}
    assert applied['url'] == 'https://new-published.example.test'
    assert applied['action'] == 'domain_apply'
    assert len(repackaged) == 1 and repackaged[0][1] == {'original_commit': 'a' * 40}
    assert repackaged[0][2]['id'] != published['id']
    assert validate_archive(repackaged[0][0])['index.html'] == b'published'
    with s.connection() as db:
        historical = db.execute('SELECT source_commit,dockerfile_sha256 FROM releases WHERE id=?',
                                (published['id'],)).fetchone()
    assert historical['source_commit'] == published['source_commit']
    assert historical['dockerfile_sha256'] == 'historical-runtime'
    assert validate_archive((s.root / 'artifacts' / (applied['artifact_sha256'] + '.zip')).read_bytes())['index.html'] == b'published'
    assert s.deployment(owner, project['id'], first['id'])['runtime_verified']
    assert environment(s.domains(owner, project['id']), 'preview')['current_url'] == 'https://published-bytes-preview.example.test'


def test_apply_domain_idempotency_rejects_environment_action_and_release_reuse(setup, tmp_path):
    s, native, owner, other = setup
    project = s.create_project(owner, 'apply-keys', request_key='apply-keys')
    published = upload(s, native, owner, project, tmp_path, 'published')
    s.deploy(owner, project['id'], published['id'], environment='production', request_key='publish-key')
    s.set_domain(owner, project['id'], 'keyed-domain')
    applied = s.apply_domain(owner, project['id'], request_key='domain-key')
    jobs = len(native.jobs)
    assert s.apply_domain(owner, project['id'], request_key='domain-key')['id'] == applied['id']
    assert len(native.jobs) == jobs
    for operation in [
        lambda: s.apply_domain(owner, project['id'], environment='preview', request_key='domain-key'),
        lambda: s.apply_domain(owner, project['id'], request_key='publish-key'),
        lambda: s.deploy(owner, project['id'], applied['release_id'], environment='production', request_key='domain-key'),
        lambda: s.deploy(owner, project['id'], applied['release_id'], environment='production', request_key='domain-key', rollback=True),
    ]:
        with pytest.raises(PlatformError) as error:
            operation()
        assert error.value.status == 409
    assert len(native.jobs) == jobs


@pytest.mark.parametrize('failure', ['configuration', 'build'])
def test_apply_domain_failure_preserves_proven_runtime_and_active_url(setup, tmp_path, failure):
    s, native, owner, other = setup
    project = s.create_project(owner, 'safe-apply', request_key='safe-apply')
    published = upload(s, native, owner, project, tmp_path, 'published')
    active = s.deploy(owner, project['id'], published['id'], environment='production', request_key='published')
    running = deepcopy(native.running)
    s.set_domain(owner, project['id'], 'attempted-rename')
    native.fail_configuration = failure == 'configuration'
    native.next_status = 'failed'
    if failure == 'configuration':
        with pytest.raises(PlatformError) as error:
            s.apply_domain(owner, project['id'], request_key='failed-apply')
        assert error.value.status == 502
    else:
        result = s.apply_domain(owner, project['id'], request_key='failed-apply')
        assert result['state'] == 'failed' and not result['runtime_verified']
    assert native.running == running
    addresses = environment(s.domains(owner, project['id']))
    assert addresses['current_url'] == active['url']
    assert addresses['desired_url'] == 'https://attempted-rename.example.test' and addresses['pending']
    assert s.deployment(owner, project['id'], active['id'])['runtime_verified']


def test_apply_domain_requires_verified_environment_and_intact_artifact(setup, tmp_path):
    s, native, owner, other = setup
    project = s.create_project(owner, 'not-published', request_key='not-published')
    with pytest.raises(PlatformError) as error:
        s.apply_domain(owner, project['id'], request_key='empty-apply')
    assert error.value.status == 409 and not native.jobs
    published = upload(s, native, owner, project, tmp_path, 'published')
    s.deploy(owner, project['id'], published['id'], environment='production', request_key='publish')
    s.set_domain(owner, project['id'], 'safe-name')
    path = s.root / 'artifacts' / (published['artifact_sha256'] + '.zip')
    path.write_bytes(b'corrupted local test fixture')
    before = len(native.jobs)
    with pytest.raises(PlatformError) as error:
        s.apply_domain(owner, project['id'], request_key='corrupted-apply')
    assert error.value.status == 409 and len(native.jobs) == before
    assert environment(s.domains(owner, project['id']))['current_url'] == 'https://not-published.example.test'


class ConsoleForms(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        value = dict(attrs)
        if tag == 'form':
            self.current = {'attrs': value, 'inputs': [], 'options': []}
            self.forms.append(self.current)
        elif self.current is not None and tag in {'input', 'option'}:
            self.current['inputs' if tag == 'input' else 'options'].append(value)

    def handle_endtag(self, tag):
        if tag == 'form':
            self.current = None


def test_console_real_forms_scoped_to_owner_and_api_rejects_viewer_writes(setup, tmp_path):
    s, native, owner, viewer = setup
    project = s.create_project(owner, 'editable-site', request_key='editable-site')
    s.grant(owner, project['id'], viewer.user_id, 'viewer')
    published = upload(s, native, owner, project, tmp_path, 'console-published')
    s.deploy(owner, project['id'], published['id'], environment='production', request_key='console-publish')
    with local_server(PlatformHandler, platform=s) as origin:
        for username, password, is_owner in [
            ('alice', 'Example-alice-password!', True),
            ('bobby', 'Example-bobby-password!', False),
        ]:
            login = s.login(username, password)
            session = s.control_session(login['token'])
            headers = {'Cookie': COOKIE + '=' + login['token']}
            with urlopen(Request(origin + '/', headers=headers)) as response:
                page = response.read().decode()
            parsed = ConsoleForms()
            parsed.feed(page)
            create = next(f for f in parsed.forms if f['attrs'].get('data-kind') == 'create')
            assert next(o['value'] for o in create['options'] if 'selected' in o) == 'public'
            assert {'slug', 'name'} <= {i.get('name') for i in create['inputs']}
            project_forms = [f for f in parsed.forms if f['attrs'].get('data-project') == project['id']]
            if is_owner:
                assert len(project_forms) == 3
                policy = next(f for f in project_forms if f['attrs']['data-kind'] == 'visibility')
                assert next(o['value'] for o in policy['options'] if 'selected' in o) == 'public'
                domain = [f for f in project_forms if f['attrs']['data-kind'] == 'domain']
                assert {f['attrs']['data-environment'] for f in domain} == {'production', 'preview'}
                assert {f['inputs'][0]['value'] for f in domain} == {'editable-site', 'editable-site-preview'}
                assert {f['attrs']['data-environment']: f['attrs']['data-live'] for f in domain} == {
                    'production': '1', 'preview': '0'}
            else:
                assert not project_forms
            # Hiding forms is only presentation: direct authenticated HTTP
            # requests must enforce the same ACL and cookie CSRF rules.
            for route, method, payload in [
                ('', 'PATCH', {'visibility': 'private'}),
                ('/domains/production', 'PUT', {'hostname': 'viewer-cannot-bind'}),
                ('/domains/production/apply', 'POST', {'request_key': 'viewer-cannot-apply'}),
            ]:
                request = Request(origin + '/api/platform/v1/projects/' + project['id'] + route,
                                  method=method, data=json.dumps(payload).encode(), headers={
                                      **headers, 'Content-Type': 'application/json',
                                      'Origin': s.control_url, 'X-CSRF-Token': session.csrf_token})
                if not is_owner:
                    with pytest.raises(HTTPError) as error:
                        urlopen(request)
                    assert error.value.code == 403
            if is_owner:
                for invalid_headers in [
                    headers,
                    {**headers, 'Origin': s.control_url},
                    {**headers, 'Origin': 'https://attacker.example.test', 'X-CSRF-Token': session.csrf_token},
                ]:
                    with pytest.raises(HTTPError) as error:
                        urlopen(Request(origin + '/api/platform/v1/projects/' + project['id'], method='PATCH',
                                        data=b'{"visibility":"private"}', headers=invalid_headers))
                    assert error.value.code == 403
        assert s.project(owner, project['id'])['visibility'] == 'public'
