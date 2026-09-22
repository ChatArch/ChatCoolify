# Registration and invitations

Coolify controls servers, containers, domains, databases, and environment variables. A production instance should keep public registration disabled and admit only explicitly invited people.

## Invitation flow

1. Sign in as an administrator.
2. Switch to the target team.
3. Open **Team → Members**.
4. Enter the invitee email address and role.
5. Select **Generate link**, or select **Send email** after transactional email is configured.
6. Send the invitation link directly to the intended person.
7. Review, revoke, or replace entries under **Pending invitations**.

## Roles

| Role | Capability | Intended user |
| --- | --- | --- |
| Owner | Highest team authority, including owners | Platform maintainers |
| Admin | Resources, deployments, and ordinary members | Designated project leads |
| Member | Participates in authorized resources | Default external collaborator |

!!! danger
    Team roles isolate the Coolify control plane, not a virtual machine. Do not grant external members host SSH, Docker socket, sudo, privileged containers, or arbitrary host-volume mounts.

## Offboarding

- Remove the member and revoke pending invitations.
- Revoke API tokens created by that member.
- Review Git providers, webhooks, shared variables, and external-service credentials.
- Rotate runtime secrets that the person could access.
