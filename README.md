# Telegram Zammad Gateway

A self-hosted gateway for two-way integration between the Telegram Bot API and Zammad.

The project provides:

- one-time linking of Telegram accounts to Zammad users;
- signed Telegram and Zammad webhooks;
- Customer and Admin conversations around Zammad tickets;
- notifications for public Agent articles and ticket state changes;
- SQLite-backed links, sessions, pending actions, and event deduplication.

This project is specifically designed for Zammad and Telegram. It is not currently a generic adapter for arbitrary helpdesk systems.

## Why use this gateway instead of Zammad's built-in Telegram channel?

Zammad includes a native Telegram channel for the basic workflow: an incoming Telegram message creates a ticket and an Agent reply is delivered back to the user. See the [Zammad Telegram documentation](https://admin-docs.zammad.org/en/pre-release/channels/telegram.html).

This Gateway targets a different workflow. It links a Telegram account to an authenticated Zammad user and lets that user work with their existing tickets from the bot. Customers can create, list, select, and continue their own tickets; Admins can work with assigned or new tickets through role-aware commands.

Do not configure the same Telegram bot token in both the native Zammad channel and this Gateway. Telegram delivers updates to one webhook endpoint, so use one integration per bot.

## Quick start

The recommended deployment does not require IIS. You need Docker Compose, `curl`, and a Telegram bot.

```bash
git clone <repository-url>
cd telegram-zammad-gateway
chmod +x scripts/deploy.sh
./scripts/deploy.sh
```

The installer asks for the public Gateway URL, the Zammad URL, Telegram credentials, and Zammad credentials. By default, the Gateway is published on `0.0.0.0:8090`.

See [deployment.md](docs/deployment.md) for the complete setup, webhook configuration, reverse proxy notes, and environment variables.

## Supported Telegram commands

- Customer: `/new`, `/mytickets`, `/current`, `/close`;
- Admin: `/my`, `/newtickets`, `/ticket`, `/current`, `/close`.

Customer messages are added to the active ticket. Admin messages are added as public Agent articles.

## Languages

The interactive bot menu supports Ukrainian, English, and Russian. The Gateway chooses the menu language from Telegram's `language_code` in each incoming update; Ukrainian is the fallback. No database migration or per-user language setting is required. Translations are kept in the editable JSON files under `app/locales/`.

Background notifications initiated by Zammad use the Gateway's default text because Telegram does not include the recipient's UI language in those webhook events.

## Development

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
ruff check app tests zammad_integration
pytest -q
```

## License

Distributed under the [MIT License](LICENSE).

Telegram Zammad Gateway is an independent integration that communicates with Zammad through its HTTP API and webhooks. It does not include or redistribute Zammad source code. The optional Linked Accounts installer adds Telegram only under `Profile → Linked Accounts`, not on the Zammad sign-in page. Zammad itself is licensed under AGPL-3.0; see the [Zammad repository](https://github.com/zammad/zammad).

## Releases

The project uses [Semantic Versioning](https://semver.org/). See [CHANGELOG.md](CHANGELOG.md) for release notes.
