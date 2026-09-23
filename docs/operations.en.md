# Operations and safety

## Token rules

- Create separate tokens for each team, AI client, and CI workflow.
- Start with `read`.
- Use `deploy` only for existing application lifecycle actions.
- Use short-lived `write` only to create or modify resources.
- Do not use `root` for routine automation.
- Set expirations and rotate or revoke tokens regularly.

## Two-stage AI commit

1. `website-plan` renders an official API payload without a remote write.
2. A person reviews the resources, domain, repository, environment, and limits.
3. Use `--allow-write` to create or deploy.
4. Return to a read-only token and inspect status and log summaries.

## Pre-release checklist

- [ ] Repository provenance and license are reviewed.
- [ ] Build and start commands are explicit.
- [ ] CPU, memory, storage, and build concurrency are bounded.
- [ ] Health checks work.
- [ ] TLS, domains, and redirects are correct.
- [ ] Secrets are absent from Git, logs, and prompts.
- [ ] Backup and restore are verified.
- [ ] Team members and tokens follow least privilege.
- [ ] A known stable version exists for rollback.

## Failure handling

| Symptom | First action |
| --- | --- |
| Control plane unavailable | Run `coolify health` |
| 401 | Check token completeness, expiry, and revocation |
| 403 | Check team, permission, API Access, and IP allowlist |
| 422 | Correct request fields; do not replay writes blindly |
| 429 | Follow `Retry-After`; do not retry writes concurrently |
| Deployment failure | Stop automatic retries, inspect the deployment, and decide on a fix or rollback |

## Host boundary

Coolify is a high-privilege control plane. Team roles do not equal VM-grade isolation; untrusted code should not share a Docker daemon with existing production workloads.
