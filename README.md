# 📸 SmugMug Docker Sync

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://www.docker.com/)

A hash-verified backup tool for SmugMug, designed to run in Docker on a NAS
(Asustor, Synology, Unraid) or any Linux/macOS/Windows host. Downloads the
original archived versions of every photo, mirrors your folder/album
structure on disk, and resumes cleanly after interruptions.

---

## Features

- **MD5-verified downloads** with atomic write (`.part` then rename) so
  partial files never masquerade as good ones.
- **SQLite state DB** for near-instant resume; only changed/new photos are
  downloaded on subsequent runs.
- **`--verify` and `--repair` modes** for periodic bit-rot checks against
  the local copies, no SmugMug calls required.
- **Robust HTTP layer** with retries on 429/5xx, exponential backoff,
  `Retry-After` honored.
- **Path-traversal hardened** filename sanitization safe for Windows, macOS
  and Linux. Case-insensitive collisions in the same album are
  automatically disambiguated.
- **Non-root container**, read-only root filesystem, secrets via env vars only.
- **Graceful shutdown** on Ctrl+C / SIGTERM (queued downloads cancelled,
  in-flight `.part` files cleaned up on next run).

---

## Getting your credentials

You need a SmugMug **API key + secret** (your "app") and an **access token +
secret** (permission for that app to read your account).

### 1. Register an app

Sign in at [SmugMug API Keys](https://api.smugmug.com/api/v2/apps), create a new
app, and note the API Key and API Secret. Read access is enough.

### 2. Run the OAuth helper

`authenticate.py` walks you through the OAuth1 PIN flow and writes a complete
`.env` file in the current directory.

```powershell
# Windows / PowerShell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python authenticate.py
```

```bash
# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python authenticate.py
```

You'll be prompted for the API key, secret, and your SmugMug nickname (the URL
slug, e.g. `https://<nickname>.smugmug.com/`). The script then prints a SmugMug
authorization URL; open it, click Authorize, and paste the 6-digit PIN back into
the terminal. On success a `.env` file is written and chmod'd to 600 on POSIX.

> Treat `.env` like a password. It's already in `.gitignore`. Don't commit it.

---

## Configuration

| Variable        | Required | Purpose                                                      |
| --------------- | :------: | ------------------------------------------------------------ |
| `API_KEY`       |    ✓     | Your SmugMug app key.                                        |
| `API_SECRET`    |    ✓     | Your SmugMug app secret.                                     |
| `ACCESS_TOKEN`  |    ✓     | OAuth access token for your account (from `authenticate.py`).|
| `ACCESS_SECRET` |    ✓     | OAuth access token secret.                                   |
| `NICKNAME`      |    ✓     | Your SmugMug URL slug (the part before `.smugmug.com`).      |
| `DATA_DIR`      |          | Output directory. Defaults to `/data` (the container mount). Override for local testing. |

---

## Run with Docker (recommended)

### 1. Build the image

```bash
docker build -t smugmug-sync:latest .
```

### 2. Run with docker compose

Edit the `volumes:` line in [`stack-docker-compose.yaml`](./stack-docker-compose.yaml)
to point at where you want the photos saved, then:

```bash
docker compose -f stack-docker-compose.yaml up
```

The container will sync, print a summary, and exit. `restart: on-failure:3`
ensures it retries a few times on transient failures but doesn't loop forever.

### 3. Run the integrity check

```bash
docker compose -f stack-docker-compose.yaml run --rm smugmug-sync --verify
```

Or to also auto-delete corrupted local copies and queue them for re-download
on the next sync:

```bash
docker compose -f stack-docker-compose.yaml run --rm smugmug-sync --repair
```

### Matching your NAS user (optional)

The container runs as UID 1002 by default, which lines up with most desktop
Linux installs. Synology users typically need a higher UID (often 1024-1030).
Find your UID with `id -u` on the NAS, then run:

```bash
docker run --rm \
  --user $(id -u):$(id -g) \
  --env-file .env \
  -v /volume2/Photos/smugmug-backup:/data \
  smugmug-sync:latest
```

Or set `user: "1002:1002"` (or whatever your IDs are) in `stack-docker-compose.yaml`.

---

## Run without Docker (local testing)

Useful for quick iteration or running on the host directly.

```powershell
# Windows / PowerShell
.venv\Scripts\Activate.ps1
Get-Content .env | ForEach-Object {
    if ($_ -match '^\s*([^#=]+?)\s*=\s*(.*)\s*$') {
        [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process')
    }
}
$env:DATA_DIR = "$pwd\test-data"
python sync.py
```

```bash
# Linux / macOS
source .venv/bin/activate
set -a; source .env; set +a
export DATA_DIR="$PWD/test-data"
python sync.py
```

---

## CLI

```
python sync.py            # full sync (default)
python sync.py --verify   # offline integrity check, exit 0 if all OK, 1 otherwise
python sync.py --repair   # implies --verify; deletes bad files and DB rows so the next sync re-downloads them
```

The full sync also runs an automatic cleanup of orphan `.part` files
left behind by previous interruptions.

---

## Suggested cron / scheduled task

- **Daily**: `python sync.py` (or run the container) to pick up new photos.
- **Weekly or monthly**: `python sync.py --verify` to detect bit rot.
  If it finds anything, run `--repair` then a normal sync to fix.

---

## Project structure

```
sync.py                        Main sync engine and CLI (--verify / --repair).
authenticate.py                One-time OAuth helper that writes .env.
Dockerfile                     Slim Python image, non-root user.
stack-docker-compose.yaml      Compose template for Portainer / docker compose.
.dockerignore                  Keeps secrets and test data out of built images.
requirements.txt               Python dependencies.
```

---

## Security notes

- Credentials are never logged, never written to disk except in `.env`,
  and never sent anywhere except `api.smugmug.com`.
- All file paths are sanitized and confined to `DATA_DIR`. SmugMug filenames
  containing `..`, path separators, Windows-illegal characters, or device
  names like `CON`/`NUL` are rewritten before use.
- HTTP downloads validate Content-Type and reject HTML responses (defense
  in depth against unsigned redirects to login pages).
- See [SECURITY.md](./SECURITY.md) for vulnerability reporting.

---

## Credits

Inspired by [smugmug-bulk-downloader](https://github.com/dannoll/smugmug-bulk-downloader)
by dannoll. The API navigation patterns were guided by that project; the
present implementation is an independent rewrite focused on Docker, integrity
verification, and resume.

---

## License

MIT, see [LICENSE](./LICENSE).
