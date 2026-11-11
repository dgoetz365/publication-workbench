# Publication Workbench

A working editorial publishing demo: edit a fictional arts program, save revisions, validate linked records, review an exact revision, and publish a stable edition. Published search results point to the actual performer, venue, or program entry. Every edition exports as a self-contained HTML program.

Built as original portfolio software using invented content. All festival, performer, venue, and program details are fictional.

## Run locally

Requires Python 3.12 or later. No packages, accounts, keys, or build step.
From this repository root:

```sh
python app.py seed
python app.py serve
```

Open [http://127.0.0.1:8093](http://127.0.0.1:8093). Stop with Ctrl+C. Seed is safe to repeat: it preserves existing editorial work. The SQLite database lives under `data/`, which is ignored by Git. Use `--port 8094` to choose another local port; `--db path/to/demo.sqlite3` selects a separate database on both commands.

## Try the editorial workflow

1. Select **A Pocket of Light**. Revise its description, add a revision note, and choose **Save revision**. Open **Saved revisions** to inspect the earlier copy.
2. Choose **Preview saved draft**. Read the program in the new tab, return to the editor, and choose **Mark reviewed**. Review is a deliberate editor assertion, not an automated proof of reading.
3. Choose **Publish edition**. Open the published program, then search for **Tala** and select the performer result. It opens the performer profile, not the top of the page. Try **Paper Hall** for a venue or **Pocket** for a program entry.
4. Choose **Download HTML**. The file includes its styles and internal links and works offline.
5. Edit and save the program title. Reopen the published edition: its title is unchanged. Review and publish the new revision to create another edition; older edition URLs continue to work.
6. To see validation, clear an entry title or choose the blank performer option and save. The revision is retained for continued editing, but review and publication are blocked until the fields are repaired and saved. A second open editor tab can demonstrate a stale-save conflict without overwriting the newer revision.

## Architecture decisions

- **Structured drafts:** performers, venues, and entries have stable IDs. Entry references resolve to real entity sections in both preview and export.
- **Revision snapshots:** every save inserts a complete JSON document into SQLite. Earlier revisions are preserved. Required text and entity links are editorial validation; malformed document shapes are rejected before storage.
- **Exact-version review:** any new save clears review. Save, review, and publish compare the supplied version against the current draft under `BEGIN IMMEDIATE`, preventing stale requests from silently replacing newer work.
- **Atomic publication:** publishing copies the reviewed document into a separate immutable edition row in one transaction. A failed insert rolls back. Retrying publication of the same revision returns the existing edition.
- **Pinned reading:** search responses contain the edition number and a concrete anchor. The program renderer and HTML download read the same stored edition, so subsequent edits cannot change those links or content.
- **Small local runtime:** Python's HTTP server serves only an explicit static allowlist and known API routes. It binds to `127.0.0.1`, checks Host and Origin, requires JSON for writes, rejects duplicate headers/JSON keys, bounds request size, and rejects Unicode surrogates. DOM text uses `textContent`; generated HTML escapes all editorial text.

`app.py` owns storage, validation, rendering, search, and HTTP routing. `static/` contains the dependency-free editor. `tests/` exercises state and HTTP behavior using temporary databases and a real loopback server.

See [engineering decisions](docs/decisions.md) for the publication model and tradeoffs, and [design notes](DESIGN.md) for the interface system.

## Validation

```sh
python -m unittest discover -s tests -v
```

Tests cover revision preservation, stale writes, review invalidation, missing fields and broken references, immutable editions, rollback after an injected database failure, idempotent publishing, search-to-rendered-entity matching, escaped exports, the HTTP editorial workflow, traversal rejection, request framing guards, body limits, and invalid Unicode. JavaScript syntax can be checked with `node --check static/app.js` when Node is available.

The implementation was validated with Python 3.12.14 and Node 22.23.3. Browser rendering and interactive browser behavior were not tested. Responsive CSS and keyboard focus states are implemented; no visual or accessibility conformance certification is claimed.

## Scope and limits

This is a local, single-user illustration, not a production publishing service. There is no authentication, user attribution, remote deployment, rich-text editor, media upload, record creation/deletion UI, review assignment, or backup service. The seeded record roster is edited in place. SQLite stores the full draft on every save; the UI shows the latest 20 revisions. The server is intentionally not exposed to the network, and its checks are not a substitute for production security controls. Concurrent tabs receive version conflicts, but there is no collaborative merge interface. Large uploads, scheduling, and distribution are outside this demonstration.

MIT licensed. See [LICENSE](LICENSE).
