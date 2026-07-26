# Security policy

## Supported versions

Security fixes are applied to the latest commit on `main`. Deployments should
track a signed release or a reviewed signed commit from that branch.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Send a concise report
to [me@alexruperez.com](mailto:me@alexruperez.com) with reproduction steps,
affected version or commit, impact and any suggested mitigation. Do not include
real credentials, private installation URLs or copyrighted media.

You will receive an acknowledgement within seven days. We will assess the
report, coordinate a fix and then publish an advisory or release notes when it
is safe to do so. Please allow a reasonable remediation period before public
disclosure.

## Automated controls

GitHub Dependabot monitors Python, Docker and GitHub Actions dependencies.
Secret scanning with push protection and CodeQL scanning are enabled for the
repository. CI also runs `pip-audit` against the locked development environment.
