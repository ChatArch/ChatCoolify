"""Project permissions, immutable build inputs and native deployment tracking."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
import base64
import hashlib
import hmac
import importlib
import json
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError
import uuid

from chatlogin import ManagedUsers, ManagedError, Role

from .platform_artifact import PlatformError, validate_archive, digest
from .platform_source import GitSources,frontend_files


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', value):
        raise PlatformError(422, 'Invalid resource identifier')
    return value


def safe_return(value):
    if (not isinstance(value, str) or len(value) > 2048 or not value.startswith('/')
            or value.startswith('//') or '\\' in value or any(ord(c) < 32 for c in value)):
        raise PlatformError(422, 'Invalid return path')
    return value


DOMAIN_LABEL=re.compile(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?')
RESERVED_DOMAIN_LABELS=frozenset({'platform','control','coolify','admin','api','auth','login','logout',
    'account','accounts','www','mail','smtp','ftp','ssh','ns1','ns2','status','metrics','internal'})


def domain_hostname(value):
    if (not isinstance(value,str) or value!=value.strip() or not value.isascii()
            or len(value)>253 or not value or any(not DOMAIN_LABEL.fullmatch(p) for p in value.lower().split('.'))):
        raise PlatformError(422,'Invalid domain hostname')
    return value.lower()


class PlatformService:
    """Importable service; HTTP/CLI adapters do not own lifecycle decisions."""
    def __init__(self, root, backend, *, control_url, internal_url=None, domain_suffix=None, reserved_hostnames=()):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        self.database = self.root / 'platform.sqlite3'
        self.users = ManagedUsers.for_instance('chatcoolify-platform', home=self.root / 'identity', ttl=86400)
        self.sources = GitSources(self.root / 'repos')
        self.backend = backend
        self.control_url = control_url.rstrip('/')
        self.internal_url = (internal_url or control_url).rstrip('/')
        control_host=urlsplit(self.control_url).hostname or ''
        if not domain_suffix:
            if not control_host.startswith('platform.'):
                raise PlatformError(422,'Configure the operator-managed domain suffix')
            domain_suffix=control_host[len('platform.'):]
        self.domain_suffix=domain_hostname(domain_suffix)
        if '.' not in self.domain_suffix:raise PlatformError(422,'Managed domain suffix requires a DNS domain')
        self.reserved_hostnames={domain_hostname(h) for h in reserved_hostnames if h}
        self.reserved_hostnames.add(domain_hostname(control_host))
        self.lock = threading.RLock()
        with self.connection() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,slug TEXT UNIQUE,name TEXT,owner_id TEXT,
                visibility TEXT,created_at REAL,request_key TEXT,native_uuid TEXT,state TEXT,UNIQUE(owner_id,request_key));
              CREATE TABLE IF NOT EXISTS grants(project_id TEXT,user_id TEXT,role TEXT,PRIMARY KEY(project_id,user_id));
              CREATE TABLE IF NOT EXISTS emails(user_id TEXT PRIMARY KEY,email TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS releases(id TEXT PRIMARY KEY,project_id TEXT,artifact_sha256 TEXT,
                dockerfile_sha256 TEXT,source_commit TEXT,original_commit TEXT,created_by TEXT,created_at REAL,
                UNIQUE(project_id,artifact_sha256,dockerfile_sha256));
              CREATE TABLE IF NOT EXISTS apps(id TEXT PRIMARY KEY,project_id TEXT,environment TEXT,native_uuid TEXT,
                environment_uuid TEXT,url TEXT,secret TEXT,aliases TEXT DEFAULT '{}',UNIQUE(project_id,environment));
              CREATE TABLE IF NOT EXISTS deployments(id TEXT PRIMARY KEY,project_id TEXT,release_id TEXT,
                environment TEXT,native_uuid TEXT,state TEXT,created_at REAL,request_key TEXT,action TEXT,
                UNIQUE(project_id,request_key));
              CREATE TABLE IF NOT EXISTS deployment_verifications(deployment_id TEXT PRIMARY KEY,
                artifact_sha256 TEXT NOT NULL,source_commit TEXT NOT NULL,verified_at REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS controls(digest TEXT PRIMARY KEY,user_id TEXT,expires REAL,active INTEGER);
              CREATE TABLE IF NOT EXISTS readers(digest TEXT PRIMARY KEY,app_id TEXT,parent TEXT,expires REAL);
              CREATE TABLE IF NOT EXISTS tickets(digest TEXT PRIMARY KEY,app_id TEXT,state TEXT,parent TEXT,
                expires REAL,return_path TEXT);
              CREATE TABLE IF NOT EXISTS management(digest TEXT,project_id TEXT,site_id TEXT,expires REAL,
                PRIMARY KEY(digest,project_id,site_id));
              CREATE TABLE IF NOT EXISTS services(id TEXT,project_id TEXT,site_id TEXT,native_uuid TEXT,
                upstream TEXT,adapter TEXT,secret TEXT,deployment_uuid TEXT,state TEXT,PRIMARY KEY(project_id,id));
              CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,project_id TEXT,subject TEXT,
                action TEXT,resource_id TEXT,created_at REAL);
              CREATE TABLE IF NOT EXISTS domain_claims(hostname TEXT PRIMARY KEY,project_id TEXT NOT NULL,
                environment TEXT NOT NULL,created_at REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS domain_plans(project_id TEXT,environment TEXT,desired_url TEXT NOT NULL,
                current_url TEXT,generation INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(project_id,environment));
              CREATE TABLE IF NOT EXISTS domain_routes(project_id TEXT,environment TEXT,url TEXT,
                PRIMARY KEY(project_id,environment,url));
              CREATE TABLE IF NOT EXISTS domain_deployments(deployment_id TEXT PRIMARY KEY,desired_url TEXT NOT NULL,
                generation INTEGER NOT NULL,urls TEXT NOT NULL);
            ''')
        self._migrate_domains()
        self.database.chmod(0o600)

    @contextmanager
    def connection(self, write=False):
        db = sqlite3.connect(self.database, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            if write:
                db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _managed_hostname(self,value):
        host=domain_hostname(value)
        if '.' not in host:host=host+'.'+self.domain_suffix
        suffix='.'+self.domain_suffix
        if not host.endswith(suffix) or '.' in host[:-len(suffix)]:
            raise PlatformError(422,'Only a single subdomain of the managed platform domain is supported')
        label=host[:-len(suffix)]
        if label in RESERVED_DOMAIN_LABELS or host in self.reserved_hostnames:
            raise PlatformError(409,'Domain hostname is reserved')
        return host

    def _inventory(self):
        # Test adapters can omit discovery; the native production adapter cannot.
        discover=getattr(self.backend,'domain_inventory',None)
        return discover() if discover else {}

    def _claim_domain(self,db,project_id,environment,url,*,inventory=None,native_uuid=None):
        host=urlsplit(url).hostname
        prior=db.execute('SELECT project_id,environment FROM domain_claims WHERE hostname=?',(host,)).fetchone()
        if prior and (prior['project_id']!=project_id or prior['environment']!=environment):
            raise PlatformError(409,'Domain hostname is unavailable')
        if inventory is not None:
            occupied=set(inventory.get(host,()))
            if occupied-({native_uuid} if native_uuid else set()):
                raise PlatformError(409,'Domain hostname is already used by a native application')
        db.execute('INSERT OR IGNORE INTO domain_claims VALUES(?,?,?,?)',
            (host,project_id,environment,time.time()))

    def _default_urls(self,slug):
        return {'production':'https://'+self._managed_hostname(slug),
            'preview':'https://'+self._managed_hostname(slug+'-preview')}

    def _migrate_domains(self):
        """Backfill metadata only; do not change a native route or active app."""
        with self.connection(True) as db:
            projects=db.execute('SELECT id,slug FROM projects ORDER BY created_at').fetchall()
            # Current routes win before proposing readable defaults for old projects.
            for app in db.execute('SELECT project_id,environment,url FROM apps').fetchall():
                self._claim_domain(db,app['project_id'],app['environment'],app['url'])
                db.execute('INSERT OR IGNORE INTO domain_routes VALUES(?,?,?)',
                    (app['project_id'],app['environment'],app['url']))
            for project in projects:
                for environment in ['production','preview']:
                    if db.execute('SELECT 1 FROM domain_plans WHERE project_id=? AND environment=?',
                            (project['id'],environment)).fetchone():continue
                    slug=project['slug'].rstrip('-')
                    name=slug if environment=='production' else slug+'-preview'
                    try:
                        url='https://'+self._managed_hostname(name)
                        self._claim_domain(db,project['id'],environment,url)
                    except PlatformError:
                        # Legacy slugs may end in '-' or collide with another
                        # project's old native/default route. Retain a readable base.
                        base=(slug[:47] or 'project')+'-'+project['id'][:6]
                        name=base if environment=='production' else base+'-preview'
                        url='https://'+self._managed_hostname(name)
                        self._claim_domain(db,project['id'],environment,url)
                    app=db.execute('SELECT url FROM apps WHERE project_id=? AND environment=?',
                        (project['id'],environment)).fetchone()
                    db.execute('INSERT INTO domain_plans VALUES(?,?,?,?,0)',
                        (project['id'],environment,url,app['url'] if app else None))

    def _domain_change_inflight(self,db,project_id,environment):
        return db.execute("SELECT 1 FROM deployments d LEFT JOIN domain_deployments c ON c.deployment_id=d.id "
            "LEFT JOIN domain_plans p ON p.project_id=d.project_id AND p.environment=d.environment "
            "WHERE d.project_id=? AND d.environment=? AND (d.state IN ('dispatching','dispatch_unknown','queued','in_progress') "
            "OR ((c.generation>0 OR p.current_url IS NOT NULL) AND p.current_url IS NOT c.desired_url "
            "AND d.state IN ('verifying','verifying_domain','native_finished_unverified'))) LIMIT 1",
            (project_id,environment)).fetchone() is not None

    def domains(self,actor,project_id):
        self.check(actor,project_id)
        with self.connection() as db:
            result=[]
            for row in db.execute('SELECT * FROM domain_plans WHERE project_id=? ORDER BY environment',(project_id,)):
                routes=[r[0] for r in db.execute('SELECT url FROM domain_routes WHERE project_id=? AND environment=? ORDER BY url',
                    (project_id,row['environment'])) if r[0]!=row['current_url']]
                result.append({'environment':row['environment'],'desired_url':row['desired_url'],
                    'current_url':row['current_url'],'legacy_urls':routes,
                    'pending':row['desired_url']!=row['current_url'],'generation':row['generation']})
        return {'project_id':project_id,'domain_suffix':self.domain_suffix,'environments':result}

    def set_domain(self,actor,project_id,hostname,*,environment='production'):
        self.check(actor,project_id,'manage_domains')
        if environment not in {'production','preview'}:raise PlatformError(422,'Invalid deployment environment')
        url='https://'+self._managed_hostname(hostname)
        with self.lock:
            inventory=self._inventory()
            with self.connection(True) as db:
                plan=db.execute('SELECT * FROM domain_plans WHERE project_id=? AND environment=?',
                    (project_id,environment)).fetchone()
                if plan['desired_url']==url:return self.domains(actor,project_id)
                if self._domain_change_inflight(db,project_id,environment):
                    raise PlatformError(409,'Reconcile the in-flight deployment before changing its domain')
                app=db.execute('SELECT native_uuid FROM apps WHERE project_id=? AND environment=?',
                    (project_id,environment)).fetchone()
                self._claim_domain(db,project_id,environment,url,inventory=inventory,
                    native_uuid=app['native_uuid'] if app else None)
                db.execute('UPDATE domain_plans SET desired_url=?,generation=generation+1 WHERE project_id=? AND environment=?',
                    (url,project_id,environment))
                self.audit(db,actor,project_id,'domain:stage',url)
        return self.domains(actor,project_id)

    def canonical_origin(self,app,host):
        """An app-only lookup, so a new container can preserve the old origin
        until its native artifact is verified and the domain is committed."""
        if not isinstance(host,str):raise PlatformError(403,'Application host mismatch')
        with self.connection() as db:
            claim=db.execute('SELECT 1 FROM domain_claims WHERE hostname=? AND project_id=? AND environment=?',
                (host,app['project_id'],app['environment'])).fetchone()
        if not claim:raise PlatformError(403,'Application host mismatch')
        return {'url':app['url']}

    def live(self, actor):
        try:
            return self.users.current_user(actor)
        except (ManagedError, AttributeError, TypeError):
            raise PlatformError(401, 'Account session is no longer valid') from None

    def admin(self, actor):
        if self.live(actor).role not in {Role.OWNER, Role.ADMIN}:
            raise PlatformError(403, 'Account administration permission required')

    def login(self, username, password):
        actor = self.users.authenticate(username, password)
        if actor is None:
            raise PlatformError(401, 'Invalid account credentials')
        issued = self.users.sessions.issue(actor)
        with self.connection(True) as db:
            db.execute('INSERT INTO controls VALUES(?,?,?,1)',
                       (digest(issued.token.encode()), actor.user_id, issued.session.expires_at))
        return {'token': issued.token, 'principal': asdict(self.live(actor)), 'expires_at': issued.session.expires_at}

    def set_email(self,actor,user_id,email):
        self.admin(actor);self.users.get_user(actor,user_id)
        if not isinstance(email,str) or not re.fullmatch(r'[^\s@<>]{1,150}@[^\s@<>.]+(?:\.[^\s@<>.]+)+',email) or len(email)>320:
            raise PlatformError(422,'Valid trusted account email required')
        with self.connection(True) as db:
            db.execute('INSERT INTO emails VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET email=excluded.email',
                (user_id,email.strip().casefold()))
            db.execute('UPDATE controls SET active=0 WHERE user_id=?',(user_id,))

    def trusted_email(self,actor):
        self.live(actor)
        with self.connection() as db:
            row=db.execute('SELECT email FROM emails WHERE user_id=?',(actor.user_id,)).fetchone()
        return row['email'] if row else ''

    def create_user(self,actor,*,username,password,email=None,**settings):
        self.admin(actor)
        record=self.users.create_user(actor,username,password,**settings)
        if email is not None:self.set_email(actor,record.user_id,email)
        return asdict(record)

    def update_user(self,actor,user_id,*,email=None,**settings):
        self.admin(actor)
        record=self.users.update_user(actor,user_id,**settings)
        if email is not None:self.set_email(actor,user_id,email)
        return asdict(record)

    def control_session(self, token):
        session = self.users.sessions.resolve(token)
        if session is None:
            raise PlatformError(401, 'Sign in to the platform')
        self.live(session.principal)
        with self.connection() as db:
            row = db.execute('SELECT * FROM controls WHERE digest=? AND active=1 AND expires>?',
                             (digest(token.encode()), time.time())).fetchone()
        if row is None:
            raise PlatformError(401, 'Control session required')
        return session

    def logout(self, token):
        self.users.sessions.revoke(token)
        with self.connection(True) as db:
            db.execute('UPDATE controls SET active=0 WHERE digest=?', (digest(token.encode()),))
        return {'authenticated': False}

    def check(self, actor, project_id, operation='read'):
        self.live(actor)
        identifier(project_id)
        with self.connection() as db:
            row = db.execute('SELECT * FROM projects WHERE id=?', (project_id,)).fetchone()
            grant = db.execute('SELECT role FROM grants WHERE project_id=? AND user_id=?',
                               (project_id, actor.user_id)).fetchone()
        if row is None or (row['owner_id'] != actor.user_id and grant is None):
            raise PlatformError(404, 'Project unavailable')
        role = 'owner' if row['owner_id'] == actor.user_id else grant['role']
        if operation in {'deploy', 'publish', 'rollback'} and role not in {'owner', 'deployer'}:
            raise PlatformError(403, 'Deployment permission required')
        if operation in {'grant', 'manage_services','manage_domains','manage_visibility'} and role != 'owner':
            raise PlatformError(403, 'Project owner permission required')
        return {**dict(row), 'role': role}

    def audit(self, db, actor, project_id, action, resource_id):
        db.execute('INSERT INTO audit(project_id,subject,action,resource_id,created_at) VALUES(?,?,?,?,?)',
                   (project_id, actor.user_id, action, resource_id, time.time()))

    def create_project(self, actor, slug, *, name=None, visibility='public', request_key):
        self.live(actor)
        if not re.fullmatch(r'[a-z][a-z0-9-]{1,47}[a-z0-9]', slug or '') or visibility not in {'public','private'}:
            raise PlatformError(422, 'Invalid project slug or visibility')
        identifier(request_key)
        name = name or slug
        if not isinstance(name,str) or not 1 <= len(name) <= 160:
            raise PlatformError(422, 'Invalid project name')
        with self.lock:
            inventory=self._inventory()
            with self.connection(True) as db:
                row = db.execute('SELECT * FROM projects WHERE owner_id=? AND request_key=?',
                                 (actor.user_id,request_key)).fetchone()
                if row:
                    if row['slug'] != slug or row['visibility'] != visibility:
                        raise PlatformError(409, 'Idempotency key already used for different settings')
                    project_id = row['id']
                else:
                    project_id = uuid.uuid4().hex
                    defaults=self._default_urls(slug)
                    for environment,url in defaults.items():
                        self._claim_domain(db,project_id,environment,url,inventory=inventory)
                    try:
                        db.execute('INSERT INTO projects VALUES(?,?,?,?,?,?,?,?,?)',
                            (project_id,slug,name,actor.user_id,visibility,time.time(),request_key,None,'registering'))
                    except sqlite3.IntegrityError:
                        raise PlatformError(409, 'Project slug is unavailable') from None
                    for environment,url in defaults.items():
                        db.execute('INSERT INTO domain_plans VALUES(?,?,?,NULL,0)',(project_id,environment,url))
                native_uuid = row['native_uuid'] if row else None
            if not native_uuid:
                native = self.backend.create_project(slug, 'chatcoolify-platform-' + project_id)
                with self.connection(True) as db:
                    db.execute('UPDATE projects SET native_uuid=?,state=? WHERE id=?', (native['uuid'],'ready',project_id))
                    self.audit(db,actor,project_id,'register',native['uuid'])
        return self.project(actor,project_id)

    def project(self, actor, project_id):
        item = self.check(actor,project_id)
        with self.connection() as db:
            apps = db.execute('SELECT id,environment,native_uuid,environment_uuid,url FROM apps WHERE project_id=?', (project_id,)).fetchall()
        return {k:v for k,v in item.items() if k != 'request_key'} | {
            'applications':[dict(a) for a in apps],'domains':self.domains(actor,project_id)}

    def projects(self, actor):
        self.live(actor)
        with self.connection() as db:
            ids = [r[0] for r in db.execute('SELECT DISTINCT p.id FROM projects p LEFT JOIN grants g ON p.id=g.project_id '
                'WHERE p.owner_id=? OR g.user_id=? ORDER BY p.created_at LIMIT 1000', (actor.user_id,actor.user_id))]
        return [self.project(actor,p) for p in ids]

    def set_visibility(self,actor,project_id,visibility):
        """Publishing access is independent of management-account permissions."""
        self.check(actor,project_id,'manage_visibility')
        if visibility not in {'public','private'}:
            raise PlatformError(422,'Invalid project visibility')
        with self.lock:
            # Tightening access takes effect before any backend request. Opening
            # access happens only after all registered comment policies agree.
            if visibility=='private':
                with self.connection(True) as db:
                    db.execute("UPDATE projects SET visibility='private' WHERE id=?",(project_id,))
            self._sync_comment_visibility(actor,project_id,visibility)
            with self.connection(True) as db:
                db.execute('UPDATE projects SET visibility=? WHERE id=?',(visibility,project_id))
                self.audit(db,actor,project_id,'visibility:'+visibility,project_id)
        return self.project(actor,project_id)

    def _sync_comment_visibility(self,actor,project_id,visibility,bindings=None):
        """Apply the owner's explicit visitor policy through a trusted adapter.

        This is a site visibility action, not a fabricated password reauth grant
        for comment settings, exports or moderation.
        """
        self.check(actor,project_id,'manage_visibility')
        if bindings is None:
            with self.connection() as db:
                bindings=[dict(r) for r in db.execute('SELECT * FROM services WHERE project_id=?',(project_id,))]
        if not bindings:return
        module=importlib.import_module('chatcomment.access')
        for binding in bindings:
            if binding['adapter']!='chatcomment':
                raise PlatformError(409,'This service has no registered visibility adapter')
            path='/api/sites/'+identifier(binding['site_id'])+'/visibility'
            raw=json.dumps({'private':visibility=='private'}).encode()
            context=module.AccessContext(subject=actor.user_id,session='visibility-'+uuid.uuid4().hex,
                sites={binding['site_id']:module.SiteAccess(read=True,manage=True,owner=True)},csrf_verified=True)
            headers=module.sign_context(context,key=binding['secret'],method='POST',path=path,body=raw)
            headers['Content-Type']='application/json'
            class NoRedirect(HTTPRedirectHandler):
                def redirect_request(self,*args):return None
            try:
                request=Request(binding['upstream']+path,data=raw,method='POST',headers=headers)
                with build_opener(NoRedirect()).open(request,timeout=20) as response:
                    result=json.loads(response.read(65536))
                    if result.get('private') is not (visibility=='private'):
                        raise ValueError('Visibility was not applied')
            except Exception:
                raise PlatformError(502,'Comment service access policy was not synchronized; retry the visibility setting') from None

    def apply_domain(self,actor,project_id,*,environment='production',request_key):
        """Explicitly repackage the currently published bytes and apply a domain.

        A new immutable release can carry the current runtime; this never changes
        the source or contents of any historical release or publishes a draft.
        """
        self.check(actor,project_id,'manage_domains');identifier(request_key)
        if environment not in {'preview','production'}:
            raise PlatformError(422,'Invalid deployment environment')
        with self.lock:
            with self.connection() as db:
                prior=db.execute('SELECT id,environment,action FROM deployments WHERE project_id=? AND request_key=?',
                    (project_id,request_key)).fetchone()
                if prior:
                    if prior['environment']!=environment or prior['action']!='domain_apply':
                        raise PlatformError(409,'Idempotency key conflicts with another operation')
                    prior_id=prior['id']
                else:prior_id=None
                current=db.execute('SELECT r.*,d.id published_deployment_id FROM deployments d '
                    'JOIN releases r ON r.id=d.release_id JOIN deployment_verifications v ON v.deployment_id=d.id '
                    "WHERE d.project_id=? AND d.environment=? AND d.state='finished' "
                    'AND v.artifact_sha256=r.artifact_sha256 AND v.source_commit=r.source_commit '
                    'ORDER BY d.rowid DESC LIMIT 1',(project_id,environment)).fetchone()
            if prior_id:
                return self.deployment(actor,project_id,prior_id)
            if not current:
                raise PlatformError(409,'Publish this environment before applying its domain')
            active=self.deployment(actor,project_id,current['published_deployment_id'])
            if not active['runtime_active'] or not active['runtime_verified']:
                raise PlatformError(409,'Reconcile the currently running deployment before applying its domain')
            archive=self.root/'artifacts'/(current['artifact_sha256']+'.zip')
            if not archive.is_file():raise PlatformError(409,'Published artifact is unavailable')
            data=archive.read_bytes()
            if digest(data)!=current['artifact_sha256']:raise PlatformError(409,'Published artifact digest mismatch')
            release=self.upload(actor,project_id,data,original_commit=current['original_commit'])
            return self.deploy(actor,project_id,release['id'],environment=environment,request_key=request_key,domain_apply=True)

    def grant(self, actor, project_id, user_id, role):
        self.check(actor,project_id,'grant'); identifier(user_id)
        if role not in {'viewer','deployer','none'}:
            raise PlatformError(422, 'Invalid collaborator role')
        with self.connection(True) as db:
            db.execute('DELETE FROM grants WHERE project_id=? AND user_id=?',(project_id,user_id))
            if role != 'none':
                db.execute('INSERT INTO grants VALUES(?,?,?)',(project_id,user_id,role))
            self.audit(db,actor,project_id,'grant:'+role,user_id)
        return {'project_id':project_id,'user_id':user_id,'role':role}

    def upload(self, actor, project_id, data, *, original_commit=None):
        self.check(actor,project_id,'deploy'); validate_archive(data)
        if original_commit is not None and not re.fullmatch(r'[0-9a-f]{40,64}',original_commit):
            raise PlatformError(422,'Invalid original source commit')
        sha = digest(data)
        source_files,docker_digest=frontend_files(data)
        with self.lock:
            with self.connection() as db:
                row = db.execute('SELECT * FROM releases WHERE project_id=? AND artifact_sha256=? AND dockerfile_sha256=?',(project_id,sha,docker_digest)).fetchone()
                if row:
                    return dict(row)
                if db.execute('SELECT count(*) FROM releases WHERE project_id=?',(project_id,)).fetchone()[0]>=200:
                    raise PlatformError(409,'Project release capacity reached; operator retention review required')
            source_commit=self.sources.commit_files(project_id,source_files,'Frontend artifact '+sha)
            directory = self.root / 'artifacts';directory.mkdir(exist_ok=True,mode=0o700)
            path = directory / (sha+'.zip');path.write_bytes(data);path.chmod(0o600)
            release_id = uuid.uuid4().hex
            with self.connection(True) as db:
                self.check(actor,project_id,'deploy')
                db.execute('INSERT INTO releases VALUES(?,?,?,?,?,?,?,?)',
                    (release_id,project_id,sha,docker_digest,source_commit,original_commit,actor.user_id,time.time()))
                self.audit(db,actor,project_id,'upload',release_id)
            return next(r for r in self.releases(actor,project_id) if r['id']==release_id)

    def releases(self, actor, project_id):
        self.check(actor,project_id)
        with self.connection() as db:
            return [dict(r) for r in db.execute('SELECT * FROM releases WHERE project_id=? ORDER BY created_at DESC LIMIT 200',(project_id,))]

    def deploy(self, actor, project_id, release_id, *, environment, request_key, rollback=False, domain_apply=False):
        project = self.check(actor,project_id,'rollback' if rollback else 'deploy')
        if domain_apply:self.check(actor,project_id,'manage_domains')
        action='domain_apply' if domain_apply else ('rollback' if rollback else 'deploy')
        if domain_apply and rollback:raise PlatformError(422,'Conflicting deployment actions')
        identifier(release_id);identifier(request_key)
        if environment not in {'preview','production'}:
            raise PlatformError(422,'Invalid deployment environment')
        with self.lock:
            inventory=self._inventory()
            with self.connection(True) as db:
                release = db.execute('SELECT * FROM releases WHERE id=? AND project_id=?',(release_id,project_id)).fetchone()
                if not release:
                    raise PlatformError(404,'Release unavailable')
                prior = db.execute('SELECT * FROM deployments WHERE project_id=? AND request_key=?',(project_id,request_key)).fetchone()
                if prior:
                    if prior['release_id']!=release_id or prior['environment']!=environment or prior['action']!=action:
                        raise PlatformError(409,'Idempotency key conflicts with prior deployment')
                    prior_id=prior['id']
                else:prior_id=None
                if not prior_id:
                    if self._domain_change_inflight(db,project_id,environment):
                        raise PlatformError(409,'Reconcile the in-flight deployment before submitting another')
                    if rollback and not db.execute("SELECT 1 FROM deployments d JOIN deployment_verifications v ON v.deployment_id=d.id "
                            "JOIN releases r ON r.id=d.release_id WHERE d.project_id=? AND d.release_id=? "
                            "AND d.environment='production' AND d.state='finished' "
                            "AND v.artifact_sha256=r.artifact_sha256 AND v.source_commit=r.source_commit",
                            (project_id,release_id)).fetchone():
                        raise PlatformError(409,'Rollback requires a previously successful production release')
                    app = db.execute('SELECT * FROM apps WHERE project_id=? AND environment=?',(project_id,environment)).fetchone()
                    plan=db.execute('SELECT * FROM domain_plans WHERE project_id=? AND environment=?',
                        (project_id,environment)).fetchone()
                    urls=[plan['desired_url']]
                    if app and app['url'] not in urls:urls.append(app['url'])
                    for row in db.execute('SELECT url FROM domain_routes WHERE project_id=? AND environment=? ORDER BY url',
                            (project_id,environment)):
                        if row['url'] not in urls:urls.append(row['url'])
                    if len(urls)>30:raise PlatformError(409,'Domain alias capacity reached; operator review required')
                    self._claim_domain(db,project_id,environment,plan['desired_url'],inventory=inventory,
                        native_uuid=app['native_uuid'] if app else None)
                    # Immutable old releases do not acquire new runtime behavior by
                    # upgrading the control plane. A re-upload creates a new source
                    # with the same website bytes and the current guarded runtime.
                    if plan['desired_url']!=plan['current_url'] or len(urls)>1:
                        archive=self.root/'artifacts'/(release['artifact_sha256']+'.zip')
                        if not archive.is_file() or frontend_files(archive.read_bytes())[1]!=release['dockerfile_sha256']:
                            raise PlatformError(409,'Upload the site again with the current runtime before changing domains or using legacy aliases')
                    deployment_id = uuid.uuid4().hex
                    db.execute('INSERT INTO deployments VALUES(?,?,?,?,?,?,?,?,?)',
                        (deployment_id,project_id,release_id,environment,None,'dispatching',time.time(),request_key,
                         action))
                    db.execute('INSERT INTO domain_deployments VALUES(?,?,?,?)',
                        (deployment_id,plan['desired_url'],plan['generation'],json.dumps(urls)))
            if prior_id:return self.deployment(actor,project_id,prior_id)
            try:
                if not app:
                    native_project = self.backend.client.get_project(project['native_uuid'])
                    envs = self.backend.environments(native_project)
                    env = envs[environment]
                    app_id = uuid.uuid4().hex
                    secret = secrets.token_urlsafe(48)
                    native = self.backend.create_source_application(project['native_uuid'],env['uuid'],environment,
                        project['slug']+'-'+environment,project_id,release['source_commit'],domains=plan['desired_url'])
                    with self.connection(True) as db:
                        db.execute('INSERT INTO apps(id,project_id,environment,native_uuid,environment_uuid,url,secret) VALUES(?,?,?,?,?,?,?)',
                            (app_id,project_id,environment,native['uuid'],env['uuid'],plan['desired_url'],secret))
                    with self.connection() as db:
                        app = db.execute('SELECT * FROM apps WHERE id=?',(app_id,)).fetchone()
                # The old URL remains routed throughout the native rolling build.
                # A running old container keeps its old configuration if build fails.
                self.backend.update_application(app['native_uuid'],domains=self.backend.native_domains(','.join(urls)),
                    custom_network_aliases='platform-front-'+app['id'],connect_to_docker_network=True)
                self.backend.env(app['native_uuid'],{'PLATFORM_APPLICATION_ID':app['id'],'PLATFORM_APPLICATION_KEY':app['secret'],
                    'PLATFORM_CONTROL_URL':self.control_url,'PLATFORM_INTERNAL_URL':self.internal_url,
                    'PLATFORM_PUBLIC_URLS':','.join(urls),'PLATFORM_DOMAIN_GENERATION':str(plan['generation']),
                    'PLATFORM_ROUTE_ALIASES':app['aliases']})
                self.check(actor,project_id,'deploy')
                self.sources.retain(project_id,release['source_commit'])
                self.backend.update_application(app['native_uuid'],git_commit_sha=release['source_commit'])
            except Exception:
                with self.connection(True) as db:
                    db.execute("UPDATE deployments SET state='configuration_failed' WHERE id=?",(deployment_id,))
                raise
            try:
                native_deployment = self.backend.deploy(app['native_uuid'])
            except Exception:
                # Ambiguous dispatch is retained for reconciliation, never blindly retried.
                with self.connection(True) as db:
                    db.execute("UPDATE deployments SET state='dispatch_unknown' WHERE id=?",(deployment_id,))
                raise
            with self.connection(True) as db:
                db.execute("UPDATE deployments SET native_uuid=?,state='queued' WHERE id=?",(native_deployment,deployment_id))
                self.audit(db,actor,project_id,action,native_deployment)
        return self.deployment(actor,project_id,deployment_id)

    def _activate_domain(self,db,item):
        capture=db.execute('SELECT * FROM domain_deployments WHERE deployment_id=?',(item['id'],)).fetchone()
        if not capture:return
        plan=db.execute('SELECT * FROM domain_plans WHERE project_id=? AND environment=?',
            (item['project_id'],item['environment'])).fetchone()
        if plan['current_url']==capture['desired_url']:return
        if plan['generation']!=capture['generation'] or plan['desired_url']!=capture['desired_url']:return
        probe=getattr(self.backend,'runtime_domain_state',None)
        actual=probe(item['url'],item['app_id'],item['app_secret']) if probe else None
        expected_runtime=digest(Path(__file__).with_name('platform_runtime.py').read_bytes())
        if (not actual or actual.get('artifact_sha256')!=item['artifact_sha256']
                or actual.get('runtime_sha256')!=expected_runtime
                or str(actual.get('domain_generation'))!=str(capture['generation'])
                or actual.get('public_urls')!=json.loads(capture['urls'])):return
        db.execute('UPDATE apps SET url=? WHERE id=?',(capture['desired_url'],item['app_id']))
        db.execute('UPDATE domain_plans SET current_url=? WHERE project_id=? AND environment=?',
            (capture['desired_url'],item['project_id'],item['environment']))
        for url in json.loads(capture['urls']):
            db.execute('INSERT OR IGNORE INTO domain_routes VALUES(?,?,?)',(item['project_id'],item['environment'],url))
        item['url']=capture['desired_url']

    def deployment(self, actor, project_id, deployment_id):
        with self.lock:
            return self._deployment(actor,project_id,deployment_id)

    def _deployment(self, actor, project_id, deployment_id):
        project = self.check(actor,project_id);identifier(deployment_id)
        with self.connection() as db:
            row = db.execute('SELECT d.*,d.rowid deployment_sequence,a.id app_id,a.secret app_secret,a.native_uuid app_uuid,a.environment_uuid,a.url,r.artifact_sha256,r.source_commit,r.dockerfile_sha256 '
                'FROM deployments d JOIN apps a ON d.project_id=a.project_id AND d.environment=a.environment JOIN releases r ON d.release_id=r.id '
                'WHERE d.project_id=? AND d.id=?',(project_id,deployment_id)).fetchone()
        if not row:
            raise PlatformError(404,'Deployment unavailable')
        item = dict(row)
        with self.connection() as db:
            proof=db.execute('SELECT verified_at FROM deployment_verifications WHERE deployment_id=? AND artifact_sha256=? AND source_commit=?',
                (deployment_id,item['artifact_sha256'],item['source_commit'])).fetchone()
        item['verified_at']=proof['verified_at'] if proof else None
        item['runtime_verified']=proof is not None
        item['runtime_active']=False

        def superseded():
            # Reconcile native jobs too: a newer finished job may never have been
            # polled through this API. Its running bytes cannot verify this job.
            with self.connection() as db:
                newer=db.execute('SELECT native_uuid,state FROM deployments WHERE project_id=? AND environment=? AND rowid>?',
                    (project_id,row['environment'],row['deployment_sequence'])).fetchall()
            for entry in newer:
                if entry['native_uuid']:
                    status=self.backend.deployment(entry['native_uuid'])
                    if (status.get('status') or status.get('deployment',{}).get('status'))=='finished':
                        return True
            return False
        if not item['native_uuid'] and item['state']=='dispatch_unknown':
            from datetime import datetime
            matches=[]
            for entry in self.backend.client.list_deployments(row['app_uuid'],take=30):
                try:created=datetime.fromisoformat(entry.get('created_at','').replace('Z','+00:00')).timestamp()
                except ValueError:continue
                if entry.get('commit')==row['source_commit'] and created>=row['created_at']-5:
                    matches.append(entry)
            if len(matches)==1:
                native_id=matches[0].get('deployment_uuid') or matches[0].get('uuid')
                if native_id:
                    item['native_uuid']=native_id
                    with self.connection(True) as db:
                        db.execute('UPDATE deployments SET native_uuid=?,state=? WHERE id=?',(native_id,'queued',deployment_id))
        if item['native_uuid']:
            native = self.backend.deployment(item['native_uuid'])
            state = native.get('status') or native.get('deployment',{}).get('status') or item['state']
            if state=='finished':
                if native.get('commit') and native['commit']!=item['source_commit']:
                    state='provenance_mismatch'
                elif superseded():
                    state='finished' if proof else 'superseded_unverified'
                elif hasattr(self.backend,'runtime_artifact'):
                    actual=self.backend.runtime_artifact(item['url'],item['app_id'],item['app_secret'])
                    item['runtime_artifact_sha256']=actual
                    if superseded():
                        state='finished' if proof else 'superseded_unverified'
                    else:
                        item['runtime_active']=actual==item['artifact_sha256']
                        if item['runtime_active']:
                            with self.connection(True) as db:
                                db.execute('INSERT OR IGNORE INTO deployment_verifications VALUES(?,?,?,?)',
                                    (deployment_id,item['artifact_sha256'],item['source_commit'],time.time()))
                                item['verified_at']=db.execute('SELECT verified_at FROM deployment_verifications WHERE deployment_id=?',
                                    (deployment_id,)).fetchone()[0]
                                self._activate_domain(db,item)
                            item['runtime_verified']=True
                        elif not proof:state='verifying'
                elif not proof:
                    state='native_finished_unverified'
            item['state'] = state
            with self.connection(True) as db:
                db.execute('UPDATE deployments SET state=? WHERE id=?',(state,deployment_id))
        item.pop('request_key',None)
        item.pop('deployment_sequence',None)
        item.pop('app_secret',None);item.pop('app_id',None)
        item['backend_ref'] = {'provider':'coolify','team_id':self.backend.team_id,'project_uuid':project['native_uuid'],
            'environment_uuid':item.pop('environment_uuid'),'application_uuid':item.pop('app_uuid'),'deployment_uuid':item['native_uuid']}
        item['domain']=next(x for x in self.domains(actor,project_id)['environments'] if x['environment']==item['environment'])
        with self.connection() as db:
            captured=db.execute('SELECT desired_url,generation FROM domain_deployments WHERE deployment_id=?',(deployment_id,)).fetchone()
        pending_attempt=(captured and captured['desired_url']==item['domain']['desired_url']
            and captured['generation']==item['domain']['generation']
            and captured['desired_url']!=item['domain']['current_url'])
        if (item['state']=='finished' and item['runtime_active'] and pending_attempt
                and hasattr(self.backend,'runtime_domain_state')):
            item['state']='verifying_domain'
            with self.connection(True) as db:db.execute('UPDATE deployments SET state=? WHERE id=?',(item['state'],deployment_id))
        return item

    def deployments(self, actor, project_id):
        self.check(actor,project_id)
        with self.connection() as db:
            ids = [r[0] for r in db.execute('SELECT id FROM deployments WHERE project_id=? ORDER BY created_at DESC LIMIT 50',(project_id,))]
        return [self.deployment(actor,project_id,i) for i in ids]

    def logs(self, actor, project_id, deployment_id):
        item = self.deployment(actor,project_id,deployment_id)
        native = self.backend.deployment(item['native_uuid'])
        logs = native.get('logs',[])
        if isinstance(logs,str):
            try:logs=json.loads(logs)
            except ValueError:logs=logs.splitlines()
        clean=[]
        for record in logs[-300:]:
            text = record.get('output','') if isinstance(record,dict) else str(record)
            # Build input contents and runtime environment must never leak through logs.
            if re.search(r'(?i)bearer|password|token|secret|PLATFORM_APPLICATION_KEY|PRIVATE KEY',text) or len(text)>1000:
                text='[sensitive or oversized build line omitted]'
            clean.append(text)
        return {'deployment_id':deployment_id,'backend_ref':item['backend_ref'],'lines':clean}

    def application_auth(self, application_id, secret, host=None):
        identifier(application_id)
        with self.connection() as db:
            row=db.execute('SELECT * FROM apps WHERE id=?',(application_id,)).fetchone()
        if not row or not isinstance(secret,str) or not hmac.compare_digest(row['secret'],secret):
            raise PlatformError(401,'Application credential required')
        if host is not None and host != urlsplit(row['url']).netloc:
            raise PlatformError(403,'Application host mismatch')
        return dict(row)

    def issue_ticket(self, control_token, application_id, state, return_path):
        session=self.control_session(control_token)
        if not isinstance(state,str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,100}',state):
            raise PlatformError(422,'Invalid login transaction')
        with self.connection() as db:
            app=db.execute('SELECT * FROM apps WHERE id=?',(identifier(application_id),)).fetchone()
        if not app:
            raise PlatformError(404,'Application unavailable')
        self.check(session.principal,app['project_id'])
        code=secrets.token_urlsafe(40)
        with self.connection(True) as db:
            db.execute('DELETE FROM tickets WHERE expires<?',(time.time(),))
            db.execute('INSERT INTO tickets VALUES(?,?,?,?,?,?)',(digest(code.encode()),application_id,
                digest(state.encode()),digest(control_token.encode()),time.time()+60,safe_return(return_path)))
        return {'code':code,'state':state,'callback':app['url'].rstrip('/')+'/__platform/callback'}

    def exchange(self, app, code, state):
        if not isinstance(code,str) or not isinstance(state,str):
            raise PlatformError(401,'Invalid login transaction')
        with self.connection(True) as db:
            ticket=db.execute('SELECT * FROM tickets WHERE digest=?',(digest(code.encode()),)).fetchone()
            if (not ticket or ticket['expires']<=time.time() or ticket['app_id']!=app['id']
                    or not hmac.compare_digest(ticket['state'],digest(state.encode()))):
                raise PlatformError(401,'Invalid or expired login transaction')
            parent=db.execute('SELECT * FROM controls WHERE digest=? AND active=1 AND expires>?',
                              (ticket['parent'],time.time())).fetchone()
            if not parent:
                raise PlatformError(401,'Central session no longer valid')
            # Resolve a revision-bound live principal from a currently valid parent session.
            # The stored account principal is never reconstructed from client-supplied identity.
            session=self._parent_principal(parent)
            self.check(session,app['project_id'])
            issued=self.users.sessions.issue(session)
            db.execute('DELETE FROM tickets WHERE digest=?',(ticket['digest'],))
            db.execute('INSERT INTO readers VALUES(?,?,?,?)',(digest(issued.token.encode()),app['id'],ticket['parent'],
                min(parent['expires'],issued.session.expires_at)))
        return {'token':issued.token,'return_path':ticket['return_path']}

    def _parent_principal(self, parent):
        # ChatLogin's own managed session store validates revision and enabled status.
        # Locate by the same opaque digest without ever storing a duplicate password/token.
        session=self.users.sessions.store.get(self.users.sessions.instance,parent['digest'])
        if session is None or session.expires_at<=time.time() or session.principal.user_id!=parent['user_id']:
            raise PlatformError(401,'Central session revoked')
        self.live(session.principal)
        return session.principal

    def reader(self, app, token):
        if not isinstance(token,str) or not token:
            raise PlatformError(401,'Sign in to read this project')
        session=self.users.sessions.resolve(token)
        if session is None:
            raise PlatformError(401,'Reader session expired')
        self.live(session.principal)
        with self.connection() as db:
            row=db.execute('SELECT r.* FROM readers r JOIN controls c ON r.parent=c.digest '
                'WHERE r.digest=? AND r.app_id=? AND r.expires>? AND c.active=1 AND c.expires>?',
                (digest(token.encode()),app['id'],time.time(),time.time())).fetchone()
        if row is None:
            raise PlatformError(401,'Reader session unavailable')
        with self.connection() as db:
            parent=db.execute('SELECT * FROM controls WHERE digest=?',(row['parent'],)).fetchone()
        if parent is None or self._parent_principal(parent).user_id!=session.principal.user_id:
            raise PlatformError(401,'Central session revoked')
        return session,self.check(session.principal,app['project_id'])

    def _guest_cookie(self,app,value=None,*,issue=False):
        """A short-lived app-bound visitor credential, never a platform account."""
        now=int(time.time())
        if not value and issue:
            raw='1.'+str(now+1800)+'.'+secrets.token_urlsafe(32)
            signature=hmac.new(app['secret'].encode(),('guest|'+app['id']+'|'+raw).encode(),hashlib.sha256).hexdigest()
            value=raw+'.'+signature
        if not isinstance(value,str) or not value.isascii() or not 1<=len(value)<=256:
            raise PlatformError(403,'Refresh the page before submitting a comment')
        parts=value.split('.')
        if (len(parts)!=4 or parts[0]!='1' or not re.fullmatch(r'[0-9]{1,12}',parts[1])
                or not re.fullmatch(r'[A-Za-z0-9_-]{43}',parts[2])
                or not re.fullmatch(r'[0-9a-f]{64}',parts[3])):
            raise PlatformError(403,'Refresh the page before submitting a comment')
        expires=int(parts[1])
        expected=hmac.new(app['secret'].encode(),('guest|'+app['id']+'|'+'.'.join(parts[:3])).encode(),hashlib.sha256).hexdigest()
        if not now<expires<=now+1805 or not hmac.compare_digest(expected,parts[3]):
            raise PlatformError(403,'Refresh the page before submitting a comment')
        return value

    def _guest_csrf(self,app,cookie):
        return hmac.new(app['secret'].encode(),('guest-csrf|'+app['id']+'|'+cookie).encode(),hashlib.sha256).hexdigest()

    def _guest_access(self,app,payload):
        method=payload.get('method','GET')
        safe=method in {'GET','HEAD'}
        supplied=payload.get('guest_token','')
        issued=False
        try:cookie=self._guest_cookie(app,supplied)
        except PlatformError:
            if not safe:raise
            cookie=self._guest_cookie(app,issue=True);issued=True
        csrf=self._guest_csrf(app,cookie)
        if not safe and (payload.get('origin')!=app['url'].rstrip('/')
                or not isinstance(payload.get('csrf'),str)
                or not payload['csrf'].isascii()
                or not hmac.compare_digest(payload['csrf'],csrf)):
            raise PlatformError(403,'Same-origin guest CSRF validation required')
        with self.connection() as db:
            sites=[row[0] for row in db.execute('SELECT site_id FROM services WHERE project_id=?',(app['project_id'],))]
        access={'authenticated':False,'read':True,'csrf_token':csrf,
            'subject':'guest:'+digest(cookie.encode())[:32],
            'site_permissions':{site:{'read':True,'comment':True,'manage':False,'owner':False,
                'management_until':0} for site in sites}}
        if issued:
            # Internal transport only. The runtime removes these fields before
            # producing browser JSON and sets a Secure HttpOnly host cookie.
            access['_guest_cookie']=cookie;access['_guest_max_age']=1800
        return access

    def _guest_submission_limit(self,app,cookie):
        """Bound in-process visitor buckets; backend applies its own limits too."""
        now=time.monotonic();key=app['id']+':'+digest(cookie.encode())
        with self.lock:
            attempts=getattr(self,'_guest_attempts',None)
            if attempts is None:attempts={};self._guest_attempts=attempts
            for previous in [k for k,v in attempts.items() if v[0]<=now]:
                del attempts[previous]
            if key not in attempts and len(attempts)>=10000:
                raise PlatformError(429,'Guest comments are busy; try again shortly')
            until,count=attempts.get(key,(now+60,0))
            if count>=10:raise PlatformError(429,'Please wait before submitting another comment')
            attempts[key]=(until,count+1)

    def authorize(self, app, payload):
        token=payload.get('reader_token','')
        with self.connection() as db:
            project=db.execute('SELECT * FROM projects WHERE id=?',(app['project_id'],)).fetchone()
        if not project:raise PlatformError(404,'Project unavailable')
        if project['visibility']=='public':
            try:session,project=self.reader(app,token)
            except PlatformError as exc:
                # An expired, foreign or revoked account cookie must not turn
                # a public website into a login wall or grant management.
                if exc.status not in {401,403,404}:raise
                return self._guest_access(app,payload)
        else:
            session,project=self.reader(app,token)
        method=payload.get('method','GET')
        if method not in {'GET','HEAD'}:
            if (payload.get('origin')!=app['url'].rstrip('/')
                    or not hmac.compare_digest(str(payload.get('csrf','')),session.csrf_token)):
                raise PlatformError(403,'Same-origin CSRF validation required')
        with self.connection() as db:
            services=db.execute('SELECT site_id FROM services WHERE project_id=?',(app['project_id'],)).fetchall()
            grants={r['site_id']:0 for r in services}
            for site in grants:
                grant=db.execute('SELECT expires FROM management WHERE digest=? AND project_id=? AND site_id=?',
                    (digest(token.encode()),app['project_id'],site)).fetchone()
                grants[site]=grant['expires'] if grant and grant['expires']>time.time() else 0
        return {'authenticated':True,'subject':session.principal.user_id,'read':True,'csrf_token':session.csrf_token,
            'site_permissions':{site:{'read':True,'comment':True,'manage':project['role']=='owner',
                'owner':project['role']=='owner','management_until':until} for site,until in grants.items()}}

    def reauth(self, app, payload):
        self.authorize(app,payload)
        session,project=self.reader(app,payload['reader_token'])
        if project['role']!='owner':
            raise PlatformError(403,'Project owner reauthentication required')
        value=payload.get('payload',{})
        expected_email=self.trusted_email(session.principal)
        entered_email=value.get('email','')
        if not expected_email or not isinstance(entered_email,str) or entered_email.strip().casefold()!=expected_email:
            raise PlatformError(401,'Account credentials did not match current owner')
        actor=self.users.authenticate(self.live(session.principal).username,value.get('password',''))
        if actor is None or actor.user_id!=session.principal.user_id:
            raise PlatformError(401,'Account credentials did not match current owner')
        site_id=value.get('site') or value.get('site_id','');identifier(site_id)
        with self.connection(True) as db:
            if not db.execute('SELECT 1 FROM services WHERE project_id=? AND site_id=?',(app['project_id'],site_id)).fetchone():
                raise PlatformError(404,'Service site unavailable')
            until=time.time()+900
            db.execute('INSERT INTO management VALUES(?,?,?,?) ON CONFLICT(digest,project_id,site_id) '
                'DO UPDATE SET expires=excluded.expires',(digest(payload['reader_token'].encode()),app['project_id'],site_id,until))
        return {'authenticated':True,'management_until':until}

    def logout_reader(self,app,payload):
        self.authorize(app,payload)
        self.reader(app,payload.get('reader_token',''))
        child=digest(payload['reader_token'].encode())
        with self.connection(True) as db:
            row=db.execute('SELECT parent FROM readers WHERE digest=? AND app_id=?',(child,app['id'])).fetchone()
            if row:
                db.execute('UPDATE controls SET active=0 WHERE digest=?',(row['parent'],))
        self.users.sessions.revoke(payload['reader_token'])
        if row:self.users.sessions.store.delete(self.users.sessions.instance,row['parent'])
        return {'authenticated':False}

    def service_candidates(self, actor, project_id):
        project=self.check(actor,project_id,'manage_services')
        native=self.backend.client.get_project(project['native_uuid'])
        candidates=[]
        for env in native['environments']:
            detail=self.backend.client._request('GET',f"/api/v1/projects/{project['native_uuid']}/{env['uuid']}")
            for item in detail.get('applications',[]):
                application=self.backend.application(item['uuid'])
                port=application.get('ports_exposes','')
                if not str(port).isdigit() or not 1<=int(port)<=65535:continue
                candidates.append({'registration_id':digest(item['uuid'].encode())[:32],
                    'name':item.get('name',''),'native_uuid':item['uuid'],'environment':env['name'],'port':int(port)})
        return candidates

    def register_service(self, actor, project_id, *, binding_id, site_id, registration_id, adapter):
        self.check(actor,project_id,'manage_services')
        identifier(binding_id);identifier(site_id);identifier(registration_id)
        if adapter!='chatcomment':
            raise PlatformError(422,'Transport adapter is not registered on this server')
        candidate=next((x for x in self.service_candidates(actor,project_id) if x['registration_id']==registration_id),None)
        if not candidate:
            raise PlatformError(404,'Native service is not registered under this project')
        with self.connection() as db:
            if db.execute('SELECT 1 FROM apps WHERE native_uuid=?',(candidate['native_uuid'],)).fetchone():
                raise PlatformError(422,'Frontend app cannot be used as its own service upstream')
            prior=db.execute('SELECT * FROM services WHERE project_id=? AND id=?',(project_id,binding_id)).fetchone()
        secret=prior['secret'] if prior else secrets.token_urlsafe(48)
        network_alias='platform-service-'+identifier(candidate['native_uuid'])
        self.backend.update_application(candidate['native_uuid'],custom_network_aliases=network_alias,connect_to_docker_network=True)
        # Trusted backend only receives its own signing key, never native Coolify token.
        self.backend.env(candidate['native_uuid'],{'CHATCOMMENT_GATEWAY_KEY':secret,'CHATCOMMENT_GATEWAY_REQUIRED':'1'})
        with self.connection(True) as db:
            db.execute('INSERT INTO services(id,project_id,site_id,native_uuid,upstream,adapter,secret) VALUES(?,?,?,?,?,?,?) ON CONFLICT(project_id,id) DO UPDATE SET '
                'site_id=excluded.site_id,native_uuid=excluded.native_uuid,upstream=excluded.upstream,adapter=excluded.adapter',
                (binding_id,project_id,site_id,candidate['native_uuid'],
                 'http://'+network_alias+':'+str(candidate['port']),adapter,secret))
            self.audit(db,actor,project_id,'bind-service',binding_id)
        native_deployment_uuid=self.backend.deploy(candidate['native_uuid'])
        with self.connection(True) as db:
            db.execute('UPDATE services SET deployment_uuid=?,state=? WHERE project_id=? AND id=?',
                (native_deployment_uuid,'queued',project_id,binding_id))
        return {'id':binding_id,'project_id':project_id,'site_id':site_id,'native_resource_ref':candidate['native_uuid'],
            'internal_upstream':'http://'+network_alias+':'+str(candidate['port']),
            'native_deployment_uuid':native_deployment_uuid,'state':'queued'}

    def services(self, actor, project_id):
        project=self.check(actor,project_id)
        with self.connection() as db:
            rows=[dict(r) for r in db.execute('SELECT * FROM services WHERE project_id=?',(project_id,))]
        for row in rows:
            native_state=self.backend.deployment(row['deployment_uuid']).get('status',row['state']) if row['deployment_uuid'] else row['state']
            if native_state=='finished' and row['state']!='ready' and project['role']=='owner':
                self._sync_comment_visibility(actor,project_id,project['visibility'],bindings=[row])
                with self.connection(True) as db:
                    db.execute("UPDATE services SET state='ready' WHERE project_id=? AND id=?",(project_id,row['id']))
                row['state']='ready'
            elif row['state']!='ready':row['state']=native_state
        return [{k:v for k,v in row.items() if k not in {'secret','upstream'}} for row in rows]

    def service_request(self, app, payload):
        access=self.authorize(app,payload)
        path=payload.get('path','')
        match=re.fullmatch(r'/__platform/services/([A-Za-z0-9_-]{1,80})(/.*)?',path)
        if not match:
            raise PlatformError(404,'Service route unavailable')
        binding_id=match[1];downstream=match[2] or '/'
        with self.connection() as db:
            binding=db.execute('SELECT * FROM services WHERE id=? AND project_id=?',(binding_id,app['project_id'])).fetchone()
        if not binding:
            raise PlatformError(404,'Service binding unavailable')
        module=importlib.import_module('chatcomment.access')
        scopes=access['site_permissions'][binding['site_id']]
        method=payload.get('method','GET')
        if access['authenticated']:
            session,project=self.reader(app,payload.get('reader_token',''))
            user=self.live(session.principal)
            context=module.AccessContext(subject=user.user_id,session=digest(payload['reader_token'].encode()),
                email=self.trusted_email(session.principal),
                sites={binding['site_id']:module.SiteAccess(**scopes)},
                csrf_verified=method in {'GET','HEAD'} or bool(payload.get('csrf')))
        else:
            parsed=urlsplit(downstream)
            public_api=re.fullmatch(r'/api/sites/([A-Za-z0-9_-]{1,64})/(config|comments)',parsed.path)
            same_site=public_api and public_api[1]==binding['site_id']
            permitted=(method in {'GET','HEAD'} and
                (parsed.path in {'/widget.js','/widget.css','/board'} or same_site))
            submission=method=='POST' and same_site and public_api[2]=='comments'
            if not permitted and not submission:
                raise PlatformError(403,'Guest access is limited to reading and adding comments')
            # POST was already checked by authorize(); GET can use the freshly
            # issued internal cookie when a visitor opens a service directly.
            cookie=self._guest_cookie(app,access.get('_guest_cookie') or payload.get('guest_token',''))
            if submission:self._guest_submission_limit(app,cookie)
            context=module.AccessContext(subject='guest:'+digest(cookie.encode())[:32],
                session=digest(cookie.encode()),email='',authenticated=False,
                sites={binding['site_id']:module.SiteAccess(**scopes)},
                csrf_verified=method in {'GET','HEAD'} or bool(payload.get('csrf')))
        try:
            raw=base64.b64decode(payload.get('body_b64',''),validate=True)
        except ValueError:
            raise PlatformError(422,'Invalid service request body') from None
        if len(raw)>2*1024*1024:
            raise PlatformError(413,'Service request exceeds limit')
        headers=module.sign_context(context,key=binding['secret'],method=payload['method'],path=downstream,body=raw)
        headers['Content-Type']=payload.get('content_type','application/json')
        if payload.get('origin'):headers['Origin']=payload['origin']
        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self,*args):return None
        request=Request(binding['upstream']+downstream,data=raw if payload['method'] not in {'GET','HEAD'} else None,
                        method=payload['method'],headers=headers)
        try:
            response=build_opener(NoRedirect()).open(request,timeout=20)
        except HTTPError as exc:
            response=exc
        with response:
            body=response.read(2*1024*1024+1)
            if len(body)>2*1024*1024:
                raise PlatformError(502,'Service response exceeds limit')
            return {'status':response.code,'body_b64':base64.b64encode(body).decode(),
                'content_type':response.headers.get('Content-Type','application/octet-stream'),
                'headers':{k:v for k,v in response.headers.items() if k.lower() in {'location','content-disposition'}}}
