# Security Policy

## Supported use

tg-sgk is designed for bot-only Telegram automation through a user account session that you control.

The project does **not** support:

- messaging humans, groups, or channels
- bypassing verification, login, or 2FA flows
- automating payments, wallets, or Mini Apps

## Reporting a vulnerability

Please do **not** open a public issue for suspected security problems.

Instead, report the issue privately to the maintainer with:

- a description of the problem
- impact and affected components
- reproduction steps
- any suggested mitigation

Until a dedicated security contact is published, use a private maintainer contact method and avoid sharing live credentials, session files, API keys, or personal Telegram data.

## Secret handling

Never publish or commit:

- `.env` files
- Telegram session files
- SQLite databases
- login codes
- 2FA passwords
- API keys
