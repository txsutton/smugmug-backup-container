# Security policy

## Reporting a vulnerability

If you believe you've found a security issue, please **do not open a public
issue or pull request**. Public reports give attackers a head start before a
fix is available.

Instead, use **GitHub's private vulnerability reporting**:

1. Go to the [Security tab](../../security) of this repository.
2. Click **Report a vulnerability**.
3. Fill in the form. Only the maintainer and GitHub Security can see it.

GitHub's docs:
[Privately reporting a security vulnerability](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)

This is a hobby-maintained project. I'll do my best to acknowledge reports
within a couple of weeks and ship a fix or mitigation when feasible. There
is no SLA and no bug bounty.

## Scope

In scope:

- Path traversal, arbitrary file write, or any way to make `sync.py` write
  outside its configured `DATA_DIR`.
- Credential leakage in logs, container layers, error messages, or via
  network requests to anywhere other than `api.smugmug.com`.
- Container escape or privilege escalation issues in the published image.
- Vulnerabilities in pinned dependencies that materially affect this tool.

Out of scope:

- Issues that require an attacker to already control your `.env` file or
  your local filesystem.
- Issues in SmugMug's own API.
- Findings that depend on running the tool with custom modifications.
- Automated scanner reports without a working proof of concept.

## What this tool reads and sends

- Reads from: `api.smugmug.com` (your photos and metadata, signed with
  your OAuth credentials), and the local SQLite state DB.
- Writes to: the configured `DATA_DIR` (default `/data` in the container)
  and the local SQLite DB inside it. Nothing else.
- Does not transmit anything to any third party, telemetry endpoint, or
  analytics service.
