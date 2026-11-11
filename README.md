# Publication Workbench

Edit, review, and publish a fictional arts program while keeping every published edition intact.

**Python 3.12+ · SQLite · JavaScript · No runtime dependencies**

[Full guide](docs/guide.md) · [Portfolio](https://github.com/dgoetz365) · [MIT license](LICENSE)

## Quick start

```sh
git clone https://github.com/dgoetz365/publication-workbench.git
cd publication-workbench
python app.py seed
python app.py serve
```

Open http://127.0.0.1:8093. The editor starts with fictional performers, venues, and program entries. Stop with Ctrl+C; saved work stays in `data/`. Seeding again preserves existing work.

On Windows, `py -3.12` can replace `python`. If you already cloned the repo, start with the Python commands from its root.

## Try it

Edit **A Pocket of Light**, save the revision, mark it reviewed, and publish. Search the edition for **Tala**, follow the performer result, and download the HTML program. Edit the draft again: the published edition stays unchanged.

## Engineering highlights

- **Editorial state:** saving a revision clears review; publication requires the exact reviewed revision.
- **Stable editions:** publication is atomic and repeat-safe; search links and exports use the stored edition.
- **Failure handling:** stale writes are rejected, failed publication rolls back, and exported text is escaped.

[Application and storage](app.py) · [Tests](tests/) · [Engineering decisions](docs/decisions.md)

## Tests and scope

```sh
python -m unittest discover -s tests -v
```

A local, single-user demonstration with synthetic content and no authentication. Browser rendering has not been verified. Detailed constraints, alternate ports, and database options are in the guide.

Built by [Daniel Goetz](https://github.com/dgoetz365) as an independent portfolio example. Employer code and data are not included.
