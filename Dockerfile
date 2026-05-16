FROM python:3.11-slim

# Prevent Python from writing .pyc files and buffer stdout
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first so the layer caches well.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY sync.py .

# Run as a non-root user so files written into the bind-mounted /data are
# owned by a predictable UID (1000 matches the default user on most NAS
# systems and Linux desktops). Override at run time with `--user <uid>:<gid>`
# if you need to match a different host UID.
RUN groupadd --system --gid 1002 smugmug-backup \
 && useradd  --system --uid 1002 --gid smugmug-backup --no-create-home --shell /usr/sbin/nologin smugmug-backup \
 && mkdir -p /data \
 && chown -R smugmug-backup:smugmug-backup /app /data
USER smugmug-backup

# /data is a mount point for the bind-mounted backup directory.
VOLUME ["/data"]

# Run the sync script
ENTRYPOINT ["python", "sync.py"]
