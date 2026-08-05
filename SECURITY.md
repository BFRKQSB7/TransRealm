# Security Policy

## Supported versions

Before V1.0, security fixes are applied to the current `master` branch only.

## Reporting a vulnerability

Do not open a public issue for suspected credential exposure, data loss, unsafe archive import, or remote code execution. Contact the repository owner privately through GitHub and include reproduction steps without real secrets or user data.

The project will acknowledge the report, assess impact, prepare a fix and regression test, and coordinate disclosure after a safe update path exists.

## Security boundaries

- Credentials are referenced through `env:` or `wincred:`; raw secrets must not enter source, Projects, logs, exports, tests, or releases.
- User databases, backups, logs, exports, artifacts, and `.aiproject` files are not source-controlled.
- Published migrations are append-only.
