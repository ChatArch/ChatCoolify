"""Reusable immutable frontend runtime, also guarding raw Coolify origins.

This file uses only stdlib and is embedded in native Coolify-built images.
It never pulls releases or switches versions: image contents are immutable.
"""
from __future__ import annotations

import html
import hmac
import hashlib
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
import secrets
import re
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

COOKIE = '__Host-platform-reader'
STATE_COOKIE = '__Host-platform-login-state'
GUEST_COOKIE = '__Host-platform-guest'
MAX_BODY = 2 * 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class FrontendHandler(BaseHTTPRequestHandler):
    server_version = 'ChatCoolifyFrontend'

    def log_message(self, *args):
        # Paths, query strings and cookies can contain private content.
        pass

    def end_headers(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'same-origin')
        self.send_header('Cache-Control', 'private, no-store')
        super().end_headers()

    def respond(self, status, body=b'', kind='application/json; charset=utf-8', headers=None):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        for cookie in getattr(self,'_guest_response_cookies',[]):
            self.send_header('Set-Cookie',cookie)
        for k, v in (headers or {}).items():
            for item in (v if isinstance(v,list) else [v]):
                self.send_header(k, item)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def token(self, name=COOKIE):
        c = SimpleCookie()
        try:
            c.load(self.headers.get('Cookie', ''))
        except Exception:
            return ''
        return c[name].value if name in c else ''

    def body(self):
        size = int(self.headers.get('Content-Length', '0'))
        if not 0 <= size <= MAX_BODY:
            raise ValueError('Request too large')
        return self.rfile.read(size)

    def broker(self, endpoint, payload):
        value = {'application_id': os.environ['PLATFORM_APPLICATION_ID'], **payload}
        data = json.dumps(value).encode()
        req = Request(os.environ['PLATFORM_INTERNAL_URL'].rstrip('/') + '/internal/v1/' + endpoint,
                      data=data, headers={'Content-Type': 'application/json',
                                          'Authorization': 'Bearer ' + os.environ['PLATFORM_APPLICATION_KEY']})
        try:
            with build_opener(NoRedirect()).open(req, timeout=15) as r:
                raw = r.read(3 * 1024 * 1024 + 1)
                if len(raw) > 3 * 1024 * 1024:
                    raise ValueError('Broker response too large')
                return r.status, json.loads(raw)
        except HTTPError as exc:
            return exc.code, {'error': 'Access denied'}
        except (URLError, OSError, ValueError):
            return 503, {'error': 'Authorization unavailable'}

    def context(self):
        return {'reader_token': self.token(), 'guest_token':self.token(GUEST_COOKIE),
                'method': self.command, 'path': self.path,
                'origin': self.headers.get('Origin', ''),
                'csrf': self.headers.get('X-CSRF-Token', ''),
                'host': self.headers.get('Host', '')}

    def redirect_login(self,return_path=None):
        state=secrets.token_urlsafe(40)
        target = os.environ['PLATFORM_CONTROL_URL'].rstrip('/') + '/login?' + urlencode({
            'application': os.environ['PLATFORM_APPLICATION_ID'], 'state':state,
            'return_path':self.path if return_path is None else return_path})
        self.respond(303, b'', headers={'Location': target,'Set-Cookie':
            f'{STATE_COOKIE}={state}; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=120'})

    def do_HEAD(self):
        self.handle_request()

    def do_GET(self):
        self.handle_request()

    def do_POST(self):
        self.handle_request()

    def do_PATCH(self):
        self.handle_request()

    def do_DELETE(self):
        self.handle_request()

    def handle_request(self):
        self._guest_response_cookies=[]
        try:
            path = urlsplit(self.path).path
            if path == '/__platform/health' and self.command in {'GET', 'HEAD'}:
                return self.respond(200, {'ok': True})
            allowed = {urlsplit(u).netloc for u in os.environ.get('PLATFORM_PUBLIC_URLS', '').split(',') if u}
            if self.headers.get('Host') not in allowed:
                return self.respond(421, {'error': 'Unregistered host'})
            if path == '/__platform/artifact' and self.command in {'GET','HEAD'} and self.headers.get('X-Platform-Probe'):
                proof=self.headers['X-Platform-Probe'].split(':',1)
                if len(proof)!=2 or abs(time.time()-int(proof[0]))>30:
                    return self.respond(403,{'error':'Invalid probe'})
                expected=hmac.new(os.environ['PLATFORM_APPLICATION_KEY'].encode(),
                    ('artifact|'+proof[0]+'|'+os.environ['PLATFORM_APPLICATION_ID']).encode(),hashlib.sha256).hexdigest()
                if not hmac.compare_digest(expected,proof[1]):return self.respond(403,{'error':'Invalid probe'})
                return self.respond(200,{'artifact_sha256':os.environ['PLATFORM_ARTIFACT_SHA256'],
                    'runtime_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    'domain_generation':os.environ.get('PLATFORM_DOMAIN_GENERATION','0'),
                    'public_urls':[u for u in os.environ.get('PLATFORM_PUBLIC_URLS','').split(',') if u]})
            # The broker commits the canonical URL only after the new native
            # container is healthy and its exact runtime/configuration is proven.
            # Until then this new image continues serving the old private origin.
            status,canonical=self.broker('canonical',{'host':self.headers.get('Host','')})
            if status!=200:return self.respond(status,canonical)
            primary=canonical.get('url','')
            if primary not in os.environ.get('PLATFORM_PUBLIC_URLS','').split(','):
                return self.respond(503,{'error':'Application domain configuration is pending'})
            if self.headers.get('Host')!=urlsplit(primary).netloc:
                if self.command in {'GET','HEAD'}:
                    # Construct from a registered origin and this request's
                    # relative path, never a caller-controlled Host or absolute URL.
                    parsed_path=urlsplit(self.path)
                    target=primary.rstrip('/')+(parsed_path.path or '/')
                    if parsed_path.query:target+='?'+parsed_path.query
                    return self.respond(308,b'',headers={'Location':target})
                return self.respond(421,{'error':'Use the canonical application origin'})
            if path=='/__platform/login' and self.command in {'GET','HEAD'}:
                destination=parse_qs(urlsplit(self.path).query,max_num_fields=4).get('return_path',['/'])[0]
                if (not destination.startswith('/') or destination.startswith('//') or '\\' in destination
                        or len(destination)>2048 or any(ord(c)<32 for c in destination)):
                    return self.respond(400,{'error':'Invalid return path'})
                return self.redirect_login(destination)
            if path == '/__platform/callback' and self.command == 'POST':
                if self.headers.get('Origin') != os.environ['PLATFORM_CONTROL_URL'].rstrip('/'):
                    return self.respond(403, {'error': 'Invalid login origin'})
                form = parse_qs(self.body().decode(), max_num_fields=6)
                state=form.get('state',[''])[0]
                if not state or not hmac.compare_digest(state,self.token(STATE_COOKIE)):
                    return self.respond(403,{'error':'Login transaction mismatch'})
                status, value = self.broker('exchange', {'code': form.get('code', [''])[0],
                                                        'state':state,'host': self.headers.get('Host')})
                if status != 200:
                    return self.respond(status, value)
                cookie = f"{COOKIE}={value['token']}; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=86400"
                return self.respond(303, b'', headers={'Location': value['return_path'], 'Set-Cookie': [cookie,
                    f'{STATE_COOKIE}=; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=0']})
            status, access = self.broker('authorize', self.context())
            if status == 401 and self.command in {'GET', 'HEAD'}:
                return self.redirect_login()
            if status != 200:
                return self.respond(status, access)
            guest=access.pop('_guest_cookie',None)
            age=access.pop('_guest_max_age',None)
            if guest is not None:
                if (not isinstance(guest,str) or not guest.isascii() or not 1<=len(guest)<=256
                        or any(not(c.isalnum() or c in '._-') for c in guest)
                        or type(age) is not int or not 1<=age<=1800):
                    return self.respond(503,{'error':'Guest session unavailable'})
                self._guest_response_cookies.append(
                    f'{GUEST_COOKIE}={guest}; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age={age}')
            if path == '/__platform/manage' and self.command in {'GET', 'HEAD'}:
                if access.get('authenticated') is not True or access.get('can_manage_project') is not True:
                    return self.respond(403, {'error': 'Project owner permission required'})
                target=access.get('management_url')
                if not isinstance(target,str):
                    return self.respond(503, {'error': 'Management destination unavailable'})
                destination=urlsplit(target)
                control=urlsplit(os.environ['PLATFORM_CONTROL_URL'])
                if (destination.scheme!=control.scheme or destination.netloc!=control.netloc
                        or destination.username or destination.password or destination.path!='/'
                        or destination.query or not re.fullmatch(r'project-[A-Za-z0-9_-]{1,80}',destination.fragment)):
                    return self.respond(503, {'error': 'Management destination unavailable'})
                return self.respond(303, b'', headers={'Location':target})
            if path == '/__platform/session':
                return self.respond(200, access)
            if path == '/__platform/artifact' and self.command in {'GET', 'HEAD'}:
                return self.respond(200, {'artifact_sha256': os.environ['PLATFORM_ARTIFACT_SHA256']})
            if path in {'/__platform/reauth', '/__platform/logout'} and self.command == 'POST':
                if not access.get('authenticated'):
                    return self.respond(403,{'error':'Account sign-in required for this operation'})
                payload = json.loads(self.body() or b'{}')
                status, result = self.broker(path.rsplit('/', 1)[1], {**self.context(), 'payload': payload})
                headers = {'Set-Cookie': f'{COOKIE}=; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=0'} if path.endswith('/logout') else {}
                return self.respond(status, result, headers=headers)
            aliases = json.loads(os.environ.get('PLATFORM_ROUTE_ALIASES', '{}'))
            service_path = self.path
            for prefix, target in aliases.items():
                if path == prefix.rstrip('/') or path.startswith(prefix):
                    service_path = target.rstrip('/') + self.path[len(prefix.rstrip('/')):]
                    break
            if urlsplit(service_path).path.startswith('/__platform/services/'):
                import base64
                raw = self.body() if self.command not in {'GET', 'HEAD'} else b''
                status, result = self.broker('service', {**self.context(), 'path': service_path,
                    'body_b64': base64.b64encode(raw).decode(),
                    'content_type': self.headers.get('Content-Type', '')})
                if status != 200:
                    return self.respond(status, result)
                response_headers = {k: v for k, v in result.get('headers', {}).items()
                                    if k.lower() in {'location', 'content-disposition'}}
                return self.respond(result['status'], base64.b64decode(result['body_b64']),
                                    result['content_type'], response_headers)
            if self.command not in {'GET', 'HEAD'}:
                return self.respond(405, {'error': 'Method not allowed'})
            if not access.get('read'):
                return self.respond(403, {'error': 'Project permission required'})
            name = unquote(path).lstrip('/')
            if any(p in {'.', '..'} or p.startswith('.') for p in name.split('/') if p) or '\\' in name or '\x00' in name:
                return self.respond(404, {'error': 'File unavailable'})
            root = Path('/app/site')
            target = root / name
            if target.is_dir():
                if not path.endswith('/'):
                    return self.respond(308, b'', headers={'Location': path + '/'})
                target = target / 'index.html'
            if not target.is_file() or root not in target.resolve().parents:
                return self.respond(404, {'error': 'File unavailable'})
            kind = mimetypes.guess_type(str(target))[0] or 'application/octet-stream'
            return self.respond(200, target.read_bytes(), kind)
        except (KeyError, ValueError, TypeError, OSError):
            self.respond(400, {'error': 'Invalid request'})


if __name__ == '__main__':
    import sys
    if sys.argv[1:]==['health']:
        with build_opener().open('http://127.0.0.1:8080/__platform/health',timeout=2) as response:
            if response.status!=200:raise SystemExit(1)
    else:
        ThreadingHTTPServer(('0.0.0.0', 8080), FrontendHandler).serve_forever()
