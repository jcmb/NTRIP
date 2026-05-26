# Developer Documentation

This document describes the structure and behavior of the NTRIP client application for maintainers.

## Main Files

- `NTRIP Client/NtripClient.py`: main client, CLI, GUI, config handling, source-table parsing, and connection logic.
- `.github/workflows/build-ntripclient.yml`: GitHub Actions workflow for building standalone binaries with PyInstaller.

## Runtime Dependencies

The client uses Python standard library modules for normal operation:

- `argparse`
- `base64`
- `datetime`
- `json`
- `os`
- `pathlib`
- `socket`
- `ssl`
- `sys`
- `threading`
- `time`
- `tkinter`

PyInstaller is only needed for binary builds.

## Configuration Model

Default settings are defined in `CONFIG_DEFAULTS` in `NtripClient.py`.

Config files are JSON objects. The GUI presents them with a `.ntrip` extension, but the file contents are JSON. `load_config_file()` only returns keys recognized by `CONFIG_DEFAULTS`, which prevents unknown keys from flowing into runtime configuration.

Important config behavior:

- `DEFAULT_CONFIG_PATH` is `~/ntripclient.ntrip`.
- GUI startup uses `load_last_config_path()` to load the last opened or saved config when available.
- The last config pointer is stored in `~/.ntripclient-last.json`.
- `normalize_config()` coerces strings, integers, floats, and booleans into runtime types.
- `save_config_file()` writes a normalized JSON object with sorted keys.

## Connection Flow

`build_ntrip_args()` converts normalized config into `NtripClient` constructor arguments.

Key behavior:

- Mountpoints are normalized to start with `/`.
- Non-IBSS connections use `caster` and `port` directly.
- IBSS mode builds the caster from `org` or `baseorg`.
- `ssl=True` wraps the socket with TLS using Python `ssl`.
- `ssl_insecure=True` disables certificate validation.
- `ssl_cafile` is loaded into the TLS context when validation is enabled and a CA path is provided.

`NtripClient.readData()` handles:

- TCP/TLS socket creation.
- Request header creation through `getMountPointBytes()`.
- Caster response header parsing.
- Optional GGA transmission.
- Chunked transfer decoding when the caster sends `Transfer-Encoding: chunked`.
- Data streaming to stdout or an output file.
- Optional UDP broadcast.
- Reconnect behavior.
- Cooperative stop through `stop_event`.

The GUI passes a `threading.Event` to `run_client()` so the `Stop` button can shut down the active socket and stop reconnect sleeps.

## Header Output

Header output is controlled by `headerOutput`.

When enabled:

- Normal NTRIP connection requests are written by `getMountPointBytes()`.
- Normal caster response header lines are written during header parsing.
- Source-table request and response are written by `write_source_table_exchange()`.

When `HeaderFile` is set and header output is enabled, output goes to that file. Otherwise it goes to stderr. Header output should not be written to stdout, because stdout may carry binary correction data.

## Chunked Transfer Handling

`ChunkedDecoder` removes HTTP chunk framing from caster data when the response headers include `Transfer-Encoding: chunked`.

Normal stream handling:

- Header parsing detects `Transfer-Encoding: chunked`.
- Any body bytes received with the header block are fed into the decoder first.
- Subsequent socket reads are decoded before writing to stdout, an output file, or UDP.
- A zero-length chunk stops the stream.

If a response advertises chunked encoding but the body is not valid chunked data, `ChunkedDecodeError` is caught, an error is written to stderr, and the raw stream data is passed through.

Source-table handling also checks for chunked encoding and decodes the body before parsing `STR;...` records.

## Source Table Lookup

The GUI `Get Mountpoint` button calls `read_source_table()` in a background thread.

The source-table path:

1. `build_source_table_args()` creates connection args and forces the mountpoint request to `/`.
2. `connect_ntrip_socket()` opens TCP or TLS.
3. `get_source_table_request_bytes()` builds the source-table HTTP/NTRIP request.
4. `read_source_table()` reads until `ENDSOURCETABLE`, socket close, or a 2 MB cap.
5. `parse_source_table()` extracts `STR;...` records into mountpoint dictionaries.
6. The GUI displays those records in a `ttk.Treeview`.

`parse_source_table()` currently expects standard NTRIP source table `STR` records and extracts:

- mountpoint
- identifier
- format
- format details
- network
- country
- latitude
- longitude

## GUI Structure

`run_gui()` owns the Tkinter interface.

Notable GUI behavior:

- The active config path is shown in the window title.
- Open/save dialogs default to the launch directory until a real config/file path is chosen.
- The window starts at `650x920`.
- `Use TLS` controls TLS socket wrapping and defaults the port between `2101` and `52101` only when the port still has a default value.
- `Validate TLS certificate` and `TLS CA file` are disabled unless `Use TLS` is enabled.
- `GGA latitude`, `GGA longitude`, and `GGA height` are disabled unless `Send GGA` is enabled.
- `Start` changes to `Stop` while a client thread is running.
- `Save` opens a save dialog and defaults to `Caster-Mountpoint.ntrip`.
- `Browse` opens an existing config and remembers it for the next startup.

The mountpoint selector is a child `Toplevel` centered over the main window. It uses a grab while open and explicitly releases focus on cancel or selection.

## CLI Behavior

The same file supports command-line use through `build_arg_parser()` and `main()`.

Important options:

- `--config [FILE]`: load a config file.
- `--save-config [FILE]`: save effective config.
- `--tls` / `--ssl`: enable TLS.
- `--no-tls` / `--no-ssl`: disable TLS.
- `--ssl-cafile PEM`: trust a supplied CA bundle or PEM.
- `--ssl-insecure`: disable TLS certificate validation.
- `--ssl-secure`: enable certificate validation from a config.
- `--Header`: output headers.
- `--HeaderFile FILE`: output headers to a file when header output is enabled.
- `--GGA` / `--no-GGA`: control GGA transmission.

## Build Workflow

`.github/workflows/build-ntripclient.yml` builds binaries using PyInstaller.

Artifacts:

- `ntripclient-linux-amd64`
- `ntripclient-linux-arm64`
- `ntripclient-linux-arm32`
- `ntripclient-macos-arm64`
- `ntripclient-windows-amd64`

Linux ARM builds run in Docker with QEMU. macOS ARM uses `macos-14`. Windows builds on `windows-latest`.

## Local Validation

Run a syntax check after Python edits:

```sh
python3 -m py_compile "NTRIP Client/NtripClient.py"
```

Run the GUI locally:

```sh
python3 "NTRIP Client/NtripClient.py"
```

Run CLI help:

```sh
python3 "NTRIP Client/NtripClient.py" --help
```

## Development Notes

- Keep stdout reserved for correction data unless the user explicitly routes output to a file.
- Send diagnostics, connection settings, and headers to stderr or the configured header file.
- Keep config backward-compatible when practical; `load_config_file()` already accepts `lon` and maps it to `long`.
- Avoid writing headers unless `headerOutput` is enabled.
- When adding config keys, update `CONFIG_DEFAULTS`, `normalize_config()`, GUI field collection, and this documentation.
