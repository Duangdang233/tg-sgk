# Contributing to tg-sgk

Thanks for helping improve tg-sgk.

## Before you start

- Read the security boundary in `README.md`.
- Never commit `.env`, Telegram sessions, local databases, login codes, or 2FA passwords.
- Keep changes focused and avoid unrelated refactors.

## Development setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest -q
ruff check app tests
```

For the OpenClaw plugin:

```bash
cd openclaw-plugin
npm install --legacy-peer-deps
npm run build
node --check dist/index.js
```

## Pull requests

- Explain the problem and the user-visible change.
- Include tests or validation notes when behavior changes.
- Keep secrets out of commits, screenshots, logs, and examples.

## Scope expectations

Contributions must preserve these project boundaries:

- Bot-only Telegram automation
- No support for messaging humans, groups, or channels
- No bypass of login, payment, wallet, Mini App, or verification flows
