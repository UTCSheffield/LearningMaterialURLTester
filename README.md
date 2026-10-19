# LearningMaterialURLTester

Scan folders of learning materials and extract URLs from:

- Markdown (`.md`, `.markdown`)
- Word (`.docx`, `.docm`)
- PowerPoint (`.pptx`, `.pptm`)
- PDF (`.pdf`)

URLs are stored in a SQLite database. Check them separately with Microsoft Edge to report whether they appear to be blocked by Senso.

## Install

```bash
pip install .
```

## Run as a module

The tool has three commands: `scan` discovers URLs, `check` tests unchecked URLs, and `import` loads existing results. Run them in order for a new collection:

```bash
python -m learning_material_url_tester scan /path/to/learning-materials
python -m learning_material_url_tester check
```

`scan` accepts one or more root folders and searches recursively. It does not check URLs. The default database is `url_check_results.db` in the current directory. After `check`, the tool writes `url_check_results.csv`, `url_check_results_blocked.csv`, and `url_check_results_errors.csv` there.

### Check options

Edge must be fully closed before checking. The selected Edge profile must have Senso active; the tool verifies this by checking that `facebook.com` is blocked before it checks the collection.

```bash
python -m learning_material_url_tester check --help
```

- `--check-blocked` re-tests URLs previously marked as blocked.
- `--limit N` checks at most the first `N` unchecked URLs and keeps failed tabs open in Edge.
- `--start-at N` starts at the 1-based position `N` among unchecked URLs (default: `1`).
- `--edge-profile DIR` selects the Edge `User Data` directory (default: `%LOCALAPPDATA%\Microsoft\Edge\User Data`).

To use a different output name, place the global `--output` option before the command. The SQLite database uses the same path with a `.db` extension, and the blocked/error CSVs are named by adding `_blocked` and `_errors` before the extension.

```bash
python -m learning_material_url_tester --output results.csv scan /path/to/learning-materials
python -m learning_material_url_tester --output results.csv check
```

### Import previous results

Imported rows are marked as already checked, so `check` will not check them again unless they are blocked and you pass `--check-blocked`.

```bash
python -m learning_material_url_tester import previous_results.csv
python -m learning_material_url_tester check --check-blocked
```

### View the report

Launch the Streamlit report with the installed command and choose a database in the app:

```bash
learning-material-url-tester-report
```

Or open a specific database directly:

```bash
learning-material-url-tester-report --db url_check_results.db
```
