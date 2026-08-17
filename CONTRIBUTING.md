# Contributing

Thank you for contributing to Telegram Zammad Gateway.

## Development workflow

Create a focused branch from `main` for each change:

```bash
git switch main
git pull --ff-only
git switch -c fix/short-description
```

Before opening a pull request, run the local checks:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
ruff check app tests zammad_integration
python -m compileall -q app tests zammad_integration
pytest -q
```

Commit only the files relevant to your change and open a GitHub Pull Request against `main`. Keep pull requests focused and describe the behavior change, configuration impact, and verification performed.

## Pull request requirements

- Keep secrets, `.env` files, SQLite databases, and generated Zammad backups out of commits.
- Add or update tests when behavior changes.
- Update documentation when configuration, deployment, or user-facing behavior changes.
- Ensure the GitHub Actions workflow passes before merge.

## Repository settings

For a public repository, protect the `main` branch and require successful status checks and pull-request review before merging.
