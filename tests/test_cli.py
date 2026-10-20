from __future__ import annotations

import json

from click.testing import CliRunner

from chatcoolify.cli import main


class _HealthClient:
    def health(self):
        return {"ok": True, "response": "OK"}


def test_health_command_uses_client_without_token(monkeypatch) -> None:
    monkeypatch.setattr(
        "chatcoolify.cli.CoolifyClient.from_env",
        classmethod(lambda cls, **_: _HealthClient()),
    )
    result = CliRunner().invoke(main, ["health"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"ok": True, "response": "OK"}


def test_version_and_registered_tree_are_available() -> None:
    runner = CliRunner()
    version = runner.invoke(main, ["--version"])
    assert version.exit_code == 0, version.output
    from chatcoolify import __version__
    assert __version__ in version.output
    tree = runner.invoke(main, ["--tree"])
    assert tree.exit_code == 0, tree.output
    assert tree.output.splitlines()[0] == "coolify"
    help_result = runner.invoke(main, ["--help"])
    assert help_result.exit_code == 0, help_result.output
    assert "Usage: coolify" in help_result.output
    assert "website-plan" in tree.output
    assert "project" in tree.output
    assert "application" in tree.output
    assert "--allow-write" in tree.output
    brief = runner.invoke(main, ["--tree-brief"])
    assert brief.exit_code == 0, brief.output
    assert "website-plan" in brief.output
    assert "platform" in brief.output
    assert "bootstrap-owner" in brief.output


def test_platform_domains_cli_uses_profile_and_explicit_environment(monkeypatch) -> None:
    class DomainClient:
        def domains(self, project):
            return {"project": project, "environments": []}

        def set_domain(self, project, hostname, *, environment):
            return {"project": project, "hostname": hostname, "environment": environment,
                    "pending": True}

    profiles = []

    def profile_client(cls, profile="default", **kwargs):
        profiles.append(profile)
        return DomainClient()

    monkeypatch.setattr("chatcoolify.platform_cli.PlatformClient.from_profile", classmethod(profile_client))
    runner = CliRunner()
    listed = runner.invoke(main, ["platform", "--profile", "work", "domains", "list", "project-1"])
    assert listed.exit_code == 0, listed.output
    assert json.loads(listed.output)["project"] == "project-1"
    changed = runner.invoke(main, ["platform", "--profile", "work", "domains", "set",
                                  "project-1", "notes-preview.apps.example.net", "--environment", "preview"])
    assert changed.exit_code == 0, changed.output
    assert json.loads(changed.output) == {"project": "project-1", "hostname": "notes-preview.apps.example.net",
                                          "environment": "preview", "pending": True}
    assert profiles == ["work", "work"]


def test_project_create_requires_explicit_write_flag() -> None:
    result = CliRunner().invoke(main, ["project-create", "demo"])
    assert result.exit_code != 0
    assert "write operation blocked locally" in result.output


def test_website_plan_has_no_write_side_effect() -> None:
    result = CliRunner().invoke(
        main,
        [
            "website-plan",
            "--project-uuid",
            "project-1",
            "--server-uuid",
            "server-1",
            "--environment-uuid",
            "environment-1",
            "--repository-url",
            "https://github.com/example/site",
            "--domain",
            "https://demo.example.com",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["endpoint"] == "/api/v1/applications/public"
    assert payload["payload"]["instant_deploy"] is False
    assert payload["payload"]["is_static"] is True
    assert payload["payload"]["autogenerate_domain"] is False


def test_website_plan_requests_a_wildcard_domain_when_omitted() -> None:
    result = CliRunner().invoke(
        main,
        [
            "website-plan",
            "--project-uuid",
            "project-1",
            "--server-uuid",
            "server-1",
            "--environment-uuid",
            "environment-1",
            "--repository-url",
            "https://github.com/example/site",
            "--health-check-path",
            "/health",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)["payload"]
    assert "domains" not in payload
    assert payload["autogenerate_domain"] is True
    assert payload["health_check_enabled"] is True
    assert payload["health_check_path"] == "/health"
