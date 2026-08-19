# Public upstream and private downstream

The public upstream repository is:

`git@github.com:kuznietsovserhiiv-blip/telegram-zammad-gateway.git`

This GitLab branch, `skywell`, contains the public upstream plus Skywell-only configuration and automation. Do not commit internal domains, IP addresses, credentials, `.env` files, customer data, or production runbooks to the public repository.

## Updating from GitHub

```bash
git fetch upstream --tags
git switch public-main
git merge --ff-only upstream/main
git switch skywell
git merge public-main
```

Publish generic changes to GitHub first. Keep Skywell-specific changes in this branch.
