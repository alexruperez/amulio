# Contributing to aMulio

Thanks for helping improve aMulio. Contributions are accepted under the
[Apache-2.0 license](LICENSE) and must follow the
[Code of Conduct](CODE_OF_CONDUCT.md).

## Before opening a pull request

Use Python 3.12 and [uv](https://docs.astral.sh/uv/):

```sh
uv sync --group dev
uv run playwright install chromium
uv run ruff check .
uv run ruff format --check .
uv run pytest -rs --cov=amulio --cov-fail-under=82
uv run pip-audit
docker compose --env-file .env.example config --quiet
```

The integration test is intentionally skipped unless
`AMULIO_INTEGRATION_URL` points to the dedicated Docker fixture. Keep it
skipped in normal contributor runs; see `tests/integration/README.md` when
changing the amuleapi boundary.

The configuration UI test runs against a local, ephemeral aMulio server and
Chromium. It covers responsive desktop/mobile layout, keyboard navigation,
native form validation and profile-manifest generation; it needs neither Docker
nor a running aMule instance.

## Scope and pull requests

- Discuss material product or architecture changes in an issue first.
- Keep each pull request focused and add tests for behavioral changes.
- Preserve or improve the 82% coverage floor. Explain any justified exception
  in the pull request description.
- Do not add credentials, private installation URLs, eD2K links, copyrighted
  media metadata, downloaded media, or production logs.
- Update README, operations, configuration or plan documentation whenever a
  user-facing behavior changes.

CI runs linting, Playwright UI tests, coverage, Compose validation, Docker builds, dependency
auditing and CodeQL. Dependabot maintains GitHub Actions, Python and Docker
dependencies; please review its pull requests like any other change.

## Reporting problems

Use GitHub Issues for reproducible bugs and feature requests. Use the private
process in [SECURITY.md](SECURITY.md) for vulnerabilities instead of a public
issue.
