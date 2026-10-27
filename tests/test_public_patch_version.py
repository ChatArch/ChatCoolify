"""The authorized forward patch must not keep a private build version."""
from pathlib import Path
from chatcoolify import __version__


def test_authorized_public_patch_version():
    assert __version__ == "0.2.4"


def test_public_patch_is_declared_in_metadata_and_changelog():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "0.2.4"' in (root / 'pyproject.toml').read_text()
    assert '## 0.2.4' in (root / 'CHANGELOG.md').read_text()
