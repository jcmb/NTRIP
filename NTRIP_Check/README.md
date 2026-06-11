# NTRIP Check

Simple Python CLI to test NTRIP source-table authentication for multiple usernames.

## What it does

- Supports two input modes:
  - `--usernames-file` with one entry per line:
    - `username`
    - `username:password`
  - `--wm-file` (CSV export with one header row)
- Optional IBSS mode with `--org`:
  - host becomes `<org>.ibss.trimbleos.com`
  - `--server` is not required when `--org` is provided
- WM username format:
  - `Column3 + "-" + Column4 + "." + org`
- WM license filtering:
  - by default processes only rows where `Column6` is `Licensed`
  - use `--include-non-licensed` to include other statuses
- WM header validation:
  - by default verifies row-1 columns 3/4/6 are
    `Device Type`, `Serial Number`, `License Status`
  - use `--skip-wm-header-validation` for translated headers
- Password precedence:
  - `--password`, or
  - per-line password in usernames file, or
  - secure terminal prompt only for username-only lines.
- Optional `--expected` mountpoint count:
  - `SUCCESS` when mountpoint count matches expected
  - `Warning` in WM mode for GNSS receivers (`SPS850`, `SPS851`, `SPS852`,
    `SPS855`, `R750`, `R750-2`) when count is in
    `expected-(expected-base-connection)` range
  - `Failed` when mountpoint count differs from expected
  - `Unauthorized or active` when HTTP 401 is returned
  - `Failed` for other HTTP/connection failures
- Optional `--base-connection` now allows `0-3` and defaults to `1`.
- When `--expected` is provided, expected/base values are shown in report metadata.
- Report includes a status summary table at the top.
- Report includes run time stamps (Local and UTC) at the bottom.
- Connects to NTRIP caster (`--port` defaults to `2101`).
- Sends a source-table request (`GET /`).
- Logs live status to the console by default while checks run.
- Writes an HTML report with a sortable table showing each request result and `STR;` item count.

## Usage

Usernames file mode with explicit server:

```bash
python3 ntrip_check.py --server caster.example.com --usernames-file usernames.txt
```

IBSS mode (server auto-derived from org):

```bash
python3 ntrip_check.py --org myorg --usernames-file usernames.txt
```

WM file mode (requires org):

```bash
python3 ntrip_check.py --org myorg --wm-file wm_export.csv
```

Include non-licensed rows from WM file:

```bash
python3 ntrip_check.py --org myorg --wm-file wm_export.csv --include-non-licensed
```

Skip WM header validation (for translated headers):

```bash
python3 ntrip_check.py --org myorg --wm-file wm_export.csv --skip-wm-header-validation
```

With explicit password:

```bash
python3 ntrip_check.py --org myorg --wm-file wm_export.csv --password "secret"
```

Check against an expected mountpoint count:

```bash
python3 ntrip_check.py --org myorg --wm-file wm_export.csv --expected 42
```

Adjust WM GNSS warning offset (default is 1):

```bash
python3 ntrip_check.py --org myorg --wm-file wm_export.csv --expected 42 --base-connection 2
```

Set a custom output HTML path:

```bash
python3 ntrip_check.py --org myorg --wm-file wm_export.csv --output-html report.html
```

If `--output-html` is omitted, output defaults to the input file name with `.html`.
If `--output-html` is provided without `.html`, `.html` is appended automatically.

Disable live console progress logging:

```bash
python3 ntrip_check.py --org myorg --wm-file wm_export.csv --no-progress
```

## Usernames file format

`usernames.txt` example:

```text
# Comments and blank lines are ignored.
# username only (uses --password or prompt)
alice

# username with line-specific password
bob:bob_password

# another username-only line
charlie
```

## WM file expectations

- First row is a header row and is skipped from processing.
- By default header row must have:
  - column 3: `Device Type`
  - column 4: `Serial Number`
  - column 6: `License Status`
- WM username is built as:
  - `<column3>-<column4>.<org>`
- In reports, WM entries display device name as:
  - `<column3>-<column4>`
