# Security policy

## Reporting a vulnerability

Please **do not** open a public issue for security problems.

Report vulnerabilities privately through GitHub's
[private vulnerability reporting](../../security/advisories/new) for this repository. Include:

- a description of the issue and its impact,
- steps to reproduce (a minimal proof of concept if possible),
- affected files, endpoints or versions.

You can expect an acknowledgement within 3 working days and a status update within 10 working days.

## Scope

In scope: the backend API (`backend/`), the Next.js frontend and its route handlers (`frontend/`), and the
handling of stored credentials and personal data.

Out of scope: vulnerabilities in third-party platforms (LinkedIn, Telegram, Gmail), denial-of-service by
volume, and issues that require a compromised server or developer machine.

## Handling secrets

- Never commit `.env` files, browser profiles (`backend/data/`), resumes or database dumps; `.gitignore` excludes
  them.
- Production deployments must use their own `FERNET_KEY` and `INTERNAL_API_KEY`, serve over HTTPS with
  `COOKIE_SECURE=true`, and keep the Python API on a private network.
