"""A local, single-user editorial publishing demonstration. Python 3.12+."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent
MAX_BODY = 65_536
ID = re.compile(r"[a-z][a-z0-9-]{0,39}\Z")
COLLECTIONS = {
    "performers": ("id", "name", "discipline", "bio"),
    "venues": ("id", "name", "access"),
    "entries": ("id", "title", "time", "performer_id", "venue_id", "description"),
}


class Problem(Exception):
    def __init__(self, message, status=400, issues=None):
        super().__init__(message)
        self.status, self.issues = status, issues or []


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def pack(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def no_duplicate_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON key")
        value[key] = item
    return value


def clean_text(value, name, maximum=4000):
    if not isinstance(value, str) or len(value) > maximum:
        raise Problem(f"{name} must be text, at most {maximum} characters.")
    if any(0xD800 <= ord(c) <= 0xDFFF or (ord(c) < 32 and c not in "\n\t") for c in value):
        raise Problem(f"{name} contains unsupported control characters.")
    return value


def shape(content):
    """Enforce storage shape; incomplete editorial fields may still be saved."""
    if not isinstance(content, dict) or set(content) != {"title", "intro", *COLLECTIONS}:
        raise Problem("Content must contain title, intro, performers, venues, and entries.")
    clean_text(content["title"], "Program title", 200)
    clean_text(content["intro"], "Introduction")
    for collection, fields in COLLECTIONS.items():
        rows = content[collection]
        if not isinstance(rows, list) or len(rows) > 100:
            raise Problem(f"{collection} must be a list of at most 100 records.")
        seen = set()
        for row in rows:
            if not isinstance(row, dict) or set(row) != set(fields):
                raise Problem(f"Unexpected fields in {collection}.")
            for field in fields:
                clean_text(row[field], f"{collection}.{field}", 4000 if field in {"bio", "description", "access"} else 200)
            if not ID.fullmatch(row["id"]) or row["id"] in seen:
                raise Problem(f"{collection} IDs must be unique lowercase slugs.")
            seen.add(row["id"])
    if len(pack(content).encode("utf-8")) > 60_000:
        raise Problem("Program content exceeds the 60 KB limit.")


def validate(content):
    shape(content)
    issues = []
    def missing(value, path):
        if not value.strip():
            issues.append({"path": path, "message": "Required text is missing."})
    missing(content["title"], "title")
    missing(content["intro"], "intro")
    for collection, fields in COLLECTIONS.items():
        if not content[collection]:
            issues.append({"path": collection, "message": "At least one record is required."})
        for row in content[collection]:
            for field in fields:
                missing(row[field], f"{collection}/{row['id']}/{field}")
    performers = {p["id"] for p in content["performers"]}
    venues = {v["id"] for v in content["venues"]}
    for entry in content["entries"]:
        for field, targets in (("performer_id", performers), ("venue_id", venues)):
            if entry[field] not in targets:
                issues.append({"path": f"entries/{entry['id']}/{field}", "message": "The linked record does not exist."})
    return issues


def seed_content():
    return {
        "title": "Lumenfold Arts Gathering",
        "intro": "An imagined afternoon of sound, paper, movement, and shared making. All people, places, and events in this program are fictional.",
        "performers": [
            {"id": "vesper-reed", "name": "Vesper Reed", "discipline": "Paper sculpture", "bio": "Vesper builds small moving worlds from folded paper, inviting audiences to finish each scene."},
            {"id": "tala-morrow", "name": "Tala Morrow", "discipline": "Percussion and storytelling", "bio": "Tala pairs soft percussion with stories about imaginary coastlines and the objects left there."},
            {"id": "threadline-ensemble", "name": "Threadline Ensemble", "discipline": "Movement", "bio": "A fictional movement collective exploring the space between everyday gestures."},
        ],
        "venues": [
            {"id": "lantern-court", "name": "Lantern Court", "access": "Step-free open courtyard. Seating available along the north edge."},
            {"id": "paper-hall", "name": "Paper Hall", "access": "Level entrance, quiet seating area, and wide aisles."},
        ],
        "entries": [
            {"id": "a-pocket-of-light", "title": "A Pocket of Light", "time": "13:00–13:45", "performer_id": "vesper-reed", "venue_id": "paper-hall", "description": "Fold a tiny landscape, then change its shadows with a handheld lantern. Materials supplied."},
            {"id": "tide-without-water", "title": "Tide Without Water", "time": "14:00–14:40", "performer_id": "tala-morrow", "venue_id": "lantern-court", "description": "An acoustic story built from small rhythms and an imaginary shoreline."},
            {"id": "between-the-steps", "title": "Between the Steps", "time": "15:00–15:30", "performer_id": "threadline-ensemble", "venue_id": "lantern-court", "description": "Three performers turn familiar gestures into a gentle moving conversation."},
        ],
    }


class Store:
    def __init__(self, path):
        self.path = str(path)

    @contextmanager
    def connection(self, write=False):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def seed(self):
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS revisions (
                    version INTEGER PRIMARY KEY, content TEXT NOT NULL,
                    note TEXT NOT NULL, saved_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS workflow (
                    id INTEGER PRIMARY KEY CHECK(id=1), reviewed_version INTEGER);
                CREATE TABLE IF NOT EXISTS publications (
                    edition INTEGER PRIMARY KEY, version INTEGER NOT NULL UNIQUE,
                    content TEXT NOT NULL, published_at TEXT NOT NULL,
                    FOREIGN KEY(version) REFERENCES revisions(version));
                INSERT OR IGNORE INTO workflow(id, reviewed_version) VALUES(1, NULL);
            """)
            if not db.execute("SELECT 1 FROM revisions LIMIT 1").fetchone():
                db.execute("INSERT INTO revisions VALUES(1, ?, ?, ?)", (pack(seed_content()), "Initial fictional program", now()))

    @staticmethod
    def latest(db, version=None):
        row = db.execute("SELECT * FROM revisions ORDER BY version DESC LIMIT 1").fetchone()
        if version is not None and (type(version) is not int or version != row["version"]):
            raise Problem("This draft changed. Reload the latest revision before trying again.", 409)
        return row

    def state(self):
        with self.connection() as db:
            db.execute("BEGIN")
            row = self.latest(db)
            content = json.loads(row["content"])
            publication = db.execute("SELECT edition, version, published_at FROM publications ORDER BY edition DESC LIMIT 1").fetchone()
            return {"version": row["version"], "content": content, "issues": validate(content),
                    "reviewed_version": db.execute("SELECT reviewed_version FROM workflow").fetchone()[0],
                    "published": dict(publication) if publication else None,
                    "history": [dict(r) for r in db.execute("SELECT version, note, saved_at FROM revisions ORDER BY version DESC LIMIT 20")]}

    def save(self, version, content, note):
        shape(content)
        clean_text(note, "Revision note", 200)
        with self.connection(True) as db:
            row = self.latest(db, version)
            db.execute("INSERT INTO revisions VALUES(?, ?, ?, ?)", (row["version"] + 1, pack(content), note.strip() or "Editorial update", now()))
            db.execute("UPDATE workflow SET reviewed_version=NULL WHERE id=1")

    def review(self, version):
        with self.connection(True) as db:
            row = self.latest(db, version)
            issues = validate(json.loads(row["content"]))
            if issues:
                raise Problem("Repair the validation issues before marking this revision reviewed.", 422, issues)
            db.execute("UPDATE workflow SET reviewed_version=? WHERE id=1", (version,))

    def publish(self, version):
        with self.connection(True) as db:
            row = self.latest(db, version)
            issues = validate(json.loads(row["content"]))
            if issues:
                raise Problem("Publication blocked by validation issues.", 422, issues)
            if db.execute("SELECT reviewed_version FROM workflow").fetchone()[0] != version:
                raise Problem("Preview and mark this exact revision reviewed before publishing.", 409)
            existing = db.execute("SELECT edition FROM publications WHERE version=?", (version,)).fetchone()
            if existing:
                return existing[0]
            cursor = db.execute("INSERT INTO publications(version, content, published_at) VALUES(?, ?, ?)", (version, row["content"], now()))
            return cursor.lastrowid

    def publication(self, edition=None):
        with self.connection() as db:
            if edition is None:
                row = db.execute("SELECT * FROM publications ORDER BY edition DESC LIMIT 1").fetchone()
            else:
                row = db.execute("SELECT * FROM publications WHERE edition=?", (edition,)).fetchone()
            if not row:
                raise Problem("No published edition exists here yet.", 404)
            return dict(row) | {"content": json.loads(row["content"])}

    def revision(self, version):
        with self.connection() as db:
            row = db.execute("SELECT content FROM revisions WHERE version=?", (version,)).fetchone()
            if not row:
                raise Problem("Revision not found.", 404)
            return json.loads(row[0])


PROGRAM_CSS = """
:root{color-scheme:light;font-family:Georgia,serif;color:#272c26;background:#f7f5ee}
*{box-sizing:border-box}body{max-width:900px;margin:auto;padding:3rem 1.5rem;line-height:1.65}
h1{font-size:2.6rem;line-height:1.15}h2{margin-top:3rem;border-bottom:1px solid #c3c8ba;padding-bottom:.5rem}
h3{margin-bottom:.4rem}a{color:#365d36;text-underline-offset:.2em}a:focus-visible{outline:3px solid #765500;outline-offset:3px}
article{padding:1rem 0;border-bottom:1px solid #d4d6ce;scroll-margin-top:1rem}article:target{background:#e4ebd9;outline:2px solid #365d36;padding:1rem}
.meta,nav,.edition{font-family:system-ui,sans-serif;font-size:.9rem}.edition{color:#545d50}nav{display:flex;gap:1.5rem;flex-wrap:wrap}
p{max-width:70ch;white-space:pre-line}h1,h3,p,a{overflow-wrap:anywhere}@media print{body{padding:0}a{color:inherit}article{break-inside:avoid}}
"""


def render_program(content, label):
    e = escape
    performers = {p["id"]: p for p in content["performers"]}
    venues = {v["id"]: v for v in content["venues"]}
    parts = [f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(content["title"])}</title><style>{PROGRAM_CSS}</style></head><body>',
             f'<header><h1>{e(content["title"])}</h1><p class="edition">{e(label)} · Fictional demonstration</p><p>{e(content["intro"])}</p></header>',
             '<nav aria-label="Program sections"><a href="#program">Program</a><a href="#performers">Performers</a><a href="#venues">Venues</a></nav><main><section id="program"><h2>Program</h2>']
    for entry in content["entries"]:
        def entity_link(collection, key, noun):
            target = collection.get(entry[key])
            return f'<a href="#{noun}-{e(target["id"])}">{e(target["name"])}</a>' if target else f'Unresolved {noun}'
        parts.append(f'<article id="entry-{e(entry["id"])}"><p class="meta">{e(entry["time"])}</p><h3>{e(entry["title"])}</h3><p class="meta">{entity_link(performers, "performer_id", "performer")} · {entity_link(venues, "venue_id", "venue")}</p><p>{e(entry["description"])}</p></article>')
    parts.append('</section><section id="performers"><h2>Performers</h2>')
    for performer in content["performers"]:
        parts.append(f'<article id="performer-{e(performer["id"])}"><h3>{e(performer["name"])}</h3><p class="meta">{e(performer["discipline"])}</p><p>{e(performer["bio"])}</p></article>')
    parts.append('</section><section id="venues"><h2>Venues</h2>')
    for venue in content["venues"]:
        parts.append(f'<article id="venue-{e(venue["id"])}"><h3>{e(venue["name"])}</h3><p>{e(venue["access"])}</p></article>')
    parts.append('</section></main><footer><p class="edition">All program content is invented for this local software demonstration.</p></footer></body></html>')
    return "".join(parts)


def search(publication, query):
    content, edition = publication["content"], publication["edition"]
    results = []
    if not query.strip():
        return results
    needle = query.casefold().strip()
    for collection, kind in (("entries", "entry"), ("performers", "performer"), ("venues", "venue")):
        for row in content[collection]:
            if needle in " ".join(row.values()).casefold():
                results.append({"kind": kind, "title": row.get("title", row.get("name")), "href": f'/program?edition={edition}#{kind}-{row["id"]}'})
    return results


class Server(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, port, store):
        super().__init__(("127.0.0.1", port), Handler)
        self.store = store
        self.origin = f"http://127.0.0.1:{self.server_port}"


class Handler(BaseHTTPRequestHandler):
    server_version = "PublicationWorkbench/1"
    sys_version = ""

    def log_message(self, format, *args):
        # Request paths can contain user content; keep local logs content-free.
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(4)

    def reply(self, status, body, content_type="application/json; charset=utf-8", attachment=False):
        if isinstance(body, (dict, list)):
            body = pack(body)
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.send_header("Connection", "close")
        if attachment:
            self.send_header("Content-Disposition", 'attachment; filename="fictional-program.html"')
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def guards(self):
        names = [name.lower() for name in self.headers.keys()]
        if len(names) != len(set(names)):
            raise Problem("Duplicate request headers are not accepted.")
        if self.headers.get("Host") != self.server.origin.removeprefix("http://"):
            raise Problem("Unrecognized Host header.", 403)
        origin = self.headers.get("Origin")
        if origin and origin != self.server.origin:
            raise Problem("Cross-origin requests are not accepted.", 403)
        if self.command == "POST" and origin != self.server.origin:
            raise Problem("A same-origin Origin header is required.", 403)
        if "Transfer-Encoding" in self.headers:
            raise Problem("Transfer encoding is not supported.")
        if len(self.path) > 2048 or not self.path.startswith("/") or self.path.startswith("//"):
            raise Problem("Invalid request target.")

    def read_body(self):
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,8}", lengths[0]):
            raise Problem("One valid Content-Length is required.")
        length = int(lengths[0])
        # A bounded drain makes rejected ordinary POSTs reliable on Windows.
        body = self.rfile.read(min(length, MAX_BODY + 1))
        if length > MAX_BODY:
            raise Problem("Request body exceeds 64 KB.", 413)
        if len(body) != length:
            raise Problem("Incomplete request body.")
        return body

    def route(self):
        body = self.read_body() if self.command == "POST" else None
        self.guards()
        parsed = urlsplit(self.path)
        params = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=8)
        if any(len(values) != 1 for values in params.values()):
            raise Problem("Duplicate query fields are not accepted.")
        def number(key):
            value = params.get(key, [None])[0]
            if value is not None and not re.fullmatch(r"[1-9][0-9]{0,8}", value):
                raise Problem(f"Invalid {key}.")
            return int(value) if value else None
        store = self.server.store
        if self.command == "GET":
            static = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"), "/style.css": ("style.css", "text/css")}
            if parsed.path in static:
                file, mime = static[parsed.path]
                return self.reply(200, (ROOT / "static" / file).read_bytes(), mime + "; charset=utf-8")
            if parsed.path == "/api/state":
                return self.reply(200, store.state())
            if parsed.path == "/preview":
                version = number("version")
                if version is None:
                    raise Problem("A revision is required for preview.")
                return self.reply(200, render_program(store.revision(version), f"Draft revision {version} — not published"), "text/html; charset=utf-8")
            if parsed.path in {"/program", "/export", "/api/search"}:
                publication = store.publication(number("edition"))
                if parsed.path == "/api/search":
                    query = clean_text(params.get("q", [""])[0], "Search", 100)
                    return self.reply(200, {"edition": publication["edition"], "results": search(publication, query)})
                html = render_program(publication["content"], f'Published edition {publication["edition"]} · revision {publication["version"]}')
                return self.reply(200, html, "text/html; charset=utf-8", parsed.path == "/export")
        elif self.command == "POST":
            if self.headers.get("Content-Type", "").lower() not in {"application/json", "application/json; charset=utf-8"}:
                raise Problem("Content-Type must be application/json.", 415)
            try:
                data = json.loads(body.decode("utf-8"), object_pairs_hook=no_duplicate_keys, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite number")))
            except (UnicodeError, ValueError, RecursionError) as error:
                raise Problem("Malformed JSON or duplicate keys.") from error
            if not isinstance(data, dict):
                raise Problem("A JSON object is required.")
            expected = {"version", "content", "note"} if parsed.path == "/api/draft" else {"version"}
            if set(data) != expected or type(data.get("version")) is not int:
                raise Problem("Unexpected fields or invalid revision number.")
            if parsed.path == "/api/draft":
                store.save(data["version"], data["content"], data["note"])
            elif parsed.path == "/api/review":
                store.review(data["version"])
            elif parsed.path == "/api/publish":
                store.publish(data["version"])
            else:
                raise Problem("Route not found.", 404)
            return self.reply(200, store.state())
        raise Problem("Route not found.", 404)

    def handle_request(self):
        try:
            self.route()
        except Problem as error:
            self.reply(error.status, {"error": str(error), "issues": error.issues})
        except (ValueError, UnicodeError):
            self.reply(400, {"error": "Invalid request."})
        except (TimeoutError, ConnectionError, BrokenPipeError):
            self.close_connection = True
        except sqlite3.Error:
            self.reply(503, {"error": "Local database is busy or unavailable. Try again."})

    do_GET = handle_request
    do_POST = handle_request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["seed", "serve"])
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "workbench.sqlite3")
    parser.add_argument("--port", type=int, default=8093)
    args = parser.parse_args()
    store = Store(args.db)
    if args.command == "seed":
        store.seed()
        print("Fictional program ready. Existing editorial work was preserved.")
        return
    if not args.db.is_file():
        parser.error("Run the seed command first.")
    server = Server(args.port, store)
    print(f"Publication Workbench: {server.origin}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
