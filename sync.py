import os
import re
import sys
import signal
import sqlite3
import hashlib
import argparse
import threading
import requests
import concurrent.futures
from pathlib import Path
from requests.adapters import HTTPAdapter
from requests_oauthlib import OAuth1
from urllib3.util.retry import Retry

# Configuration pulled from Environment Variables
API_KEY = os.getenv('API_KEY')
API_SECRET = os.getenv('API_SECRET')
ACCESS_TOKEN = os.getenv('ACCESS_TOKEN')
ACCESS_SECRET = os.getenv('ACCESS_SECRET')
NICKNAME = os.getenv('NICKNAME')
# Defaults to /data for the container; override with DATA_DIR for local testing.
DATA_DIR = os.getenv('DATA_DIR', '/data')
BASE_URL = "https://api.smugmug.com/api/v2"
API_HOST = "https://api.smugmug.com"

# (connect timeout, read timeout) in seconds. Prevents the container hanging forever
# on a stalled SmugMug API call or download.
HTTP_TIMEOUT = (10, 60)

# Characters that are illegal in Windows filenames (and odd elsewhere). We replace
# them with "_". Forward slash and backslash are handled separately because they're
# path separators on the relevant OSes.
_INVALID_NAME_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')

# Windows reserves these device names regardless of extension. SmugMug allows
# arbitrary names, so we have to defend against them.
_RESERVED_WIN_NAMES = {
    'CON', 'PRN', 'AUX', 'NUL',
    *(f'COM{i}' for i in range(1, 10)),
    *(f'LPT{i}' for i in range(1, 10)),
}

# Global cancellation flag set by SIGINT/SIGTERM handlers so worker threads
# can exit promptly instead of holding the process open through atexit.
_cancel = threading.Event()


def _install_signal_handlers():
    def handler(signum, frame):
        if _cancel.is_set():
            # Second Ctrl+C: bail immediately, don't wait for graceful shutdown.
            print("\nForce exit.", file=sys.stderr)
            os._exit(130)
        print("\nCancellation requested, finishing current downloads...", file=sys.stderr)
        _cancel.set()

    signal.signal(signal.SIGINT, handler)
    # SIGTERM only exists on POSIX; Windows raises AttributeError if we try.
    if hasattr(signal, 'SIGTERM'):
        try:
            signal.signal(signal.SIGTERM, handler)
        except (ValueError, OSError):
            pass

# Result codes returned from download_image so process_album can summarize.
RESULT_DOWNLOADED = 'downloaded'
RESULT_SKIPPED = 'skipped'
RESULT_MISMATCH = 'mismatch'
RESULT_FAILED = 'failed'


def _safe_name(name, fallback='unnamed'):
    """Make a single path component safe for both POSIX and Windows.

    - Strips path separators and parent-directory tricks.
    - Replaces characters illegal on Windows with "_".
    - Strips leading/trailing whitespace and dots (Windows quirk).
    - Adds a suffix to Windows reserved device names.
    - Truncates to 200 chars to leave room under MAX_PATH.
    """
    if not name:
        return fallback
    # Drop any path separators or parent refs entirely.
    name = name.replace('/', '_').replace('\\', '_')
    if name in ('.', '..'):
        return fallback
    # Replace illegal characters.
    name = _INVALID_NAME_CHARS.sub('_', name)
    # Trim leading/trailing whitespace and dots; Windows refuses these.
    name = name.strip(' .')
    if not name:
        return fallback
    # Avoid device-name collisions on Windows.
    stem = name.split('.', 1)[0].upper()
    if stem in _RESERVED_WIN_NAMES:
        name = '_' + name
    if len(name) > 200:
        # Preserve the extension if present.
        base, dot, ext = name.rpartition('.')
        if dot and len(ext) <= 10:
            name = base[: 200 - len(ext) - 1] + '.' + ext
        else:
            name = name[:200]
    return name


def _is_within(parent, child):
    """True if `child` resolves to a path under `parent` (no traversal)."""
    try:
        parent_resolved = Path(parent).resolve()
        child_resolved = Path(child).resolve()
        return parent_resolved == child_resolved or parent_resolved in child_resolved.parents
    except OSError:
        return False


def _api_url(path_or_url):
    """Resolve a SmugMug API reference to an absolute URL.

    SmugMug returns paths in two flavors:
      - already-absolute (rare): "https://api.smugmug.com/api/v2/node/abc"
      - rooted path (common):    "/api/v2/node/abc"
    Older code in this repo also passed bare suffixes like "/user/<nick>", so
    handle that too. Result is always a single, well-formed URL.
    """
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        return path_or_url
    if path_or_url.startswith("/api/v2"):
        return API_HOST + path_or_url
    if path_or_url.startswith("/"):
        return BASE_URL + path_or_url
    return BASE_URL + "/" + path_or_url


def _check_env():
    """Fail fast with a clear message if any required credential is missing."""
    required = {
        'API_KEY': API_KEY,
        'API_SECRET': API_SECRET,
        'ACCESS_TOKEN': ACCESS_TOKEN,
        'ACCESS_SECRET': ACCESS_SECRET,
        'NICKNAME': NICKNAME,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        print(
            "ERROR: missing required environment variables: "
            + ", ".join(missing)
            + ". Check your .env file and that env_file is loaded by docker compose.",
            file=sys.stderr,
        )
        sys.exit(1)


def _build_session(auth):
    """A requests.Session with sane retries for the long-running sync.

    Retries on 429 and 5xx with exponential backoff. Honors any Retry-After
    header SmugMug sends back. Keeps a connection pool large enough for the
    threadpool below.
    """
    session = requests.Session()
    session.auth = auth
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        status=5,
        backoff_factor=2.0,  # 0, 2, 4, 8, 16 seconds between retries
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(['GET', 'HEAD']),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=16, pool_maxsize=16)
    session.mount('https://', adapter)
    session.mount('http://', adapter)
    return session


class SmugMugSync:
    def __init__(self, online=True):
        """Build a sync instance.

        online=True (default): full sync mode. Builds the OAuth-signed HTTP
        session and validates env vars upstream.

        online=False: offline maintenance mode (--verify / --repair). Skips
        all network setup so credentials aren't required. Any code path that
        tries to make an HTTP call in this mode will raise AttributeError,
        which is the correct loud failure.
        """
        if online:
            self.auth = OAuth1(API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_SECRET)
            self.session = _build_session(self.auth)
        else:
            self.auth = None
            self.session = None

        # Resolve DATA_DIR once so we can validate every output path stays under it.
        self.data_root = Path(DATA_DIR).resolve()
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.db_path = str(self.data_root / "sync_state.db")
        self._init_db()
        # Run-wide totals for the final summary.
        self.totals = {
            'albums': 0,
            RESULT_DOWNLOADED: 0,
            RESULT_SKIPPED: 0,
            RESULT_MISMATCH: 0,
            RESULT_FAILED: 0,
        }

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS photos
                           (image_key TEXT PRIMARY KEY, md5 TEXT, path TEXT)''')

    def _cleanup_part_files(self):
        """Remove orphaned `.part` files left behind by a previous interrupted run.

        Our download path writes to `<final>.part` and only renames once MD5
        verifies, so any leftover .part file is by definition incomplete and
        safe to delete. Doing this at startup keeps the data dir tidy and
        prevents disk usage growing every time the sync is killed mid-flight.
        """
        try:
            parts = list(self.data_root.rglob('*.part'))
        except OSError as e:
            print(f"  Note: could not scan for orphan .part files: {e}")
            return

        if not parts:
            return

        removed = 0
        bytes_freed = 0
        for p in parts:
            try:
                size = p.stat().st_size
                p.unlink()
                removed += 1
                bytes_freed += size
            except OSError:
                # File vanished or permission denied; not worth aborting over.
                pass

        if removed:
            mb = bytes_freed / (1024 * 1024)
            print(f"Cleaned up {removed} orphan .part file(s) ({mb:.1f} MB) from a previous run.")

    def get_json(self, url):
        headers = {'Accept': 'application/json'}
        r = self.session.get(url, headers=headers, timeout=HTTP_TIMEOUT)
        if r.status_code != 200:
            print(f"HTTP {r.status_code} from {url}")
            print(f"Response body (first 500 chars): {r.text[:500]}")
            r.raise_for_status()
        try:
            return r.json().get('Response', {})
        except ValueError:
            print(f"Non-JSON response from {url}")
            print(f"Body (first 500 chars): {r.text[:500]}")
            raise

    def get_md5(self, filepath):
        hash_md5 = hashlib.md5()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    def download_image(self, image_data, album_path):
        """Download one image. Returns one of the RESULT_* codes."""
        if _cancel.is_set():
            return RESULT_FAILED

        ikey = image_data['ImageKey']
        fname = image_data['FileName']
        url = image_data['ArchivedUri']
        remote_md5 = image_data['ArchivedMD5']
        local_path = os.path.join(album_path, fname)

        # Defense in depth: even after _safe_name, refuse to write outside DATA_DIR.
        if not _is_within(self.data_root, local_path):
            print(f"  ! Refusing to write outside data dir: {local_path}")
            return RESULT_FAILED

        # Already verified on a previous run? Skip.
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT md5 FROM photos WHERE image_key=?", (ikey,)).fetchone()
            if row and os.path.exists(local_path) and row[0] == remote_md5:
                return RESULT_SKIPPED

        os.makedirs(album_path, exist_ok=True)

        # Write to a temp file and rename on success so a partial download never
        # presents itself as the real file.
        tmp_path = local_path + '.part'
        try:
            # Sign download requests too. Private albums require OAuth on
            # ArchivedUri or SmugMug returns an HTML login page instead of the image.
            r = self.session.get(url, stream=True, timeout=HTTP_TIMEOUT)
            r.raise_for_status()

            # Defense in depth: SmugMug should be returning binary image data.
            # If we somehow got HTML (e.g. an unsigned redirect to a login page)
            # treat it as a failure rather than saving garbage.
            ctype = r.headers.get('Content-Type', '').lower()
            if ctype.startswith('text/html'):
                print(f"  ! Unexpected HTML response for {fname} (Content-Type={ctype})")
                return RESULT_FAILED

            with open(tmp_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if _cancel.is_set():
                        f.close()
                        self._remove_quietly(tmp_path)
                        return RESULT_FAILED
                    if chunk:
                        f.write(chunk)

            local_md5 = self.get_md5(tmp_path)
            if local_md5 != remote_md5:
                print(f"  ! MD5 mismatch on {fname} (got {local_md5}, expected {remote_md5})")
                self._remove_quietly(tmp_path)
                return RESULT_MISMATCH

            os.replace(tmp_path, local_path)

            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO photos VALUES (?, ?, ?)",
                    (ikey, local_md5, local_path),
                )
            return RESULT_DOWNLOADED
        except Exception as e:
            print(f"  ! Error downloading {fname}: {e}")
            self._remove_quietly(tmp_path)
            return RESULT_FAILED

    @staticmethod
    def _remove_quietly(path):
        try:
            os.remove(path)
        except OSError:
            pass

    def _fetch_all_album_images(self, album_url):
        """Return every image in an album, following SmugMug's pagination."""
        images = []
        next_path = f"{album_url}!images"
        while next_path:
            page = self.get_json(_api_url(next_path))
            images.extend(page.get('AlbumImage', []) or [])
            next_path = page.get('Pages', {}).get('NextPage')
        return images

    @staticmethod
    def _prepare_filenames(images):
        """Sanitize and disambiguate the FileName for every image in an album.

        Two problems handled here:
          1. SmugMug filenames may contain characters that are illegal on
             Windows (`<>:"|?*`), path separators, or reserved device names.
             _safe_name() takes care of those.
          2. SmugMug allows two images in the same album whose names differ
             only in case (e.g. DSC_0967.jpg vs DSC_0967.JPG). On Windows
             NTFS / default macOS APFS those map to the same on-disk path
             and the parallel downloads race and corrupt each other. We
             append _<ImageKey> before the extension to disambiguate.

        Sort by ImageKey first so the chosen "winner" keeps a stable filename
        across runs.
        """
        seen = {}
        renamed = []
        for img in sorted(images, key=lambda i: i.get('ImageKey', '')):
            original = img.get('FileName') or f"image_{img.get('ImageKey', 'unknown')}"
            safe = _safe_name(original, fallback=f"image_{img.get('ImageKey', 'unknown')}")
            lower = safe.lower()
            if lower in seen:
                base, ext = os.path.splitext(safe)
                safe = f"{base}_{img['ImageKey']}{ext}"
                renamed.append((original, safe))
            seen[lower] = True
            img['FileName'] = safe
        if renamed:
            print(f"  Note: renamed {len(renamed)} file(s) to avoid case-insensitive collisions:")
            for old, new in renamed:
                print(f"    {old} -> {new}")
        return images

    def process_album(self, album_url, path, display_path):
        images = self._fetch_all_album_images(album_url)
        images = self._prepare_filenames(images)
        total = len(images)
        self.totals['albums'] += 1

        print(f"\n[Album] {display_path}  ({total} photo{'s' if total != 1 else ''})")
        if total == 0:
            return

        counts = {
            RESULT_DOWNLOADED: 0,
            RESULT_SKIPPED: 0,
            RESULT_MISMATCH: 0,
            RESULT_FAILED: 0,
        }

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_name = {
                executor.submit(self.download_image, img, path): img.get('FileName', '?')
                for img in images
            }
            done = 0
            try:
                for future in concurrent.futures.as_completed(future_to_name):
                    fname = future_to_name[future]
                    try:
                        result = future.result()
                    except Exception as e:
                        print(f"  ! Unexpected error on {fname}: {e}")
                        result = RESULT_FAILED
                    counts[result] += 1
                    done += 1
                    if result == RESULT_DOWNLOADED:
                        print(f"  [{done}/{total}] downloaded {fname}")
                    if _cancel.is_set():
                        # Stop accepting new completions; cancel queued futures.
                        for f in future_to_name:
                            f.cancel()
                        break
            finally:
                # cancel_futures stops queued tasks immediately. Already-running
                # downloads check _cancel each chunk and exit fast.
                executor.shutdown(wait=True, cancel_futures=True)

        for k in counts:
            self.totals[k] += counts[k]

        # Per-album one-line summary.
        print(
            f"  -> new {counts[RESULT_DOWNLOADED]}, "
            f"skipped {counts[RESULT_SKIPPED]}, "
            f"mismatch {counts[RESULT_MISMATCH]}, "
            f"failed {counts[RESULT_FAILED]}"
        )

    def walk_nodes(self, node_url, current_path, display_path=""):
        if _cancel.is_set():
            return
        # Walk pagination at this level too. SmugMug paginates !children just
        # like !images, and a folder with > 100 nodes would otherwise be cut off.
        next_path = f"{node_url}!children?_expand=Album"
        while next_path and not _cancel.is_set():
            try:
                data = self.get_json(_api_url(next_path))
            except requests.HTTPError as e:
                # One bad subtree shouldn't abort the whole sync.
                print(f"  ! Skipping subtree {display_path or '/'}: {e}")
                return
            for node in data.get('Node', []):
                if _cancel.is_set():
                    return
                raw_name = node.get('Name') or 'unnamed'
                safe = _safe_name(raw_name)
                new_local = os.path.join(current_path, safe)
                if not _is_within(self.data_root, new_local):
                    print(f"  ! Skipping '{raw_name}': resolved path escapes data dir")
                    continue
                new_display = f"{display_path}/{safe}" if display_path else safe

                node_type = node.get('Type')
                if node_type == 'Album':
                    album_uri = node.get('Uris', {}).get('Album', {}).get('Uri')
                    if not album_uri:
                        print(f"Skipping album '{new_display}': no Album URI on node {node.get('Uri')}")
                        continue
                    try:
                        self.process_album(album_uri, new_local, new_display)
                    except requests.HTTPError as e:
                        print(f"  ! Skipping album '{new_display}': {e}")
                elif node_type == 'Folder':
                    print(f"\n[Folder] {new_display}")
                    self.walk_nodes(node.get('Uri'), new_local, new_display)
                # Other node types (e.g. SmartAlbum, Page) are intentionally
                # ignored: no archive download applies.
            next_path = data.get('Pages', {}).get('NextPage')

    def run(self):
        # Step 1: fetch the user object. Its Uris map contains the root node URI.
        user_resp = self.get_json(_api_url(f"/user/{NICKNAME}"))
        try:
            node_uri = user_resp['User']['Uris']['Node']['Uri']
        except (KeyError, TypeError):
            print("Error: Could not find user root node. Check your NICKNAME and API keys.")
            print(f"User response: {user_resp}")
            return

        print(f"Starting sync for '{NICKNAME}' into {DATA_DIR}")
        self._cleanup_part_files()
        self.walk_nodes(node_uri, DATA_DIR)

        t = self.totals
        print("\n=== Sync complete ===")
        print(f"Albums processed : {t['albums']}")
        print(f"New downloads    : {t[RESULT_DOWNLOADED]}")
        print(f"Already in sync  : {t[RESULT_SKIPPED]}")
        print(f"MD5 mismatches   : {t[RESULT_MISMATCH]}")
        print(f"Failed           : {t[RESULT_FAILED]}")

    def verify(self, repair=False):
        """Re-hash every file recorded in the DB and compare against the stored MD5.

        This is offline: it does NOT contact SmugMug. It only confirms that the
        files on disk still match the hashes we computed when we downloaded them.
        Use it for periodic bit-rot checks on the NAS.

        With repair=True, mismatched and missing entries are removed from the DB
        so the next normal sync will re-download them. The corrupted files on
        disk are also deleted so a future sync starts clean.

        Returns True if everything is healthy, False otherwise.
        """
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT image_key, md5, path FROM photos"
            ).fetchall()

        total = len(rows)
        if total == 0:
            print("Nothing to verify: the sync state DB is empty.")
            return True

        print(f"Verifying {total} files recorded in {self.db_path}")
        if repair:
            print("Repair mode ON: bad/missing files will be deleted and dropped from the DB.")
        else:
            print("Repair mode OFF: this is a read-only check. Re-run with --repair to fix.")

        ok = 0
        missing = []          # file is gone from disk
        mismatch = []         # file present, hash differs
        unreadable = []       # IO error reading the file
        outside = []          # DB path is outside the configured DATA_DIR

        for i, (ikey, expected_md5, stored_path) in enumerate(rows, 1):
            if _cancel.is_set():
                print("Cancellation requested, stopping verification.")
                break

            if i % 100 == 0 or i == total:
                print(f"  ...checked {i}/{total}")

            # Sanity: never verify a file outside the data root, even if the DB
            # somehow points elsewhere.
            if not _is_within(self.data_root, stored_path):
                outside.append((ikey, stored_path))
                continue

            if not os.path.exists(stored_path):
                missing.append((ikey, stored_path))
                continue

            try:
                actual_md5 = self.get_md5(stored_path)
            except OSError as e:
                unreadable.append((ikey, stored_path, str(e)))
                continue

            if actual_md5 == expected_md5:
                ok += 1
            else:
                mismatch.append((ikey, stored_path, expected_md5, actual_md5))

        print("\n=== Verification complete ===")
        print(f"Total checked    : {ok + len(missing) + len(mismatch) + len(unreadable) + len(outside)} / {total}")
        print(f"OK               : {ok}")
        print(f"Missing on disk  : {len(missing)}")
        print(f"MD5 mismatches   : {len(mismatch)}")
        print(f"Unreadable       : {len(unreadable)}")
        print(f"Outside data dir : {len(outside)}")

        if mismatch:
            print("\nFirst 10 mismatches:")
            for ikey, path, exp, got in mismatch[:10]:
                print(f"  {path}\n    expected {exp}, got {got}")

        if missing:
            print("\nFirst 10 missing:")
            for ikey, path in missing[:10]:
                print(f"  {path}")

        if unreadable:
            print("\nFirst 10 unreadable:")
            for ikey, path, err in unreadable[:10]:
                print(f"  {path}: {err}")

        bad_keys = (
            [k for k, _ in missing]
            + [k for k, _, _, _ in mismatch]
            + [k for k, _, _ in unreadable]
            + [k for k, _ in outside]
        )

        if repair and bad_keys:
            # Delete the corrupt files first so a partial run leaves the DB
            # consistent with what's on disk if interrupted.
            for _, path, *_ in mismatch:
                self._remove_quietly(path)
            with sqlite3.connect(self.db_path) as conn:
                conn.executemany(
                    "DELETE FROM photos WHERE image_key=?",
                    [(k,) for k in bad_keys],
                )
            print(
                f"\nRepaired DB: dropped {len(bad_keys)} bad/missing entries. "
                "Run a normal sync to re-download them."
            )

        return not bad_keys


def _parse_args():
    """Parse CLI args. The script is normally run with no flags from Docker;
    --verify and --repair are for ad-hoc maintenance from the host.
    """
    p = argparse.ArgumentParser(
        prog='sync.py',
        description='SmugMug Docker sync. With no args, performs a full sync.',
    )
    p.add_argument(
        '--verify',
        action='store_true',
        help='Re-hash every file in the DB against its stored MD5 (offline). '
             'Does not contact SmugMug.',
    )
    p.add_argument(
        '--repair',
        action='store_true',
        help='With --verify, also delete bad files and drop their DB entries '
             'so the next sync re-downloads them. Implies --verify.',
    )
    args = p.parse_args()
    if args.repair:
        args.verify = True
    return args


if __name__ == "__main__":
    args = _parse_args()
    _install_signal_handlers()

    if args.verify:
        # Verify mode is offline, so credentials aren't required.
        sync = SmugMugSync(online=False)
        ok = sync.verify(repair=args.repair)
        sys.exit(0 if ok else 1)

    _check_env()
    SmugMugSync().run()
