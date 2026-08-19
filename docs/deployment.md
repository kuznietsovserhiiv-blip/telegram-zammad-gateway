# Deployment guide

## Direct Docker deployment

Run the installer from the project directory:

```bash
chmod +x scripts/deploy.sh
./scripts/deploy.sh
```

It creates a protected `.env`, builds the image, starts the container, and checks `/healthz`.

Use neutral example values such as `https://gateway.example.com` for the Gateway and `https://zammad.example.com` for Zammad.

For Internet-facing deployments, put the Gateway behind an HTTPS reverse proxy such as Nginx, Caddy, Traefik, or a cloud load balancer. IIS is not required.

## Important same-origin requirement

The `/link` page uses the current Zammad session cookie to identify the logged-in user. The browser must therefore open the page from an origin that can send that cookie.

If the Gateway and Zammad use different origins, direct access to `/link` will not automatically receive the Zammad session cookie. In that case, expose the Gateway under the Zammad origin through a reverse proxy, or implement a separate authentication flow.

For a same-origin setup:

```dotenv
PUBLIC_BASE_URL=https://zammad.example.com/telegram-gateway
ALLOWED_ORIGINS=https://zammad.example.com
```

## Manual deployment

```bash
cp .env.example .env
nano .env
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8090/healthz
```

The `./data` directory is mounted as `/data` and stores the SQLite database. Never commit `.env` or `data/`.

Important variables:

- `PUBLIC_BASE_URL` — public Gateway URL;
- `ALLOWED_ORIGINS` — comma-separated browser origins;
- `ZAMMAD_BASE_URL` — Zammad URL;
- `TELEGRAM_BOT_TOKEN` and `TELEGRAM_WEBHOOK_SECRET` — Telegram credentials;
- `ZAMMAD_API_TOKEN`, `ZAMMAD_WEBHOOK_SECRET`, and `ZAMMAD_SERVICE_USER_ID` — Zammad credentials;
- `GATEWAY_BIND_IP` and `GATEWAY_PORT` — Docker-published bind address and port.

## Telegram webhook

After deployment:

```bash
docker compose exec gateway python -m app.webhook_admin set
docker compose exec gateway python -m app.webhook_admin info
docker compose exec gateway python -m app.menu_admin set-default
```

The webhook endpoint is `${PUBLIC_BASE_URL}/telegram/webhook`.

## Zammad webhook

Create an active webhook in Zammad:

- URL: `${PUBLIC_BASE_URL}/zammad/webhook`;
- Method: `POST`;
- Signature Token: the value of `ZAMMAD_WEBHOOK_SECRET`;
- Payload: standard.

Trigger the webhook from Zammad. The Gateway forwards only public Agent articles and actual ticket state changes. Internal notes, Customer articles, and service-user articles are ignored.

## Optional IIS ARR setup

IIS ARR is only needed when the Gateway must be exposed under the Zammad origin. Example rule for `https://zammad.example.com`:

- Match URL: `^telegram-gateway/(.*)`;
- Rewrite URL: `http://127.0.0.1:8090/{R:1}`;
- Append query string: enabled;
- Stop processing: enabled.

Place the rule above the general Zammad rule and restrict the Gateway port to the reverse proxy where possible.

## Retention and security

Pending actions expire after 15 minutes. Processed Telegram updates and completed Zammad deliveries are retained for 30 days by default; configure this with `EVENT_RETENTION_DAYS`.

Use strong, unique values for all webhook secrets and keep `.env` outside version control.
