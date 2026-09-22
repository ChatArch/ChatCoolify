# Development

## Local checks

```bash
python -m pip install -e '.[dev,docs]'
python -m pytest -q
python -m mkdocs build --strict
python -m build
python -m twine check dist/*
python scripts/check_no_secrets.py
```

## Release contract

1. A feature branch and pull request pass CI and Docs Preview.
2. The merged `main` commit passes the default-branch CI and Docs deployment.
3. The release tag `vX.Y.Z` is created from the merged `main` commit.
4. `publish.yml` uses GitHub OIDC and the PyPI Trusted Publisher configuration.
5. PyPI exact-version JSON, project JSON, Simple index, and clean installation are verified.

Do not use a long-lived PyPI upload token for a normal release. Do not include an API token, cookie, password, or credential-bearing URL in source, docs, CI logs, or issue text.
