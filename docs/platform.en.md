# Local project platform

`coolify platform` supports invited trusted collaborators: register a frontend project, upload a built local directory, inspect a preview, explicitly publish, view native logs and roll back. Independent backends remain native Coolify applications/services and can be associated with a project. The existing `CoolifyClient` and Git/backend API remain available.

Open the platform origin in a browser and sign in to see projects you own or have been granted access to, including production/preview links, your role and pending domain settings. Owners can create projects, select public/private visitor access, edit domain prefixes and explicitly apply them in this dashboard. Public website visitors do not sign in. The native Coolify administrator console is a separate surface; a platform account does not automatically receive native server or Team administration privileges.

```bash
coolify platform --profile work login --url https://<platform-origin> --username <account>
coolify platform --profile work projects create my-site
coolify platform --profile work upload PROJECT_ID ./dist
coolify platform --profile work preview PROJECT_ID RELEASE_ID
coolify platform --profile work status PROJECT_ID
coolify platform --profile work publish PROJECT_ID RELEASE_ID
coolify platform --profile work logs PROJECT_ID DEPLOYMENT_ID
coolify platform --profile work rollback PROJECT_ID PREVIOUS_PRODUCTION_RELEASE_ID
```

Passwords are entered through a hidden prompt or an environment variable named by `--password-env`. ChatEnv owns named endpoint profiles; TokenStore owns opaque sessions. Named profile selection does not change another active profile. Uploads exclude hidden files such as `.env` and `.git`, reject symlinks, credentials and reserved/traversal paths, and require `index.html`. Limits: 2,000 files, 8 MiB ZIP and 32 MiB expanded content. Arbitrary user Dockerfiles are not accepted.

## Readable managed domains

The operator configures `CHATCOOLIFY_DOMAIN_SUFFIX` with a suffix already served by wildcard DNS and HTTPS. A control origin named `platform.<suffix>` can supply the suffix when no explicit value is configured. New projects reserve `<slug>.<suffix>` for production and `<slug>-preview.<suffix>` for preview. Reserved infrastructure labels, existing native domains, production/preview names and historical addresses share conflict checks; long native UUIDs remain resource references.

Global platform claims cover every platform project. Native discovery covers plain/Compose applications and service child applications within the service account's Team; it is not cross-Team global discovery. Operators reserve other Teams' or shared routes through comma-separated full hostnames in `CHATCOOLIFY_RESERVED_HOSTS`. Domain conflicts are never force-overridden.

```bash
coolify platform --profile work domains list PROJECT_ID
coolify platform --profile work domains set PROJECT_ID notes.apps.example.net
coolify platform --profile work domains set PROJECT_ID notes-preview.apps.example.net --environment preview
```

Only the project owner can reserve another hostname. It must be one label under the managed suffix, without scheme, path or port. A setting does not publish or change the live URL. For a published environment, use the dashboard Save and apply action or `domains apply PROJECT_ID --environment production`. This repackages the verified published artifact with the current runtime into an immutable release when necessary; it never publishes an unpublished draft. Normal upload/preview/publish remains available. Activation follows native deployment success and signed runtime digest verification. Previous GET/HEAD addresses redirect to the canonical address and stay reserved. A failed deployment keeps the old canonical address.

`domains list` exposes `desired_url`, `current_url` and `pending`. The SDK uses the same contract through `client.domains(project_id)` and `client.set_domain(project_id, "notes.apps.example.net", environment="production")`. Domain activation does not migrate backend data. Backends that validate Origin, such as ChatComment, need an additive authorization of the new origin while preserving existing data/settings. External bring-your-own domains still require ownership, certificate and cross-site identity work; managed-prefix customization does not claim that capability.

## Native execution and provenance

The broker writes the artifact, controlled Dockerfile and reusable runtime into a private bare Git commit on the server. Native Coolify private-deploy-key applications build and run immutable images from that commit. Preview and production are separate native applications; upload alone does not alter production. Selected releases are explicitly published or rolled back through native deployments, never by switching a host-directory pointer. Successful status reconciles the native record and actual runtime artifact digest.

The SDK exposes stable platform IDs and sanitized native Team/Project/Environment/Application/Deployment references, artifact/Dockerfile digests and actual build commit. Optional original repository attribution is separate. Reuse request keys after interrupted requests; ambiguous dispatch is retained for reconciliation instead of blindly queued again. Sensitive or oversized build log lines are omitted.

`runtime_verified` and `verified_at` persist evidence that this deployment was actually verified; `runtime_active` describes the current probe. Verified historical deployments retain successful status. An older deployment that was never verified becomes `superseded_unverified` and cannot authorize rollback. Upgrades do not treat legacy `finished` metadata as verification evidence; an active version can acquire proof through a live probe. Rollback requires a previously verified production release in the same project.

Source keys stay in server/Coolify secret storage, outside application images. An SSH forced command only permits read-only `git-upload-pack` beneath the registered source root, rejecting shell access, writes and forwarding. Each build commit retains an immutable source ref; the individual repository allows reachable-SHA fetches so native shallow clones can roll back after main advances. Verify repository URL and custom-port syntax against the installed native version. No anonymous Git HTTP/daemon endpoint is provided.

## Public visitors, comments and management

New projects default to `public`: visitors read HTML/assets without a platform account. Use explicit `--visibility private` for restricted sites. Existing projects keep their current policy on upgrade. Owners change visibility in the dashboard, with `projects visibility PROJECT_ID public|private`, or `client.set_visibility(...)`. Opening access first synchronizes registered ChatComment policy; tightening first protects the frontend. Failure keeps the frontend private. This owner publication decision does not fabricate password reauthentication for comment management.

Public anonymous comments use short-lived signed host-only HttpOnly guest cookies, a separate CSRF token and exact same-origin checks. The raw backend still rejects unsigned requests. The bounded per-process budget is 10 posts per guest session/app/minute; a new cookie or restart resets it, so this is not a global IP/WAF abuse-control system. Owners can explicitly enter `/__platform/login?return_path=/` to manage a public site. Comment settings, exports and moderation still require owner authorization and password reauthentication.

The domain SDK also provides `client.apply_domain(project_id, environment="production")` for an explicit application of the reserved address to currently published bytes.

## Identity and access

Owners grant viewer/deployer collaboration; deployers preview, publish and roll back. Account administrators provision/disable accounts but have no implicit access to another project's content, deployments or service bindings. Every native target is derived from an authorized project mapping. Ordinary accounts never receive a shared Team token.

Invitation-only currently means an administrator runs `users create` and privately shares the initial password. There is no invitation email, invitation token or acceptance page. Native Coolify Pending invitations belong to its separate Team system; platform users do not automatically join that Team.

The same runtime guards every private HTML/JS/asset/export/service request, including raw native domains. Public read does not grant publishing or management. Private reads revalidate the account, reader session, central parent session and current project ACL, failing closed on authorization outage.

Control and app reader cookies are independent host-only Secure/HttpOnly cookies. Each app starts a 120-second `__Host-` state/nonce transaction, Path=/, no Domain, SameSite=Lax. Codes bind the app, state and central session and are consumed atomically. The single auto-POST callback requires the exact central Origin plus matching app cookie/form state; all other writes require same-origin CSRF. This protocol currently covers same-site HTTPS origins, not cross-site custom domains. Central logout invalidates children; account disable and project revocation affect existing readers. ChatLogin remains an embedded identity library; the platform host implements this issuer/reader protocol.

## SDK and services

```python
from chatcoolify import PlatformClient

client = PlatformClient.from_profile("work")
project = client.create_project("another-site")
release = client.upload(project["id"], "./dist")
preview = client.deploy(project["id"], release["id"], environment="preview")
```

`PlatformService` and `CoolifyBackend` are importable host APIs. Project owners use `services list PROJECT_ID --candidates`, then `services register` with an opaque candidate ID verified under that native project. Arbitrary URLs, host paths and other-project native UUIDs are rejected. The first transport adapter supports ChatComment request-bound signed site permissions, independently checked by the backend, including its raw native origin.

Operators configure the `coolify-platform-server` typed profile and run `coolify platform serve`. `bootstrap-owner` is server CLI only; there is no public signup/bootstrap route. The control plane itself should run as a native Coolify application with persistent identity/metadata/source storage and no Docker socket. Ordinary frontend apps have no host mounts.

Back up consistent ChatLogin/platform SQLite snapshots, private bare Git, immutable artifacts and private server configuration. Preserve reachable Git history/releases until an explicit retention policy exists; do not prune rollback sources automatically. Independent-service data remains on its own persistent mount, unaffected by frontend rollback. Verify new native resources and data before retiring an old entry.
