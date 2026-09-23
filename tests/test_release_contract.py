from __future__ import annotations

from pathlib import Path

from chatcoolify import DEFAULT_BASE_URL, __version__


ROOT = Path(__file__).resolve().parents[1]


def test_public_defaults_do_not_target_a_private_instance() -> None:
    assert DEFAULT_BASE_URL == "https://coolify.example.com"
    public_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
    )
    assert "https://coolify.example.com" not in public_text
    assert "/home/" not in public_text


def test_release_workflow_is_tag_driven_oidc() -> None:
    workflow = (ROOT / ".github/workflows/publish.yml").read_text(encoding="utf-8")
    assert 'tags:\n      - "v*"' in workflow
    assert "id-token: write" in workflow
    assert "pypa/gh-action-pypi-publish@release/v1" in workflow
    assert "PYPI_API_TOKEN" not in workflow
    assert "TWINE_PASSWORD" not in workflow
    assert f'print(f"tag=v{{version}}"' in workflow


def test_docs_and_readmes_match_release_identity() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "ChatCoolify"' in pyproject
    assert f'version = "{__version__}"' in pyproject
    assert "https://arch.gh.wzhecnu.cn/ChatCoolify/" in pyproject
    assert (ROOT / "README.en.md").is_file()
    assert (ROOT / "docs/assets/cases/coolifyhello-release-4.png").is_file()
    assert (ROOT / "docs/assets/cases/coolifyhello-release-4-commit.png").is_file()
    for stem in (
        "index",
        "registration",
        "ai-integration",
        "python-client",
        "cli-tree",
        "capability-map",
        "simple-website",
        "self-service-demo",
        "full-stack",
        "operations",
    ):
        assert (ROOT / "docs" / f"{stem}.en.md").is_file()


def test_ci_builds_docs_and_installed_cli() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "python -m mkdocs build --strict" in workflow
    assert "chatcoolify --version" in workflow
    assert "chatcoolify --tree" in workflow
    assert "python scripts/check_public_docs.py" in workflow
