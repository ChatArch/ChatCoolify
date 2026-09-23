"""Command-line interface for safe Coolify inspection and automation."""

from __future__ import annotations

import json
from typing import Any

import click

from . import __version__
from .client import DEFAULT_BASE_URL, CoolifyClient, CoolifyError, PublicApplicationSpec


CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}


def _emit(value: Any) -> None:
    click.echo(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str))


def _client(ctx: click.Context) -> CoolifyClient:
    return ctx.obj["client"]


def _handle_error(error: CoolifyError) -> None:
    raise click.ClickException(str(error)) from error


def _render_tree(command: click.Group, *, brief: bool) -> str:
    """Render the registered CLI surface instead of maintaining docs by hand."""

    options = ["--help", "--version", "--tree", "--tree-brief", "--base-url", "--allow-write"]
    lines = [command.name or "chatcoolify"]
    for option in options:
        lines.append(f"|- {option}")
    commands = sorted(command.commands.values(), key=lambda item: item.name)
    for index, subcommand in enumerate(commands):
        connector = "`-" if index == len(commands) - 1 else "|-"
        suffix = "" if brief else f"  # {subcommand.help or subcommand.short_help or ''}".rstrip()
        lines.append(f"{connector} {subcommand.name}{suffix}")
    return "\n".join(lines)


def _tree_callback(brief: bool):
    def callback(ctx: click.Context, _param: click.Parameter, value: bool) -> None:
        if not value or ctx.resilient_parsing:
            return
        click.echo(_render_tree(ctx.command, brief=brief))
        ctx.exit()

    return callback


@click.group(name="chatcoolify", context_settings=CONTEXT_SETTINGS)
@click.version_option(__version__, prog_name="chatcoolify")
@click.option("--tree", is_flag=True, is_eager=True, expose_value=False, callback=_tree_callback(False), help="Print the registered command tree.")
@click.option("--tree-brief", is_flag=True, is_eager=True, expose_value=False, callback=_tree_callback(True), help="Print the registered command tree without descriptions.")
@click.option(
    "--base-url",
    envvar="COOLIFY_BASE_URL",
    default=DEFAULT_BASE_URL,
    show_default=True,
    help="Coolify control-plane URL. Keep API tokens out of command arguments.",
)
@click.option(
    "--allow-write",
    is_flag=True,
    default=False,
    help="Allow commands that create or deploy resources. Read-only is the default.",
)
@click.pass_context
def main(ctx: click.Context, base_url: str, allow_write: bool) -> None:
    """Use the official Coolify REST API with a local AI safety gate."""

    ctx.ensure_object(dict)
    ctx.obj["client"] = CoolifyClient.from_env(allow_write=allow_write)
    if base_url != DEFAULT_BASE_URL:
        ctx.obj["client"] = CoolifyClient(
            base_url,
            token=ctx.obj["client"].token,
            allow_write=allow_write,
        )


@main.command()
@click.pass_context
def health(ctx: click.Context) -> None:
    """Call the public health endpoint; no API token is needed."""

    try:
        _emit(_client(ctx).health())
    except CoolifyError as error:
        _handle_error(error)


@main.command()
@click.pass_context
def team(ctx: click.Context) -> None:
    """Show the current team bound to the configured API token."""

    try:
        _emit(_client(ctx).current_team())
    except CoolifyError as error:
        _handle_error(error)


@main.command("overview")
@click.pass_context
def overview(ctx: click.Context) -> None:
    """Show a compact read-only inventory for the configured team."""

    client = _client(ctx)
    try:
        _emit(
            {
                "team": client.current_team(),
                "projects": client.list_projects(),
                "applications": client.list_applications(),
                "servers": client.list_servers(),
            }
        )
    except CoolifyError as error:
        _handle_error(error)


@main.command("projects")
@click.pass_context
def projects(ctx: click.Context) -> None:
    """List projects visible to the configured API token."""

    try:
        _emit(_client(ctx).list_projects())
    except CoolifyError as error:
        _handle_error(error)


@main.command("project")
@click.argument("project_uuid")
@click.pass_context
def project(ctx: click.Context, project_uuid: str) -> None:
    """Show one project and its environments by UUID."""

    try:
        _emit(_client(ctx).get_project(project_uuid))
    except CoolifyError as error:
        _handle_error(error)


@main.command("applications")
@click.pass_context
def applications(ctx: click.Context) -> None:
    """List applications visible to the configured API token."""

    try:
        _emit(_client(ctx).list_applications())
    except CoolifyError as error:
        _handle_error(error)


@main.command("application")
@click.argument("application_uuid")
@click.pass_context
def application(ctx: click.Context, application_uuid: str) -> None:
    """Show one application, including its allocated domain and status."""

    try:
        _emit(_client(ctx).get_application(application_uuid))
    except CoolifyError as error:
        _handle_error(error)


@main.command("servers")
@click.pass_context
def servers(ctx: click.Context) -> None:
    """List servers visible to the configured API token."""

    try:
        _emit(_client(ctx).list_servers())
    except CoolifyError as error:
        _handle_error(error)


@main.command("deployments")
@click.argument("application_uuid")
@click.option("--skip", default=0, type=click.IntRange(min=0), show_default=True)
@click.option("--take", default=20, type=click.IntRange(min=1), show_default=True)
@click.pass_context
def deployments(ctx: click.Context, application_uuid: str, skip: int, take: int) -> None:
    """List deployment history for one application."""

    try:
        _emit(_client(ctx).list_deployments(application_uuid, skip=skip, take=take))
    except CoolifyError as error:
        _handle_error(error)


@main.command("project-create")
@click.argument("name")
@click.option("--description", default=None, help="Optional project description.")
@click.pass_context
def project_create(ctx: click.Context, name: str, description: str | None) -> None:
    """Create a project. Requires the global --allow-write flag."""

    try:
        _emit(_client(ctx).create_project(name, description=description))
    except CoolifyError as error:
        _handle_error(error)


def _website_spec(
    project_uuid: str,
    server_uuid: str,
    environment_name: str,
    environment_uuid: str,
    repository_url: str,
    branch: str,
    build_pack: str,
    name: str | None,
    domain: str | None,
    publish_directory: str | None,
    port: int | None,
    health_check_path: str | None,
    spa: bool,
) -> PublicApplicationSpec:
    return PublicApplicationSpec(
        project_uuid=project_uuid,
        server_uuid=server_uuid,
        environment_name=environment_name,
        environment_uuid=environment_uuid,
        git_repository=repository_url,
        git_branch=branch,
        build_pack=build_pack,
        name=name,
        domains=domain,
        publish_directory=publish_directory,
        is_static=build_pack == "static",
        is_spa=spa,
        port=port,
        health_check_path=health_check_path,
    )


def _website_options(function):
    options = [
        click.option("--project-uuid", required=True),
        click.option("--server-uuid", required=True),
        click.option("--environment-name", default="production", show_default=True),
        click.option("--environment-uuid", required=True),
        click.option("--repository-url", required=True),
        click.option("--branch", default="main", show_default=True),
        click.option(
            "--build-pack",
            type=click.Choice(["static", "nixpacks", "railpack", "dockerfile", "dockercompose"]),
            default="static",
            show_default=True,
        ),
        click.option("--name", default=None),
        click.option(
            "--domain",
            default=None,
            help="Optional full HTTPS domain. Omit it to request Coolify's unique wildcard-pool domain.",
        ),
        click.option("--publish-directory", default="dist", show_default=True),
        click.option("--port", type=click.IntRange(min=1, max=65535), default=None),
        click.option("--health-check-path", default=None, help="Optional HTTP health-check path, for example /health."),
        click.option("--spa/--no-spa", default=True, show_default=True),
    ]
    for option in reversed(options):
        function = option(function)
    return function


@main.command("website-plan")
@_website_options
@click.pass_context
def website_plan(ctx: click.Context, **kwargs: Any) -> None:
    """Render a website payload without making a Coolify write request."""

    del ctx
    try:
        spec = _website_spec(**kwargs)
        _emit({"endpoint": "/api/v1/applications/public", "payload": spec.as_payload(instant_deploy=False)})
    except CoolifyError as error:
        _handle_error(error)


@main.command("website-create")
@_website_options
@click.option("--deploy", is_flag=True, default=False, help="Ask Coolify to deploy immediately after creation.")
@click.pass_context
def website_create(ctx: click.Context, deploy: bool, **kwargs: Any) -> None:
    """Create a public Git website. Requires the global --allow-write flag."""

    try:
        spec = _website_spec(**kwargs)
        _emit(_client(ctx).create_public_application(spec, instant_deploy=deploy))
    except CoolifyError as error:
        _handle_error(error)


@main.command("deploy")
@click.argument("application_uuid")
@click.option("--force", is_flag=True, default=False, help="Rebuild without the existing cache.")
@click.pass_context
def deploy(ctx: click.Context, application_uuid: str, force: bool) -> None:
    """Trigger a deployment. Requires the global --allow-write flag."""

    try:
        _emit(_client(ctx).deploy(application_uuid, force=force))
    except CoolifyError as error:
        _handle_error(error)


if __name__ == "__main__":  # pragma: no cover
    main()
