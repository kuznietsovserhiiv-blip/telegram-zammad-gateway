# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] - 2026-08-20

### Added

- Telegram media attachments, including photos, audio, voice messages, video, and video notes.
- Notifications between a linked Customer and the linked owner/Admin of a ticket.

### Fixed

- Enforce webhook request size limits before JSON deserialization.
- Stream Telegram media downloads with enforced size limits instead of buffering an entire file.

## [0.3.0] - 2026-08-17

### Added

- English Telegram command menus and reply keyboards.
- JSON translation catalogs in `app/locales/` for Ukrainian, English, and Russian.

## [0.2.0] - 2026-08-17

### Added

- Ukrainian and Russian Telegram command menus and reply keyboards, selected automatically from the Telegram client language without database changes.

## [0.1.4] - 2026-08-17

### Changed

- Document every public environment variable in `.env.example`.

## [0.1.3] - 2026-08-17

### Added

- Restore the safe `.env.example` configuration template in the public repository.

## [0.1.2] - 2026-08-17

### Changed

- Upgrade GitHub Actions checkout and Python setup actions to Node.js 24-compatible versions.

## [0.1.1] - 2026-08-17

### Fixed

- Run tests in GitHub Actions with `python -m pytest` so local application packages are importable.

## [0.1.0] - 2026-08-17

### Added

- Initial public release of Telegram Zammad Gateway.
- Telegram account linking, ticket conversations, and signed Telegram/Zammad webhooks.
- Docker deployment, GitHub Actions CI, security policy, and public documentation.
