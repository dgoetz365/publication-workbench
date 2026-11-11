import copy
from html.parser import HTMLParser
import http.client
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import MAX_BODY, Problem, Server, Store, render_program, search, validate


class Anchors(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.links = []
        self.current = None
        self.text = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.add(attrs["id"])
        if tag == "article":
            self.current = attrs["id"]
            self.text[self.current] = ""
        if tag == "a":
            self.links.append(attrs.get("href", ""))

    def handle_endtag(self, tag):
        if tag == "article":
            self.current = None

    def handle_data(self, data):
        if self.current:
            self.text[self.current] += data


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "test.sqlite3")
        self.store.seed()

    def publish(self):
        version = self.store.state()["version"]
        self.store.review(version)
        return self.store.publish(version)

    def test_seed_is_non_destructive(self):
        state = self.store.state()
        state["content"]["title"] = "New draft title"
        self.store.save(1, state["content"], "Title update")
        self.store.seed()
        self.assertEqual(self.store.state()["content"]["title"], "New draft title")
        self.assertEqual(self.store.state()["version"], 2)

    def test_saved_revisions_and_published_snapshots_are_immutable(self):
        edition = self.publish()
        old = self.store.publication(edition)
        draft = copy.deepcopy(old["content"])
        draft["entries"][0]["title"] = "Changed but unpublished"
        self.store.save(1, draft, "Revise title")
        self.assertEqual(self.store.publication(edition), old)
        self.assertEqual(self.store.revision(1), old["content"])
        self.assertNotEqual(self.store.revision(2), old["content"])
        self.assertIsNone(self.store.state()["reviewed_version"])

    def test_save_conflicts_never_overwrite(self):
        content = self.store.state()["content"]
        self.store.save(1, content, "First save")
        with self.assertRaises(Problem) as raised:
            self.store.save(1, content, "Stale save")
        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(len(self.store.state()["history"]), 2)

    def test_review_and_publish_require_current_version(self):
        content = self.store.state()["content"]
        self.store.review(1)
        self.store.save(1, content, "New version")
        for action in (self.store.review, self.store.publish):
            with self.assertRaises(Problem) as raised:
                action(1)
            self.assertEqual(raised.exception.status, 409)
        with self.assertRaises(Problem):
            self.store.publish(2)
        self.assertIsNone(self.store.state()["published"])

    def test_missing_fields_and_broken_links_are_saved_but_block_publication(self):
        self.publish()
        before = self.store.publication()
        content = self.store.state()["content"]
        content["entries"][0]["title"] = " "
        content["entries"][0]["performer_id"] = "missing-performer"
        self.store.save(1, content, "Incomplete edit")
        paths = {issue["path"] for issue in self.store.state()["issues"]}
        self.assertIn("entries/a-pocket-of-light/title", paths)
        self.assertIn("entries/a-pocket-of-light/performer_id", paths)
        for action in (self.store.review, self.store.publish):
            with self.assertRaises(Problem) as raised:
                action(2)
            self.assertEqual(raised.exception.status, 422)
        self.assertEqual(self.store.publication(), before)

    def test_failed_database_write_rolls_back_publication(self):
        self.publish()
        content = self.store.state()["content"]
        self.store.save(1, content, "Second edition")
        self.store.review(2)
        before = self.store.publication()
        with self.store.connection(True) as db:
            db.execute("CREATE TRIGGER deny_publish AFTER INSERT ON publications BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.publish(2)
        self.assertEqual(self.store.publication(), before)
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM publications").fetchone()[0], 1)

    def test_repeated_publish_is_idempotent(self):
        edition = self.publish()
        self.assertEqual(self.store.publish(1), edition)
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM publications").fetchone()[0], 1)

    def test_search_results_target_correct_entities_in_pinned_edition(self):
        edition = self.publish()
        publication = self.store.publication()
        parser = Anchors()
        parser.feed(render_program(publication["content"], "Published"))
        for query, kind, title in (("Tala", "performer", "Tala Morrow"), ("Pocket", "entry", "A Pocket of Light"), ("Paper Hall", "venue", "Paper Hall")):
            matches = search(publication, query)
            expected = next(item for item in matches if item["kind"] == kind)
            url = urlsplit(expected["href"])
            self.assertEqual(url.query, f"edition={edition}")
            self.assertIn(url.fragment, parser.ids)
            self.assertIn(title, parser.text[url.fragment])
        for href in parser.links:
            if href.startswith("#"):
                self.assertIn(href[1:], parser.ids)

    def test_export_escapes_text_and_has_no_external_dependencies(self):
        content = self.store.state()["content"]
        content["title"] = '<script>alert("x")</script>'
        content["performers"][0]["bio"] = '<img src=x onerror="alert(1)"> & text'
        document = render_program(content, '<unsafe label>')
        self.assertNotIn("<script", document)
        self.assertNotIn("<img", document)
        self.assertNotIn("src=", document.replace("src=x", ""))
        self.assertIn("&lt;script&gt;", document)
        self.assertIn("&lt;unsafe label&gt;", document)
        self.assertIn("<style>", document)

    def test_shape_rejects_duplicate_ids_surrogates_and_oversized_values(self):
        original = self.store.state()["content"]
        for change in (lambda c: c["entries"].append(c["entries"][0]),
                       lambda c: c.update(title="bad\ud800"),
                       lambda c: c.update(intro="x" * 4001)):
            content = copy.deepcopy(original)
            change(content)
            with self.assertRaises(Problem):
                self.store.save(1, content, "Invalid")
        self.assertEqual(self.store.state()["version"], 1)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "http.sqlite3")
        self.store.seed()
        self.server = Server(0, self.store)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = self.server.origin
        self.port = self.server.server_port

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, path, method="GET", data=None, headers=None, raw=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        body = raw if raw is not None else json.dumps(data).encode() if data is not None else None
        actual_headers = {"Origin": self.origin, "Content-Type": "application/json"}
        actual_headers.update(headers or {})
        connection.request(method, path, body=body, headers=actual_headers)
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def test_complete_http_editorial_workflow(self):
        status, _, body = self.request("/api/state")
        self.assertEqual(status, 200)
        state = json.loads(body)
        state["content"]["intro"] += " A revised introduction."
        self.assertEqual(self.request("/api/draft", "POST", {"version": 1, "content": state["content"], "note": "Intro edit"})[0], 200)
        self.assertEqual(self.request("/preview?version=2")[0], 200)
        self.assertEqual(self.request("/api/review", "POST", {"version": 2})[0], 200)
        self.assertEqual(self.request("/api/publish", "POST", {"version": 2})[0], 200)
        result = json.loads(self.request("/api/search?q=Tala&edition=1")[2])
        target = next(row["href"] for row in result["results"] if row["kind"] == "performer")
        url = urlsplit(target)
        status, _, body = self.request(url.path + "?" + url.query)
        self.assertEqual(status, 200)
        parser = Anchors()
        parser.feed(body.decode())
        self.assertIn("Tala Morrow", parser.text[url.fragment])
        export_status, headers, export = self.request("/export?edition=1")
        self.assertEqual(export_status, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertEqual(export, body)

    def test_older_publication_remains_addressable_after_next_edition(self):
        self.store.review(1)
        self.store.publish(1)
        before = self.request("/program?edition=1")[2]
        content = self.store.state()["content"]
        content["title"] = "A revised gathering"
        self.store.save(1, content, "Title")
        self.store.review(2)
        self.store.publish(2)
        self.assertEqual(self.request("/program?edition=1")[2], before)
        self.assertIn(b"A revised gathering", self.request("/program")[2])

    def test_no_published_data_before_explicit_publish(self):
        for path in ("/program", "/export", "/api/search?q=Tala"):
            self.assertEqual(self.request(path)[0], 404)

    def test_static_allowlist_blocks_traversal_and_runtime_files(self):
        for path in ("/../app.py", "/%2e%2e/app.py", "/data/workbench.sqlite3", "/app.py"):
            self.assertEqual(self.request(path)[0], 404)
        self.assertEqual(self.request("/")[0], 200)
        self.assertEqual(self.request("/app.js")[0], 200)

    def test_host_origin_and_json_guards(self):
        for headers, expected in (({"Host": "untrusted.invalid"}, 403), ({"Origin": "http://untrusted.invalid"}, 403), ({"Origin": ""}, 403), ({"Content-Type": "text/plain"}, 415)):
            self.assertEqual(self.request("/api/review", "POST", {"version": 1}, headers)[0], expected)
        self.assertEqual(self.request("/api/review", "POST", raw=b'{"version":1,"version":1}')[0], 400)
        self.assertEqual(self.request("/api/review", "POST", raw=b'{"version":NaN}')[0], 400)
        self.assertEqual(self.request("/api/review", "POST", raw=b'\xff')[0], 400)
        self.assertEqual(self.request("/api/review", "POST", raw=b'[' * 1100 + b']' * 1100)[0], 400)

    def test_surrogate_and_boolean_revision_are_rejected(self):
        content = self.store.state()["content"]
        content["title"] = "\udfff"
        self.assertEqual(self.request("/api/draft", "POST", {"version": 1, "content": content, "note": "Invalid"})[0], 400)
        self.assertEqual(self.request("/api/review", "POST", {"version": True})[0], 400)
        self.assertEqual(self.store.state()["version"], 1)

    def test_body_limit(self):
        self.assertEqual(self.request("/api/review", "POST", raw=b" " * (MAX_BODY + 1))[0], 413)

    def test_duplicate_headers_rejected(self):
        body = b'{"version":1}'
        wire = (f"POST /api/review HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nOrigin: {self.origin}\r\nContent-Type: application/json\r\nX-Demo: one\r\nX-Demo: two\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n").encode() + body
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as connection:
            connection.sendall(wire)
            response = http.client.HTTPResponse(connection)
            response.begin()
            self.assertEqual(response.status, 400)
            self.assertIn(b"Duplicate request headers", response.read())
        self.assertIsNone(self.store.state()["reviewed_version"])

    def test_stale_http_publish_does_not_change_edition(self):
        self.store.review(1)
        self.store.publish(1)
        content = self.store.state()["content"]
        self.store.save(1, content, "New revision")
        self.assertEqual(self.request("/api/publish", "POST", {"version": 1})[0], 409)
        self.assertEqual(self.store.publication()["version"], 1)


if __name__ == "__main__":
    unittest.main()
