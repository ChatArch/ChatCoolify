"""Local-only credentials and upload-policy contracts; no real service requests."""
import io
import json
import zipfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest
from click.testing import CliRunner
from chatenv import EnvStore, get_paths
from chatenv.tokens import TokenStore
from chatcoolify.cli import main
from chatcoolify.config import PlatformConfig, PlatformServerConfig
from chatcoolify.platform_artifact import PlatformError
from chatcoolify.platform_client import PlatformClient
from chatcoolify.platform_web import PlatformHandler
from test_platform_domains import setup
from test_platform_management import local_server


def limits_type():
    import chatcoolify.platform_artifact as artifact
    assert hasattr(artifact, 'ArtifactLimits'), 'Artifact policy must be importable and configurable'
    return artifact.ArtifactLimits


def archive(contents):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_STORED) as result:
        for name, data in contents.items():
            result.writestr(name, data)
    return stream.getvalue()


def save_credentials(home, profile='work', username='alice', password='Profile-canary-secret!'):
    values = {'CHATCOOLIFY_PLATFORM_URL': 'https://platform.example.test',
              'CHATCOOLIFY_PLATFORM_USERNAME': username, 'CHATCOOLIFY_PLATFORM_PASSWORD': password}
    EnvStore(get_paths(home).envs_dir).save_profile(PlatformConfig, profile, values)
    return values


def test_chatenv_schema_owns_sensitive_credentials_and_server_policy():
    assert hasattr(PlatformConfig, 'CHATCOOLIFY_PLATFORM_USERNAME')
    assert hasattr(PlatformConfig, 'CHATCOOLIFY_PLATFORM_PASSWORD')
    assert PlatformConfig.CHATCOOLIFY_PLATFORM_PASSWORD.is_sensitive
    assert hasattr(PlatformServerConfig, 'CHATCOOLIFY_MAX_UPLOAD_BYTES')
    assert hasattr(PlatformServerConfig, 'CHATCOOLIFY_MAX_EXPANDED_BYTES')
    assert hasattr(PlatformServerConfig, 'CHATCOOLIFY_MAX_ARTIFACT_FILES')


def test_default_policy_is_one_gib_without_expanded_or_entry_gate():
    limits = limits_type()()
    assert limits.max_upload_bytes == 1073741824
    assert limits.max_expanded_bytes == 0
    assert limits.max_files == 0


def test_configurable_archive_limits_and_zero_disable():
    from chatcoolify.platform_artifact import validate_archive
    Policy = limits_type()
    raw = archive({'index.html': b'home', 'data.bin': b'0123456789'})
    for policy in (Policy(max_upload_bytes=len(raw)-1), Policy(max_expanded_bytes=13), Policy(max_files=1)):
        with pytest.raises(PlatformError) as error:
            validate_archive(raw, limits=policy)
        assert error.value.status == 413
    assert validate_archive(raw, limits=Policy(0, 0, 0))['data.bin'] == b'0123456789'


def test_default_accepts_above_old_byte_and_entry_limits():
    from chatcoolify.platform_artifact import validate_archive
    limits_type()
    raw = archive({'index.html': b'home', 'large.bin': b'x' * (33*1024*1024)})
    assert 'large.bin' in validate_archive(raw, read_files=False)
    del raw
    raw = archive({'index.html': b'home', **{f'assets/{number}.txt': b'' for number in range(2001)}})
    assert len(validate_archive(raw, read_files=False)) == 2002


def test_zero_limits_keep_path_security():
    from chatcoolify.platform_artifact import validate_archive
    Policy = limits_type()
    with pytest.raises(PlatformError) as error:
        validate_archive(archive({'index.html': b'ok', '../escape': b'bad'}), limits=Policy(0, 0, 0))
    assert error.value.status == 422


def test_effective_limits_endpoint_is_authenticated(setup):
    service, native, owner, other = setup
    Policy = limits_type()
    service.artifact_limits = Policy(12345, 0, 0)
    with local_server(PlatformHandler, platform=service) as origin:
        with pytest.raises(HTTPError) as error:
            urlopen(origin + '/api/platform/v1/limits')
        assert error.value.code == 401
        client = PlatformClient(origin)
        client.login('alice', 'Example-alice-password!')
        assert client.request('/limits') == {'max_upload_bytes': 12345, 'max_expanded_bytes': 0, 'max_files': 0}


def test_cli_login_reads_selected_chatenv_profile_and_keeps_credentials(tmp_path, monkeypatch):
    home = tmp_path / 'client'
    selected = save_credentials(home)
    other = save_credentials(home, 'other', username='someone-else', password='Other-profile-canary!')
    calls = []
    def request(self, path, *, method='GET', payload=None, **kwargs):
        calls.append((path, method, payload))
        assert path == '/login'
        assert payload == {'username': 'alice', 'password': selected['CHATCOOLIFY_PLATFORM_PASSWORD']}
        return {'token': 'fixture-session', 'principal': {'role': 'user'}, 'expires_at': 4102444800}
    monkeypatch.setattr(PlatformClient, 'request', request)
    monkeypatch.setenv('CHATCOOLIFY_PLATFORM_USERNAME', 'wrong-process-account')
    monkeypatch.setenv('CHATCOOLIFY_PLATFORM_PASSWORD', 'Wrong-process-canary!')
    result = CliRunner().invoke(main, ['platform', '--home', str(home), '--profile', 'work', 'login'])
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert 'Profile-canary' not in result.output and 'Wrong-process' not in result.output
    assert EnvStore(get_paths(home).envs_dir).load_profile(PlatformConfig, 'work') == selected
    assert EnvStore(get_paths(home).envs_dir).load_profile(PlatformConfig, 'other') == other
    assert TokenStore(home=home).read('ChatCoolifyPlatform', 'work')['values']['token'] == 'fixture-session'


def test_sdk_save_preserves_credentials_and_from_profile_can_login(tmp_path, monkeypatch):
    home = tmp_path / 'client'
    selected = save_credentials(home)
    calls = []
    def request(self, path, *, method='GET', payload=None, **kwargs):
        calls.append(path)
        if path == '/login':
            assert payload == {'username': 'alice', 'password': selected['CHATCOOLIFY_PLATFORM_PASSWORD']}
            return {'token': 'fixture-new-session', 'principal': {'role': 'user'}, 'expires_at': 4102444800}
        assert path == '/session'
        return {'principal': {'role': 'user'}}
    monkeypatch.setattr(PlatformClient, 'request', request)
    client = PlatformClient.from_profile('work', home=home)
    assert client.token == 'fixture-new-session'
    client.save('work', home=home)
    assert EnvStore(get_paths(home).envs_dir).load_profile(PlatformConfig, 'work') == selected
    assert calls.count('/login') == 1


def test_profile_expired_session_renews_before_mutation_without_replay(tmp_path, monkeypatch):
    home = tmp_path / 'client'
    selected = save_credentials(home)
    TokenStore(home=home).write('ChatCoolifyPlatform', 'work', values={'token': 'expired-fixture'},
        summary={'url': 'https://platform.example.test'})
    calls = []
    def request(self, path, *, method='GET', payload=None, **kwargs):
        calls.append((path, method))
        if path == '/session':
            if self.token == 'expired-fixture':
                raise PlatformError(401, 'Session expired')
            return {'principal': {'role': 'user'}}
        if path == '/login':
            assert payload['username'] == 'alice'
            return {'token': 'renewed-fixture', 'principal': {'role': 'user'}, 'expires_at': 4102444800}
        assert path == '/projects/site/publish'
        raise PlatformError(502, 'Outcome unknown; preserve the request key')
    monkeypatch.setattr(PlatformClient, 'request', request)
    client = PlatformClient.from_profile('work', home=home)
    assert client.token == 'renewed-fixture'
    with pytest.raises(PlatformError):
        client.request('/projects/site/publish', method='POST', payload={'request_key': 'same-key'})
    assert calls.count(('/login', 'POST')) == 1
    assert calls.count(('/projects/site/publish', 'POST')) == 1


def test_client_upload_uses_server_policy_before_packing(tmp_path, monkeypatch):
    limits_type()
    site = tmp_path / 'site'
    site.mkdir()
    (site / 'index.html').write_text('test')
    calls = []
    def request(self, path, **kwargs):
        calls.append(path)
        if path == '/limits':
            return {'max_upload_bytes': 1, 'max_expanded_bytes': 0, 'max_files': 0}
        raise AssertionError('An oversized artifact must not be uploaded')
    monkeypatch.setattr(PlatformClient, 'request', request)
    client = PlatformClient('https://platform.example.test', 'fixture')
    with pytest.raises(PlatformError) as error:
        client.upload('site', site)
    assert error.value.status == 413 and calls == ['/limits']


@pytest.mark.parametrize('value', ['-1', 'not-a-number', '1.5', True])
def test_invalid_server_policy_fails_closed(value):
    Policy = limits_type()
    with pytest.raises(PlatformError):
        Policy.from_values({'CHATCOOLIFY_MAX_UPLOAD_BYTES': value})


def test_server_policy_zero_strings_are_not_replaced_by_defaults():
    Policy = limits_type()
    assert Policy.from_values({'CHATCOOLIFY_MAX_UPLOAD_BYTES': '0',
        'CHATCOOLIFY_MAX_EXPANDED_BYTES': '0', 'CHATCOOLIFY_MAX_ARTIFACT_FILES': '0'}) == Policy(0, 0, 0)


def test_legacy_policy_fallback_is_only_for_404(monkeypatch):
    Policy = limits_type()
    client = PlatformClient('https://platform.example.test', 'fixture')
    def missing(*args, **kwargs):
        raise PlatformError(404, 'Old server')
    monkeypatch.setattr(client, 'request', missing)
    assert client.limits() == Policy(8*1024*1024, 32*1024*1024, 2000)
    def denied(*args, **kwargs):
        raise PlatformError(401, 'Expired')
    monkeypatch.setattr(client, 'request', denied)
    with pytest.raises(PlatformError) as error:
        client.limits()
    assert error.value.status == 401


def test_invalid_profile_origin_is_rejected_before_token_lookup(tmp_path, monkeypatch):
    home = tmp_path/'client'
    values = save_credentials(home)
    values['CHATCOOLIFY_PLATFORM_URL'] = 'http://remote.example.test'
    EnvStore(get_paths(home).envs_dir).save_profile(PlatformConfig, 'work', values)
    calls = []
    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError('Token resolution must follow URL validation')
    monkeypatch.setattr(TokenStore, 'read', forbidden)
    with pytest.raises(PlatformError) as error:
        PlatformClient.from_profile('work', home=home)
    assert error.value.status == 422 and not calls


def test_url_and_token_only_legacy_profile_remains_usable(tmp_path, monkeypatch):
    home = tmp_path/'client'
    EnvStore(get_paths(home).envs_dir).save_profile(PlatformConfig, 'legacy',
        {'CHATCOOLIFY_PLATFORM_URL': 'https://platform.example.test'})
    TokenStore(home=home).write('ChatCoolifyPlatform', 'legacy', values={'token': 'legacy-session'},
        summary={'url': 'https://platform.example.test'})
    def forbidden(*args, **kwargs):
        raise AssertionError('Do not invent credential renewal for token-only profiles')
    monkeypatch.setattr(PlatformClient, 'request', forbidden)
    assert PlatformClient.from_profile('legacy', home=home).token == 'legacy-session'


def test_limits_cli_reports_effective_policy(monkeypatch):
    Policy = limits_type()
    class Client:
        def limits(self):
            return Policy()
    monkeypatch.setattr(PlatformClient, 'from_profile', classmethod(lambda cls, *args, **kwargs: Client()))
    result = CliRunner().invoke(main, ['platform', '--profile', 'work', 'limits'])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == Policy().as_dict()


def test_http_custom_artifact_limit_does_not_enlarge_control_body(setup):
    from email.message import Message
    from types import SimpleNamespace
    Policy = limits_type()
    handler = object.__new__(PlatformHandler)
    handler.server = SimpleNamespace(platform=SimpleNamespace(artifact_limits=Policy(0, 0, 0)))
    handler.headers = Message()
    handler.headers['Content-Length'] = str(9*1024*1024)
    class Unread:
        def read(self, size):
            raise AssertionError('Oversized control body must be rejected before reading')
    handler.rfile = Unread()
    with pytest.raises(PlatformError) as error:
        handler.body()
    assert error.value.status == 413
    service, native, owner, other = setup
    service.artifact_limits = Policy(100, 0, 0)
    project = service.create_project(owner, 'tiny-upload', request_key='tiny')
    with local_server(PlatformHandler, platform=service) as origin:
        client = PlatformClient(origin)
        client.login('alice', 'Example-alice-password!')
        with pytest.raises(PlatformError) as error:
            client.request('/projects/'+project['id']+'/releases', method='POST', data=archive({'index.html': b'home'}))
        assert error.value.status == 413
        assert service.releases(owner, project['id']) == []


def test_actual_chatenv_dispatcher_authenticates_selected_profile(setup, tmp_path):
    from chatenv.cli import cli as command
    service, native, owner, other = setup
    home = tmp_path/'dispatcher-home'
    with local_server(PlatformHandler, platform=service) as origin:
        EnvStore(get_paths(home).envs_dir).save_profile(PlatformConfig, 'work', {
            'CHATCOOLIFY_PLATFORM_URL': origin, 'CHATCOOLIFY_PLATFORM_USERNAME': 'alice',
            'CHATCOOLIFY_PLATFORM_PASSWORD': 'Example-alice-password!'})
        result = CliRunner().invoke(command, ['--home', str(home), 'test', 'work', '-t', 'coolify-platform', '-I'])
        assert result.exit_code == 0, result.output
        assert 'authentication passed' in result.output
        assert 'Example-alice-password' not in result.output
        assert not TokenStore(home=home).read('ChatCoolifyPlatform', 'work').get('values', {}).get('token')


def test_cached_bearer_is_not_sent_to_changed_profile_origin(tmp_path, monkeypatch):
    home = tmp_path/'client'
    save_credentials(home)
    TokenStore(home=home).write('ChatCoolifyPlatform', 'work', values={'token': 'old-origin-token'},
        summary={'url': 'https://previous.example.test'})
    calls = []
    def request(self, path, *, method='GET', payload=None, **kwargs):
        calls.append((path, self.token))
        assert self.token != 'old-origin-token', 'Cached bearer must remain bound to its issuing origin'
        assert path == '/login'
        return {'token': 'new-origin-session', 'principal': {'username': 'alice'}, 'expires_at': 4102444800}
    monkeypatch.setattr(PlatformClient, 'request', request)
    assert PlatformClient.from_profile('work', home=home).token == 'new-origin-session'
    assert calls == [('/login', None)]


def test_cli_url_override_does_not_reuse_saved_password(tmp_path, monkeypatch):
    home = tmp_path/'client'
    save_credentials(home)
    calls = []
    def request(self, path, **kwargs):
        calls.append(path)
        return {'token': 'unexpected', 'principal': {'username': 'alice'}}
    monkeypatch.setattr(PlatformClient, 'request', request)
    result = CliRunner().invoke(main, ['platform', '--home', str(home), '--profile', 'work',
        'login', '--url', 'https://different.example.test'])
    assert result.exit_code != 0 and not calls
    assert 'Profile-canary-secret' not in result.output


def test_cached_session_identity_matches_selected_username(tmp_path, monkeypatch):
    home = tmp_path/'client'
    save_credentials(home, username='bobby', password='Bobby-selected-canary!')
    TokenStore(home=home).write('ChatCoolifyPlatform', 'work', values={'token': 'alice-session'},
        summary={'url': 'https://platform.example.test'})
    calls = []
    def request(self, path, *, method='GET', payload=None, **kwargs):
        calls.append(path)
        if path == '/session':
            return {'principal': {'username': 'alice', 'user_id': 'alice-id'}}
        assert path == '/login' and self.token is None
        assert payload == {'username': 'bobby', 'password': 'Bobby-selected-canary!'}
        return {'token': 'bobby-session', 'principal': {'username': 'bobby'}, 'expires_at': 4102444800}
    monkeypatch.setattr(PlatformClient, 'request', request)
    assert PlatformClient.from_profile('work', home=home).token == 'bobby-session'
    assert calls == ['/session', '/login']


def test_saving_session_for_new_origin_does_not_carry_old_password(tmp_path):
    home = tmp_path/'client'
    save_credentials(home)
    client = PlatformClient('https://different.example.test', 'new-session')
    client.save('work', home=home)
    saved = EnvStore(get_paths(home).envs_dir).load_profile(PlatformConfig, 'work')
    assert saved['CHATCOOLIFY_PLATFORM_URL'] == 'https://different.example.test'
    assert not saved.get('CHATCOOLIFY_PLATFORM_USERNAME') and not saved.get('CHATCOOLIFY_PLATFORM_PASSWORD')


def test_username_only_profile_cannot_use_another_accounts_session(tmp_path, monkeypatch):
    home = tmp_path/'client'
    EnvStore(get_paths(home).envs_dir).save_profile(PlatformConfig, 'work', {
        'CHATCOOLIFY_PLATFORM_URL': 'https://platform.example.test', 'CHATCOOLIFY_PLATFORM_USERNAME': 'bobby'})
    TokenStore(home=home).write('ChatCoolifyPlatform', 'work', values={'token': 'alice-session'},
        summary={'url': 'https://platform.example.test'})
    calls = []
    def request(self, path, **kwargs):
        calls.append(path)
        return {'principal': {'username': 'alice'}}
    monkeypatch.setattr(PlatformClient, 'request', request)
    with pytest.raises(PlatformError) as error:
        PlatformClient.from_profile('work', home=home)
    assert error.value.status == 401 and calls == ['/session']


def test_saving_same_origin_with_trailing_slash_preserves_credentials(tmp_path):
    home = tmp_path/'client'
    values = save_credentials(home)
    values['CHATCOOLIFY_PLATFORM_URL'] += '/'
    EnvStore(get_paths(home).envs_dir).save_profile(PlatformConfig, 'work', values)
    PlatformClient('https://platform.example.test', 'cached-session').save('work', home=home)
    saved = EnvStore(get_paths(home).envs_dir).load_profile(PlatformConfig, 'work')
    assert saved['CHATCOOLIFY_PLATFORM_USERNAME'] == values['CHATCOOLIFY_PLATFORM_USERNAME']
    assert saved['CHATCOOLIFY_PLATFORM_PASSWORD'] == values['CHATCOOLIFY_PLATFORM_PASSWORD']
