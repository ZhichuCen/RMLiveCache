#!/usr/bin/python3
"""Small HLS cache coordinator for the RoboMaster LAN live service."""

import hashlib
import http.server
import json
import os
import re
import shutil
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


CONFIG_PATH = os.environ.get("RM_LIVE_CACHE_CONFIG", "/etc/rm-live-cache/config.json")
SOURCE_URL = "https://rm-static.djicdn.com/live_json/live_game_info.json"
UPSTREAM_ORIGIN = "https://rtmp.djicdn.com"
USER_AGENT = "RMLiveCache/1.0 (+http://rm.lan/)"

with open(CONFIG_PATH, "r", encoding="utf-8") as config_file:
    CONFIG = json.load(config_file)

CACHE_DIR = CONFIG["cache_dir"]
CACHE_MAX_BYTES = int(CONFIG["cache_max_bytes"])
SEGMENT_TTL = float(CONFIG["segment_ttl_seconds"])
PLAYLIST_TTL = float(CONFIG["playlist_ttl_seconds"])
SOURCE_TTL = float(CONFIG["source_ttl_seconds"])
UPSTREAM_TIMEOUT = float(CONFIG["upstream_timeout_seconds"])
TARGET_SOURCE_RESOLUTION = str(CONFIG.get("source_resolution", "middle")).lower()
TARGET_SOURCE_LABEL = str(CONFIG.get("source_label", "720p"))

os.makedirs(CACHE_DIR, exist_ok=True)
threading.stack_size(256 * 1024)

STATE_LOCK = threading.RLock()
INFLIGHT = {}
PLAYLIST_CACHE = {}
STARTED_AT = time.time()
SOURCE = {
    "url": None,
    "checked_at": 0.0,
    "label": "",
    "active": False,
    "error": None,
}
STATS = {
    "cache_hits": 0,
    "cache_misses": 0,
    "coalesced_requests": 0,
    "upstream_bytes": 0,
    "client_bytes": 0,
    "errors": 0,
}


def now():
    return time.time()


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def upstream_request(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Connection": "close",
        },
    )
    return urllib.request.urlopen(
        request,
        timeout=UPSTREAM_TIMEOUT,
        context=ssl.create_default_context(),
    )


def select_source(payload):
    events = payload.get("eventData") or []
    ranked_events = sorted(
        events,
        key=lambda event: (
            int(
                str(event.get("liveState", 0)) == "1"
                and str(event.get("matchState", 0)) == "1"
            ),
            int(str(event.get("matchState", 0)) == "1"),
            int(str(event.get("liveState", 0)) == "1"),
        ),
        reverse=True,
    )
    for event in ranked_events:
        sources = event.get("zoneLiveString") or []
        preferred = [
            source
            for source in sources
            if str(source.get("res", "")).lower() == TARGET_SOURCE_RESOLUTION
            and str(source.get("label", "")).lower() == TARGET_SOURCE_LABEL.lower()
        ]
        for source in preferred:
            value = source.get("src") or ""
            parsed = urllib.parse.urlsplit(value)
            if (
                parsed.scheme == "https"
                and parsed.hostname == "rtmp.djicdn.com"
                and parsed.path.startswith("/robomaster/")
                and parsed.path.endswith(".m3u8")
            ):
                label = " · ".join(
                    part
                    for part in (
                        payload.get("eventName"),
                        event.get("zoneName"),
                        source.get("label") or TARGET_SOURCE_LABEL,
                    )
                    if part
                )
                active = (
                    str(event.get("liveState", 0)) == "1"
                    and str(event.get("matchState", 0)) == "1"
                )
                return value, label, active
    raise ValueError(
        "official JSON does not contain a valid %s main stream" % TARGET_SOURCE_LABEL
    )


def discover_source(force=False):
    current_time = now()
    with STATE_LOCK:
        if (
            not force
            and SOURCE["url"]
            and current_time - SOURCE["checked_at"] < SOURCE_TTL
        ):
            return SOURCE["url"], SOURCE["label"]
        last_url = SOURCE["url"]
        last_label = SOURCE["label"]

    try:
        with upstream_request(SOURCE_URL) as response:
            payload = json.loads(response.read().decode("utf-8"))
        source_url, label, active = select_source(payload)
        with STATE_LOCK:
            SOURCE.update(
                {
                    "url": source_url,
                    "label": label,
                    "active": active,
                    "checked_at": current_time,
                    "error": None,
                }
            )
        return source_url, label
    except Exception as exc:  # keep a last-known-good stream during short API failures
        with STATE_LOCK:
            SOURCE["checked_at"] = current_time
            SOURCE["error"] = str(exc)
            STATS["errors"] += 1
        if last_url:
            return last_url, last_label
        raise


def localize_source(source_url):
    parsed = urllib.parse.urlsplit(source_url)
    path = "/hls" + parsed.path
    if parsed.query:
        path += "?" + parsed.query
    return path


def localize_playlist_uri(uri, upstream_url):
    """Keep every HLS child request on the LAN cache origin."""
    parsed = urllib.parse.urlsplit(urllib.parse.urljoin(upstream_url, uri))
    if (
        parsed.scheme != "https"
        or parsed.hostname != "rtmp.djicdn.com"
        or not parsed.path.startswith("/robomaster/")
    ):
        return uri
    local = "/hls" + parsed.path
    if parsed.query:
        local += "?" + parsed.query
    return local


def localize_playlist(body, upstream_url):
    """Rewrite media lines and URI attributes, including nested playlists."""
    text = body.decode("utf-8-sig")
    rewritten = []
    uri_attribute = re.compile(r'URI=("([^"]+)"|([^,\r\n]+))')

    for line in text.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        ending = line[len(content) :]
        stripped = content.strip()
        if stripped and not stripped.startswith("#"):
            prefix = content[: len(content) - len(content.lstrip())]
            suffix = content[len(content.rstrip()) :]
            content = prefix + localize_playlist_uri(stripped, upstream_url) + suffix
        elif "URI=" in content:
            def replace_uri(match):
                quoted = match.group(2) is not None
                value = match.group(2) if quoted else match.group(3)
                local = localize_playlist_uri(value, upstream_url)
                return 'URI="%s"' % local if quoted else "URI=" + local

            content = uri_attribute.sub(replace_uri, content)
        rewritten.append(content + ending)

    return "".join(rewritten).encode("utf-8")


def cache_filename(cache_key, suffix):
    digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()
    clean_suffix = suffix if suffix in (".ts", ".aac", ".m4s", ".mp4") else ".bin"
    return os.path.join(CACHE_DIR, digest + clean_suffix)


def cache_snapshot():
    entries = []
    total = 0
    try:
        for name in os.listdir(CACHE_DIR):
            if name.startswith(".") or name.endswith(".tmp"):
                continue
            path = os.path.join(CACHE_DIR, name)
            try:
                stat = os.stat(path)
            except OSError:
                continue
            if not os.path.isfile(path):
                continue
            total += stat.st_size
            entries.append((stat.st_mtime, stat.st_size, path))
    except OSError:
        pass
    return total, entries


def prune_cache():
    total, entries = cache_snapshot()
    if total <= CACHE_MAX_BYTES:
        return total
    target = int(CACHE_MAX_BYTES * 0.82)
    for _, size, path in sorted(entries):
        try:
            os.unlink(path)
            total -= size
        except OSError:
            pass
        if total <= target:
            break
    return total


def content_type_for(path, upstream_type=None):
    if upstream_type:
        return upstream_type.split(";", 1)[0]
    if path.endswith(".m3u8"):
        return "application/vnd.apple.mpegurl"
    if path.endswith(".ts"):
        return "video/mp2t"
    if path.endswith(".aac"):
        return "audio/aac"
    if path.endswith(".m4s"):
        return "video/iso.segment"
    if path.endswith(".mp4"):
        return "video/mp4"
    return "application/octet-stream"


def fetch_bytes(url):
    with upstream_request(url) as response:
        body = response.read()
        return response.status, response.headers.get("Content-Type"), body


def get_playlist(cache_key, upstream_url):
    current_time = now()
    with STATE_LOCK:
        cached = PLAYLIST_CACHE.get(cache_key)
        if cached and current_time - cached[0] <= PLAYLIST_TTL:
            STATS["cache_hits"] += 1
            STATS["client_bytes"] += len(cached[2])
            return cached[1], cached[2], "HIT"
        event = INFLIGHT.get(cache_key)
        if event is None:
            event = threading.Event()
            INFLIGHT[cache_key] = event
            leader = True
        else:
            STATS["coalesced_requests"] += 1
            leader = False

    if not leader:
        event.wait(UPSTREAM_TIMEOUT + 2)
        with STATE_LOCK:
            cached = PLAYLIST_CACHE.get(cache_key)
            if cached:
                STATS["cache_hits"] += 1
                STATS["client_bytes"] += len(cached[2])
                return cached[1], cached[2], "COALESCED"
        raise RuntimeError("playlist coalescing timed out")

    try:
        status, content_type, body = fetch_bytes(upstream_url)
        if status != 200:
            raise RuntimeError("upstream playlist returned status %s" % status)
        body = localize_playlist(body, upstream_url)
        with STATE_LOCK:
            PLAYLIST_CACHE[cache_key] = (now(), content_type_for(".m3u8", content_type), body)
            STATS["cache_misses"] += 1
            STATS["upstream_bytes"] += len(body)
            STATS["client_bytes"] += len(body)
        return content_type_for(".m3u8", content_type), body, "MISS"
    finally:
        with STATE_LOCK:
            INFLIGHT.pop(cache_key, None)
            event.set()


def get_segment(cache_key, upstream_url, request_path):
    suffix = os.path.splitext(urllib.parse.urlsplit(request_path).path)[1].lower()
    target = cache_filename(cache_key, suffix)
    try:
        stat = os.stat(target)
        if now() - stat.st_mtime <= SEGMENT_TTL and stat.st_size > 0:
            with STATE_LOCK:
                STATS["cache_hits"] += 1
                STATS["client_bytes"] += stat.st_size
            return target, stat.st_size, "HIT"
    except OSError:
        pass

    with STATE_LOCK:
        event = INFLIGHT.get(cache_key)
        if event is None:
            event = threading.Event()
            INFLIGHT[cache_key] = event
            leader = True
        else:
            STATS["coalesced_requests"] += 1
            leader = False

    if not leader:
        event.wait(UPSTREAM_TIMEOUT + 3)
        try:
            size = os.path.getsize(target)
            if size > 0:
                with STATE_LOCK:
                    STATS["cache_hits"] += 1
                    STATS["client_bytes"] += size
                return target, size, "COALESCED"
        except OSError:
            pass
        raise RuntimeError("segment coalescing timed out")

    temporary = target + ".%d.tmp" % os.getpid()
    try:
        status, _, body = fetch_bytes(upstream_url)
        if status != 200:
            raise RuntimeError("upstream segment returned status %s" % status)
        with open(temporary, "wb") as output:
            output.write(body)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
        size = len(body)
        with STATE_LOCK:
            STATS["cache_misses"] += 1
            STATS["upstream_bytes"] += size
            STATS["client_bytes"] += size
        prune_cache()
        return target, size, "MISS"
    finally:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        with STATE_LOCK:
            INFLIGHT.pop(cache_key, None)
            event.set()


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "RMLiveCache/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def add_common_headers(self):
        origin = self.headers.get("Origin")
        allowed = (
            origin
            if origin
            in (
                "https://www.robomaster.com",
                "http://rm.lan",
                "http://rm.local",
                "http://192.168.8.2",
            )
            else "*"
        )
        self.send_header("Access-Control-Allow-Origin", allowed)
        self.send_header("Access-Control-Allow-Methods", "GET,HEAD,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Range,Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Timing-Allow-Origin", "*")
        self.send_header("X-Content-Type-Options", "nosniff")

    def send_bytes(self, status, body, content_type, cache_state=None, head_only=False):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if cache_state:
            self.send_header("X-RM-Cache", cache_state)
        self.add_common_headers()
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.add_common_headers()
        self.end_headers()

    def do_HEAD(self):
        self.handle_request(head_only=True)

    def do_GET(self):
        self.handle_request(head_only=False)

    def handle_request(self, head_only=False):
        parsed = urllib.parse.urlsplit(self.path)
        try:
            if parsed.path == "/health":
                source_url, _ = discover_source()
                with STATE_LOCK:
                    live_active = bool(SOURCE["active"])
                body = json_bytes(
                    {"ok": True, "source": bool(source_url), "live_active": live_active}
                )
                self.send_bytes(200, body, "application/json; charset=utf-8", head_only=head_only)
                return

            if parsed.path == "/api/status":
                try:
                    discover_source()
                except Exception:
                    pass
                cache_bytes, entries = cache_snapshot()
                with STATE_LOCK:
                    stats = dict(STATS)
                    source = dict(SOURCE)
                source_url = source.get("url") or ""
                public_source = urllib.parse.urlsplit(source_url).path if source_url else ""
                response = {
                    "ok": bool(source_url),
                    "live_active": bool(source.get("active")),
                    "uptime_seconds": int(now() - STARTED_AT),
                    "source_label": source.get("label") or "等待直播源",
                    "source_path": public_source,
                    "source_error": source.get("error"),
                    "cache_bytes": cache_bytes,
                    "cache_limit_bytes": CACHE_MAX_BYTES,
                    "cache_entries": len(entries),
                    "stats": stats,
                    "estimated_wan_saved_bytes": max(
                        0, stats["client_bytes"] - stats["upstream_bytes"]
                    ),
                }
                self.send_bytes(
                    200,
                    json_bytes(response),
                    "application/json; charset=utf-8",
                    head_only=head_only,
                )
                return

            if parsed.path == "/live.m3u8":
                source_url, _ = discover_source()
                with STATE_LOCK:
                    live_active = bool(SOURCE["active"])
                if not live_active:
                    body = json_bytes({"ok": False, "error": "official live stream is inactive"})
                    self.send_bytes(
                        503,
                        body,
                        "application/json; charset=utf-8",
                        head_only=head_only,
                    )
                    return
                location = localize_source(source_url)
                self.send_response(302)
                self.send_header("Location", location)
                self.send_header("Content-Length", "0")
                self.send_header("Cache-Control", "no-store")
                self.add_common_headers()
                self.end_headers()
                return

            if not parsed.path.startswith("/hls/robomaster/") or ".." in parsed.path:
                self.send_error(404)
                return

            upstream_path = parsed.path[len("/hls") :]
            source_url, _ = discover_source()
            source_path = urllib.parse.urlsplit(source_url).path
            segment_prefix = source_path.rsplit(".", 1)[0] + "/"
            if upstream_path != source_path and not upstream_path.startswith(segment_prefix):
                self.send_error(
                    403,
                    "only the active %s main stream is available" % TARGET_SOURCE_LABEL,
                )
                return
            upstream_url = UPSTREAM_ORIGIN + upstream_path
            if parsed.query:
                upstream_url += "?" + parsed.query

            if parsed.path.endswith(".m3u8"):
                cache_key = parsed.path + "?" + parsed.query
                content_type, body, cache_state = get_playlist(cache_key, upstream_url)
                self.send_bytes(
                    200, body, content_type, cache_state=cache_state, head_only=head_only
                )
                return

            if not parsed.path.endswith((".ts", ".aac", ".m4s", ".mp4")):
                self.send_error(403, "unsupported HLS object")
                return

            cache_key = parsed.path  # signed query strings rotate; segment paths are immutable
            target, size, cache_state = get_segment(cache_key, upstream_url, parsed.path)
            internal_path = "/_rm_live_cache/" + os.path.basename(target)
            self.send_response(200)
            self.send_header("Content-Type", content_type_for(parsed.path))
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "public, max-age=300, immutable")
            self.send_header("X-RM-Cache", cache_state)
            self.send_header("X-Accel-Redirect", internal_path)
            self.add_common_headers()
            self.end_headers()
        except urllib.error.HTTPError as exc:
            with STATE_LOCK:
                STATS["errors"] += 1
            body = json_bytes({"ok": False, "error": "upstream HTTP %s" % exc.code})
            self.send_bytes(502, body, "application/json; charset=utf-8", head_only=head_only)
        except Exception as exc:
            with STATE_LOCK:
                STATS["errors"] += 1
            body = json_bytes({"ok": False, "error": str(exc)})
            self.send_bytes(503, body, "application/json; charset=utf-8", head_only=head_only)


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 128
    allow_reuse_address = True


def main():
    server = Server((CONFIG["listen"], int(CONFIG["port"])), Handler)
    print("rm-live-cache listening on %s:%s" % (CONFIG["listen"], CONFIG["port"]), flush=True)
    server.serve_forever(poll_interval=0.25)


if __name__ == "__main__":
    main()
