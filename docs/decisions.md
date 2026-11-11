# Engineering decisions

## Publish a whole edition

The unit of publication is one consistent program: introduction, entries, performers, and venues. Publishing separate tables independently could mix different editorial revisions. A complete JSON snapshot stored in a transaction keeps linked content together. The tradeoff is repeated content and a deliberately small 60 KB draft limit.

## Separate storage shape from editorial readiness

An editor must be able to save unfinished work. The server rejects malformed records, unsupported characters, duplicate IDs, and excessive content before storing a draft. Missing required text and broken entity references are saved, then surfaced as editorial issues. Review and publication require zero issues.

## Review one revision

Review records an exact revision number. Saving any change clears that review; even a small correction must be reconsidered before publication. All mutating operations check the caller's draft version while holding SQLite's write transaction. Stale tabs receive a conflict and retain their unsaved local text. There is no silent merge.

## Preserve destinations, not only search matches

Every search result names a stored edition and an entity anchor. The renderer uses the same stable IDs. This prevents a draft rename or a later publication from redirecting an existing result into different content. Tests parse rendered HTML and verify the exact fragment, edition, entity type, and title. HTTP tests follow the result's actual path/query and check the matching article's text.

## Keep the runtime inspectable

The standard library and SQLite are enough for this scale. The browser uses ordinary forms and safe text nodes. The export has embedded CSS and no scripts, font downloads, or external dependencies. The HTTP server is local-only and requires same-origin JSON writes. It is an illustrative single-user tool, not an authentication or production-hosting solution.

## Evidence and limits

Automated state and HTTP tests exercise both successful publication and blocked/failed operations, including rollback after an injected database failure. They do not establish browser rendering, keyboard usability, screen-reader behavior, or production readiness. No browser testing was performed for this build. The source detector reported one warm-background style warning; the paper palette is an intentional program-design choice documented in `DESIGN.md`.
