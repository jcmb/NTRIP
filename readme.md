# NTRIP Client

This repository includes a Python NTRIP client for connecting to an NTRIP caster, selecting a mountpoint, and streaming correction data to stdout, a file, or UDP.

The main application is `NTRIP Client/NtripClient.py`. Run it with no arguments to open the GUI, or provide command-line arguments to run directly from a terminal.

## Capabilities

- Connect to NTRIP V1 or V2 casters.
- Use plain TCP or TLS connections.
- Optionally validate TLS certificates with the system trust store or a supplied CA file.
- Fetch and parse an NTRIP source table from the caster.
- Select a mountpoint from a source-table dialog.
- Decode `Transfer-Encoding: chunked` caster responses before forwarding data.
- Send a GGA sentence when enabled.
- Stream correction data to stdout or an output file.
- Optionally broadcast received data over UDP.
- Optionally output request/response headers to stderr or a header file.
- Save and load `.ntrip` JSON configuration files.
- Remember the last opened or saved configuration file on startup.
- Build standalone binaries with GitHub Actions.

## Running The GUI

From the repository root:

```sh
python3 "NTRIP Client/NtripClient.py"
```

The GUI opens with the last used configuration if one was previously opened or saved. Otherwise it starts with defaults:

- Caster: `SPS855.com`
- Port: `2101`
- TLS: off
- TLS certificate validation: off
- User/password: `IBS` / `IBS`

The active configuration file path is shown in the window title.

## GUI Workflow

1. Enter the caster, port, username, password, and mountpoint.
2. Enable `Use TLS` if the caster requires TLS. If the port is still the default `2101`, enabling TLS changes it to `52101`.
3. Enable `Validate TLS certificate` only when certificate validation is wanted. If needed, select a `TLS CA file`.
4. Enable `Send GGA` if the caster requires a GGA sentence, then edit the GGA latitude, longitude, and height fields.
5. Click `Get Mountpoint` to request the caster source table and choose a mountpoint.
6. Click `Start` to connect. The button changes to `Stop` while connected.
7. Click `Save` to save the current settings to a `.ntrip` config file.

`Save` opens a save dialog. The default filename is based on the caster and mountpoint, for example:

```text
SPS855.com-MOUNTPOINT.ntrip
```

Open and save dialogs default to the directory where the application was launched unless an existing config or file path has already been chosen.

## Source Table Lookup

`Get Mountpoint` connects to the caster, requests the source table, parses `STR;...` records, and displays available mountpoints in a selection dialog. Double-click a row or choose `Use Selected` to set the mountpoint.

Header output from this request is only written when `Output headers` is enabled:

- If `Header file` is set, headers are written to that file.
- Otherwise headers are written to stderr.

## Output Headers

Enable `Output headers` to capture request and response headers. Header output includes the NTRIP request and caster response headers.

If `Header file` is set, header output is written to that file. If no header file is set, header output goes to stderr. Headers are not written unless `Output headers` is enabled.

## Chunked Streams

If the caster response includes `Transfer-Encoding: chunked`, the client removes the chunk framing before writing correction data to stdout, an output file, or UDP. If a response advertises chunked encoding but the stream data is not valid chunked data, the client writes an error to stderr.

## Command-Line Usage

Basic usage:

```sh
python3 "NTRIP Client/NtripClient.py" MOUNTPOINT CASTER PORT
```

Example with TLS:

```sh
python3 "NTRIP Client/NtripClient.py" MOUNTPOINT SPS855.com 52101 --tls
```

Example with config:

```sh
python3 "NTRIP Client/NtripClient.py" --config my-base.ntrip
```

Show help:

```sh
python3 "NTRIP Client/NtripClient.py" --help
```

## Configuration Files

Configuration files use JSON content and typically use the `.ntrip` extension. They store fields such as caster, port, credentials, mountpoint, TLS options, GGA settings, output files, and header output settings.

The GUI remembers the last opened or saved config path in:

```text
~/.ntripclient-last.json
```

## Build Artifacts

GitHub Actions builds standalone binaries for:

- Linux AMD64
- Linux ARM64
- Linux ARM32
- macOS ARM64
- Windows AMD64

Artifacts are uploaded from the workflow run.
