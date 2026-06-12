#!/usr/bin/env python3
"""Simple NTRIP source table checker."""

from __future__ import annotations

import argparse
import base64
import csv
import getpass
import socket
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Iterable, Tuple


DEFAULT_PORT = 2101
DEFAULT_TIMEOUT_SECONDS = 10.0
EXPECTED_WM_HEADERS = ("Device Type", "Serial Number", "License Status")
APP_VERSION = "1.0.0"


@dataclass(frozen=True)
class UserCredential:
    display_name: str
    username: str
    line_password: str | None
    device_type: str | None


@dataclass(frozen=True)
class CheckResult:
    display_name: str
    username: str
    status: str
    message: str
    source_table_items: int | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check NTRIP source-table access for a list of usernames."
    )
    parser.add_argument(
        "--server",
        help="NTRIP caster hostname or IP address (required when --org is not used).",
    )
    parser.add_argument(
        "--org",
        help="Organization name for IBSS mode. Host becomes <org>.ibss.trimbleos.com.",
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--usernames-file",
        help="Path to a file with username or username:password per line.",
    )
    input_group.add_argument(
        "--wm-file",
        help="Path to WM CSV file (skips first row header).",
    )
    parser.add_argument(
        "--skip-wm-header-validation",
        action="store_true",
        help=(
            "Skip WM header checks for translated files. "
            "By default, verifies columns 3/4/6 are Device Type/Serial Number/License Status."
        ),
    )
    parser.add_argument(
        "--include-non-licensed",
        action="store_true",
        help="Include WM rows whose license status is not Licensed.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Caster port (default: {DEFAULT_PORT}).",
    )
    parser.add_argument(
        "--password",
        help="Password used for all usernames.",
    )
    parser.add_argument(
        "--expected",
        type=int,
        help="Expected number of mountpoints (STR lines) for a successful check.",
    )
    parser.add_argument(
        "--base-connection",
        type=int,
        choices=[0, 1, 2, 3],
        default=1,
        help=(
            "Allowed GNSS receiver mountpoint offset in WM mode (0-3, default: 1). "
            "Used for SPS855/R750 warning range when --expected is set."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=(
            "Socket timeout in seconds for connect/read operations "
            f"(default: {DEFAULT_TIMEOUT_SECONDS})."
        ),
    )
    parser.add_argument(
        "--output-html",
        help=(
            "Output HTML report path. If omitted, uses input file name "
            "with .html extension."
        ),
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable live progress logging to the console.",
    )
    return parser.parse_args()


def resolve_server(args: argparse.Namespace) -> str:
    if args.org:
        return f"{args.org}.ibss.trimbleos.com"
    if args.server:
        return args.server
    raise ValueError("--server is required unless --org is provided.")


def read_usernames(path: Path) -> list[UserCredential]:
    if not path.exists():
        raise FileNotFoundError(f"Usernames file not found: {path}")

    usernames: list[UserCredential] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            username, line_password = line.split(":", 1)
            username = username.strip()
            line_password = line_password.strip()
            if not username:
                continue
            usernames.append(
                UserCredential(
                    display_name=username,
                    username=username,
                    line_password=line_password if line_password else None,
                    device_type=None,
                )
            )
        else:
            usernames.append(
                UserCredential(
                    display_name=line,
                    username=line,
                    line_password=None,
                    device_type=None,
                )
            )

    if not usernames:
        raise ValueError("No usernames found in file.")

    return usernames


def detect_csv_dialect(path: Path) -> csv.Dialect:
    sample = path.read_text(encoding="utf-8").splitlines()
    sample_text = "\n".join(sample[:10])
    return csv.Sniffer().sniff(sample_text, delimiters=",;\t")


def read_wm_users(
    path: Path,
    org: str,
    skip_header_validation: bool,
    include_non_licensed: bool,
) -> list[UserCredential]:
    if not path.exists():
        raise FileNotFoundError(f"WM file not found: {path}")

    if not org:
        raise ValueError("--org is required when using --wm-file.")

    dialect = detect_csv_dialect(path)
    rows: list[list[str]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle, dialect=dialect)
        for row in reader:
            rows.append([col.strip() for col in row])

    if not rows:
        raise ValueError("WM file is empty.")

    header = rows[0]
    if len(header) < 6:
        raise ValueError("WM header must contain at least 6 columns.")

    if not skip_header_validation:
        actual = (header[2], header[3], header[5])
        if actual != EXPECTED_WM_HEADERS:
            raise ValueError(
                "WM header columns 3/4/6 do not match expected values "
                f"{EXPECTED_WM_HEADERS}. Use --skip-wm-header-validation to bypass."
            )

    users: list[UserCredential] = []
    for row in rows[1:]:
        if len(row) < 6:
            continue
        device_type = row[2]
        serial_number = row[3]
        license_status = row[5]
        if not device_type or not serial_number:
            continue
        if not include_non_licensed and license_status.lower() != "licensed":
            continue
        device_name = f"{device_type}-{serial_number}"
        username = f"{device_name}.{org}"
        users.append(
            UserCredential(
                display_name=device_name,
                username=username,
                line_password=None,
                device_type=device_type,
            )
        )

    if not users:
        raise ValueError("No WM usernames found after filtering.")

    return users


def resolve_shared_password(args: argparse.Namespace) -> str | None:
    if args.password:
        return args.password
    return None


def ensure_password_for_users(
    users: Iterable[UserCredential],
    shared_password: str | None,
) -> str | None:
    if shared_password:
        return shared_password

    has_missing_passwords = any(not user.line_password for user in users)
    if not has_missing_passwords:
        return None

    prompt = "Password for usernames without one in file: "
    password = getpass.getpass(prompt).strip()
    if not password:
        raise ValueError("Password cannot be empty when file has username-only lines.")
    return password


def build_request(server: str, port: int, username: str, password: str) -> bytes:
    credentials = f"{username}:{password}".encode("utf-8")
    auth = base64.b64encode(credentials).decode("ascii")
    host_header = f"{server}:{port}"
    req = (
        "GET / HTTP/1.0\r\n"
        f"Host: {host_header}\r\n"
        "User-Agent: NTRIP_Check/1.0\r\n"
        "Ntrip-Version: Ntrip/2.0\r\n"
        "Accept: */*\r\n"
        f"Authorization: Basic {auth}\r\n"
        "Connection: close\r\n"
        "\r\n"
    )
    return req.encode("ascii")


def parse_http_response(payload: bytes) -> Tuple[str, str]:
    text = payload.decode("latin-1", errors="replace")
    parts = text.split("\r\n\r\n", 1)
    headers = parts[0] if parts else ""
    body = parts[1] if len(parts) > 1 else ""
    status_line = headers.splitlines()[0] if headers else ""
    return status_line, body


def parse_status_code(status_line: str) -> int | None:
    parts = status_line.split()
    if len(parts) < 2:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


def count_source_table_entries(source_table_body: str) -> int:
    count = 0
    for line in source_table_body.splitlines():
        line = line.strip()
        if line.startswith("STR;"):
            count += 1
    return count


def fetch_source_table(
    server: str,
    port: int,
    username: str,
    password: str,
    timeout: float,
) -> Tuple[str, str, int]:
    request = build_request(
        server=server,
        port=port,
        username=username,
        password=password,
    )

    try:
        with socket.create_connection((server, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(request)
            chunks: list[bytes] = []
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
    except Exception as exc:
        return "Failed", f"connection failed: {exc}", 0

    response = b"".join(chunks)
    if not response:
        return "Failed", "empty response from server", 0

    status_line, body = parse_http_response(response)
    status_code = parse_status_code(status_line)
    if status_code == 401:
        return "Unauthorized or active", status_line or "HTTP 401 Unauthorized", 0
    if status_code != 200:
        return "Failed", status_line or "HTTP error", 0

    item_count = count_source_table_entries(body)
    return "Success", status_line or "OK", item_count


def write_html_report(
    output_path: Path,
    report_title: str,
    server: str,
    port: int,
    results: list[CheckResult],
    expected_mountpoints: int | None,
    base_connection: int,
    run_local: datetime,
    run_utc: datetime,
) -> None:
    def status_to_css_class(status: str) -> str:
        normalized = status.strip().lower()
        if normalized == "success":
            return "success"
        if normalized == "unauthorized or active":
            return "warning"
        if normalized == "warning":
            return "warning"
        return "failed"

    rows: list[str] = []
    for result in results:
        status_class = status_to_css_class(result.status)
        rows.append(
            "<tr>"
            f"<td>{escape(result.display_name)}</td>"
            f'<td class="{status_class}">{escape(result.status)}</td>'
            f"<td>{escape(result.message)}</td>"
            f'<td data-sort="{result.source_table_items if result.source_table_items is not None else -1}">'
            f'{result.source_table_items if result.source_table_items is not None else ""}</td>'
            "</tr>"
        )

    status_counts = Counter(result.status for result in results)
    total_results = len(results)
    summary_rows = "".join(
        "<tr>"
        f"<td>{escape(status)}</td>"
        f"<td>{count}</td>"
        f"<td>{(count / total_results * 100) if total_results else 0:.1f}%</td>"
        "</tr>"
        for status, count in sorted(status_counts.items())
    )
    expected_meta = (
        f" | Expected: {expected_mountpoints}, Base: {base_connection}"
        if expected_mountpoints is not None
        else ""
    )
    run_local_text = run_local.strftime("%Y-%m-%d %H:%M:%S %Z")
    run_utc_text = run_utc.strftime("%Y-%m-%d %H:%M:%S UTC")

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(report_title)}</title>
  <!-- NTRIP_Check version: {escape(APP_VERSION)} -->
  <style>
    body {{
      font-family: Arial, sans-serif;
      margin: 1.5rem;
      color: #1f2937;
    }}
    h1 {{
      margin-bottom: 0.25rem;
    }}
    .meta {{
      color: #4b5563;
      margin-bottom: 1rem;
    }}
    table {{
      border-collapse: collapse;
      width: 100%;
    }}
    th, td {{
      border: 1px solid #d1d5db;
      padding: 0.5rem 0.6rem;
      text-align: left;
    }}
    th {{
      background: #f3f4f6;
      cursor: pointer;
      user-select: none;
    }}
    tr:nth-child(even) {{
      background: #f9fafb;
    }}
    .success {{
      color: #166534;
      font-weight: bold;
    }}
    .warning {{
      color: #b45309;
      font-weight: bold;
    }}
    .failed {{
      color: #991b1b;
      font-weight: bold;
    }}
  </style>
</head>
<body>
  <h1>{escape(report_title)}</h1>
  <div class="meta">Server: {escape(server)}:{port} | Checks: {len(results)}{expected_meta}</div>
  <h2>Status Summary</h2>
  <table class="sortable">
    <thead>
      <tr>
        <th>Status</th>
        <th data-type="number">Count</th>
        <th data-type="number">% of Total</th>
      </tr>
    </thead>
    <tbody>
      {summary_rows}
    </tbody>
  </table>
  <br>
  <table class="sortable">
    <thead>
      <tr>
        <th>Device</th>
        <th>Status</th>
        <th>Message</th>
        <th data-type="number">Mountpoints</th>
      </tr>
    </thead>
    <tbody>
      {"".join(rows)}
    </tbody>
  </table>
  <div class="meta" style="margin-top: 1rem;">
    Run Time (Local): {escape(run_local_text)}<br>
    Run Time (UTC): {escape(run_utc_text)}
  </div>
  <script>
    document.querySelectorAll("table.sortable").forEach((table) => {{
      const tbody = table.tBodies[0];
      if (!tbody) return;
      const sortDirections = {{}};
      table.querySelectorAll("thead th").forEach((header, columnIndex) => {{
        header.style.cursor = "pointer";
        header.addEventListener("click", () => {{
          const rows = Array.from(tbody.rows);
          const direction = sortDirections[columnIndex] === "asc" ? "desc" : "asc";
          sortDirections[columnIndex] = direction;
          const treatAsNumber = header.dataset.type === "number";
          rows.sort((a, b) => {{
            const aCell = a.cells[columnIndex];
            const bCell = b.cells[columnIndex];
            const aRaw = aCell.dataset.sort ?? aCell.textContent.trim();
            const bRaw = bCell.dataset.sort ?? bCell.textContent.trim();
            if (treatAsNumber) {{
              const aNum = Number(aRaw);
              const bNum = Number(bRaw);
              const comparison = (Number.isNaN(aNum) ? -Infinity : aNum) - (Number.isNaN(bNum) ? -Infinity : bNum);
              return direction === "asc" ? comparison : -comparison;
            }}
            const comparison = aRaw.localeCompare(bRaw, undefined, {{ sensitivity: "base" }});
            return direction === "asc" ? comparison : -comparison;
          }});
          rows.forEach((row) => tbody.appendChild(row));
        }});
      }});
    }});
  </script>
</body>
</html>
"""
    output_path.write_text(html, encoding="utf-8", newline="\n")


def resolve_output_html_path(input_file: Path, output_html: str | None) -> Path:
    if output_html:
        candidate = Path(output_html)
        if candidate.suffix.lower() != ".html":
            return Path(f"{candidate}.html")
        return candidate
    return input_file.with_suffix(".html")


def run_checks(
    server: str,
    port: int,
    users: Iterable[UserCredential],
    shared_password: str | None,
    timeout: float,
    log_status: bool,
    expected_mountpoints: int | None,
    base_connection: int,
) -> Tuple[list[CheckResult], int]:
    results: list[CheckResult] = []
    total = 0
    success_count = 0

    if log_status:
        print(f"Server: {server}:{port}")
        print("-" * 60)

    for user in users:
        total += 1
        password = shared_password or user.line_password
        if not password:
            result = CheckResult(
                display_name=user.display_name,
                username=user.username,
                status="Failed",
                message="missing password",
                source_table_items=None,
            )
            results.append(result)
            if log_status:
                print(f"[{result.display_name}] FAILED  | {result.message}")
            continue

        raw_status, message, items = fetch_source_table(
            server=server,
            port=port,
            username=user.username,
            password=password,
            timeout=timeout,
        )
        had_source_table = raw_status == "Success"
        status = raw_status

        if status == "Success" and expected_mountpoints is not None:
            if items == expected_mountpoints:
                status = "SUCCESS"
            else:
                warning_device_types = {
                    "SPS850",
                    "SPS851",
                    "SPS852",
                    "SPS855",
                    "R750",
                    "R750-2",
                }
                min_expected = expected_mountpoints - base_connection
                is_wm_gnss_receiver = user.device_type in warning_device_types
                if is_wm_gnss_receiver and min_expected <= items < expected_mountpoints:
                    status = "Warning"
                    message = (
                        "mountpoints mismatch: expected "
                        f"{expected_mountpoints}-{min_expected}, got {items}"
                    )
                else:
                    status = "Failed"
                    message = "mountpoints mismatch"
        elif status == "Success":
            status = "SUCCESS"

        result = CheckResult(
            display_name=user.display_name,
            username=user.username,
            status=status,
            message=message,
            source_table_items=items if had_source_table else None,
        )
        results.append(result)
        if status == "SUCCESS":
            success_count += 1

        if log_status:
            mountpoints_display = (
                str(result.source_table_items)
                if result.source_table_items is not None
                else "-"
            )
            print(
                f"[{result.display_name}] {result.status} | {result.message} | "
                f"Mountpoints: {mountpoints_display}"
            )

    exit_code = 0 if success_count == total else 1
    if log_status:
        print("-" * 60)
        print(f"Completed {total} checks, {success_count} successful.")
    return results, exit_code


def load_users(args: argparse.Namespace) -> tuple[list[UserCredential], Path]:
    if args.usernames_file:
        path = Path(args.usernames_file)
        return read_usernames(path), path

    if not args.org:
        raise ValueError("--org is required when using --wm-file.")

    wm_path = Path(args.wm_file)
    users = read_wm_users(
        path=wm_path,
        org=args.org,
        skip_header_validation=args.skip_wm_header_validation,
        include_non_licensed=args.include_non_licensed,
    )
    return users, wm_path


def main() -> int:
    args = parse_args()
    run_local = datetime.now().astimezone()
    run_utc = datetime.now(timezone.utc)
    server = resolve_server(args)
    users, input_path = load_users(args)
    shared_password = resolve_shared_password(args)
    shared_password = ensure_password_for_users(users, shared_password)
    output_html_path = resolve_output_html_path(
        input_file=input_path,
        output_html=args.output_html,
    )
    report_title = "NTRIP Check Report"
    if args.org:
        report_title = f"NTRIP Check Report - {args.org}"

    results, exit_code = run_checks(
        server=server,
        port=args.port,
        users=users,
        shared_password=shared_password,
        timeout=args.timeout,
        log_status=not args.no_progress,
        expected_mountpoints=args.expected,
        base_connection=args.base_connection,
    )
    write_html_report(
        output_path=output_html_path,
        report_title=report_title,
        server=server,
        port=args.port,
        results=results,
        expected_mountpoints=args.expected,
        base_connection=args.base_connection,
        run_local=run_local,
        run_utc=run_utc,
    )
    print(f"HTML report written to: {output_html_path}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
