# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub's **Report a
vulnerability** button on this repository's Security tab. This is the only
reporting channel; there is no security email address. Do not open a public
issue for a suspected vulnerability. Fixes are made on the latest release.

## Security model

- **No credentials.** Canary never reads environment variables, `.env` files,
  or configuration files, and never holds an API key. Model access goes
  through a `ModelPort` object that the application constructs around its own
  client. `tests/test_boundaries.py` enforces this.
- **No network.** The package imports no provider SDK or network client.
- **Minimal file access.** Only `canary.ledger.append` writes, appending to a
  path the application passes; new ledger files are created readable by the
  owner only. Rubric seeds load from package data by validated name.
- **Closed judge outputs.** Judges accept only the labels, criteria, and keys
  their closed schema declares, and a second malformed answer is recorded as
  unavailable. Closed schemas do not stop content under evaluation from trying
  to steer a judge toward a wrong label; calibration against hand-labelled
  records, and review of disagreements, is the defence.

## Handling secrets when you use Canary

Canary's records are meant to be stored and shared: ledger payloads, score
evidence, calibration reports (including error messages), and freeze
configuration. Never put credentials into them, and make your `ModelPort`
adapter raise errors that do not echo provider responses. The
[integration guide](docs/integration.md#keep-keys-out-of-evaluation-artifacts)
explains both.

This repository contains no credentials. `tests/test_repository_hygiene.py`
fails on credential-shaped strings or committed `.env` files in any
publishable file.
