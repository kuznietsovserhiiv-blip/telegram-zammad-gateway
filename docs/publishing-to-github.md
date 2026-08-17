# Publishing to GitHub

This directory is a clean public snapshot of the project. It intentionally excludes GitLab CI configuration, local Git metadata, deployment data, `.env` files, SQLite databases, and IDE files.

## Before the first push

1. Review the staged files for organization-specific names, domains, IP addresses, and secrets.
2. Replace `<repository-url>` in `README.md` with the GitHub repository URL.
3. Confirm the license copyright holder is correct.
4. Run the checks from `README.md`.
5. Create a new empty GitHub repository without auto-generated files, then add it as `origin`.

## First commit and push

```bash
git add .
git commit -m "Initial public release"
git tag -a v0.1.0 -m "Initial public release"
git remote add origin git@github.com:<owner>/telegram-zammad-gateway.git
git push -u origin main
git push origin v0.1.0
```

Keep Skywell-specific infrastructure, production configuration, and GitLab-only automation in the private GitLab repository. Submit reusable changes to the public GitHub repository first, then merge or rebase them into the private downstream repository.
