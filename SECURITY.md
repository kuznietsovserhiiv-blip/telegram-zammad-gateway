# Security policy

## Reporting a vulnerability

Do not report security vulnerabilities in public GitHub issues.

Until a dedicated security contact is configured, report a vulnerability privately to the repository owner through GitHub. Include a clear description, affected version or commit, reproduction steps, and the potential impact.

The maintainer will acknowledge the report, assess it, and coordinate a fix before public disclosure where appropriate.

## Security notes for operators

- Keep `.env`, Telegram tokens, Zammad API tokens, and webhook secrets outside version control.
- Use unique, high-entropy values for webhook secrets.
- Serve public endpoints over HTTPS.
- Restrict the Gateway port to the reverse proxy or trusted network when possible.
- Update the container base image and Python dependencies regularly.
