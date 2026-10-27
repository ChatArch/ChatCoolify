"""Public release documentation must not retain an active private-build claim."""
from pathlib import Path


def test_active_documentation_does_not_claim_the_distribution_is_a_private_build():
    root = Path(__file__).resolve().parents[1]
    files = [root / 'README.md', root / 'README.en.md', root / 'DEVELOP.md', *sorted((root / 'docs').glob('*.md'))]
    stale = ('0.2.2+access.1', '0.2.2+publicread.1',
             'This private build does not add or rename CLI commands.',
             'not a formal PyPI release', '不是 PyPI 正式发版')
    findings = [(path.relative_to(root).as_posix(), marker)
                for path in files for marker in stale if marker in path.read_text()]
    assert findings == []
