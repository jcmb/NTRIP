#! /usr/bin/env python3

"""
Configure a Trimble GNSS receiver's built-in NTRIP Caster (io.xml NTripCaster),
not an outbound NTRIP Server connection.
"""

import argparse
import logging
import logging.handlers
import sys
from urllib.parse import quote

import requests

# NTRIP caster slot 1–3 maps to io.xml port=32–34.
NTRIP_CASTER_NUM_TO_IO_PORT = {1: 32, 2: 33, 3: 34}

# Enable query: shared prefix/suffix from device web UI; middle differs by format.
# Placeholders: {port}, {casterPort}, {mountPoint} (mountPoint URL-encoded by caller).
NTRIP_CASTER_ENABLE_PREFIX = (
    "port={port}&portType=NTripCaster&ntripEnable=1&casterPort={casterPort}"
    "&identifier=&country=&mountPoint={mountPoint}&"
)

# CMR / CMRx / RTCM3 — see device io.xml (CMR=1, CMR=6, or RTCM primary).
NTRIP_CASTER_ENABLE_MIDDLE_BY_FORMAT = {
    "CMRx": (
        "datatype=cmr&CMR=6&CMRDelay=0&BWLimit=0&datatype=rtcm&RTCM=0&rtcmversion=1"
        "&rtcmtype2=1&rtcmtype3=0&rtcmtype=1&rtcmType1019Period=&rtcmType1020Period="
    ),
    "CMR": (
        "datatype=cmr&CMR=1&CMRDelay=0&BWLimit=0&datatype=rtcm&RTCM=0&rtcmversion=1"
        "&rtcmtype2=1&rtcmtype3=0&rtcmtype=1&rtcmType1019Period=&rtcmType1020Period="
    ),
    "RTCM3": (
        "datatype=cmr&CMR=0&CMRDelay=0&BWLimit=0&datatype=rtcm&RTCM=1&rtcmversion=6"
        "&rtcmtype2=1&rtcmtype3=0&rtcmtype=0&rtcmType1019Period=120000"
        "&rtcmType1020Period=120000"
    ),
}

NTRIP_CASTER_ENABLE_TAIL = (
    "RtcmBWLimit=0&rtcmIodeHoldoff=0&rtcmType1Period=1000&rtcmType31Period=0"
    "&rtcmType3Period=10000&rtcmType32Period=0&rtcmType9Enable=on&glonassDatumMenu=0"
    "&rtcmType2Enable=on&rtcmOtherRecsEnable=on&L2P_L2CPrefVer2=0"
    "&rtcmType1004Period=1000&rtcmType1012Period=1000&rtcmType1019PeriodV3X=0"
    "&rtcmType1020PeriodV3X=0&rtcmBaseRecords=on&L2P_L2CPrefVer3=0&MSMMenu=3"
    "&rtcmTypeMsmPeriod=1000&enableGps=on&rtcmType1019PeriodV32=120000"
    "&enableGlonass=on&rtcmType1020PeriodV32=120000&enableGalileo=on"
    "&rtcmType1045Period=120000&rtcmType1046Period=120000&enableQzss=on"
    "&rtcmType1044Period=120000&enableBeidou=on&rtcmType1042Period=120000"
    "&enableIrnss=on&rtcmType1041Period=120000&LBANDRAWC4=0&OK=1"
)


def ntrip_caster_enable_query(stream_format: str) -> str:
    middle = NTRIP_CASTER_ENABLE_MIDDLE_BY_FORMAT[stream_format]
    return NTRIP_CASTER_ENABLE_PREFIX + middle + "&" + NTRIP_CASTER_ENABLE_TAIL


def setup_syslog_logging():
    """Configures and returns a logger that sends messages to syslog."""

    logger = logging.getLogger("API_Request_Logger")
    logger.setLevel(logging.INFO)

    if sys.platform == "linux":
        address = "/dev/log"
    elif sys.platform == "darwin":
        address = "/var/run/syslog"
    elif sys.platform == "win32":
        address = ("localhost", 514)
    else:
        address = ("localhost", 514)

    try:
        handler = logging.handlers.SysLogHandler(address=address)
    except (ConnectionRefusedError, FileNotFoundError):
        print(f"Error: Could not connect to syslog at {address}.")
        print(
            "On Windows, ensure a syslog server is running. "
            "On Linux/macOS, check permissions."
        )
        sys.exit(1)

    formatter = logging.Formatter("%(name)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger


def get_args():
    parser = argparse.ArgumentParser(
        description="Configure the receiver's NTRIP Caster via io.xml.",
        fromfile_prefix_chars="@",
    )

    parser.add_argument("--host", required=True, help="Host address of the device.")
    parser.add_argument(
        "--port",
        default=443,
        type=int,
        help="HTTP(S) port of the device web interface (default 443).",
    )
    parser.add_argument(
        "--scheme",
        choices=["http", "https"],
        default="https",
        help="URL scheme for the device (default https).",
    )
    parser.add_argument(
        "--user",
        default="admin",
        help="User name for the device web interface (default admin).",
    )
    parser.add_argument("--password", required=True, help="Password for the device.")

    parser.add_argument("-v", "--verbose", help="Verbose diagnostics", action="store_true")
    parser.add_argument("--tell", help="Print what would be configured", action="store_true")

    parser.add_argument(
        "--ntrip-caster-num",
        type=int,
        choices=[1, 2, 3],
        default=2,
        help="NTRIP caster slot (1–3); uses io.xml port 32–34 respectively (default 2 → port 33).",
    )
    parser.add_argument(
        "--caster-port",
        type=int,
        default=None,
        help=(
            "NTRIP caster TCP port. With --enabled, defaults to 2102 if omitted. "
            "With --disabled, included in the request only if you pass this option "
            "(omitted otherwise, so the device is not sent casterPort=0)."
        ),
    )
    parser.add_argument(
        "--mountpoint",
        help="Mount point name for the caster (required with --enabled).",
    )
    parser.add_argument(
        "--format",
        dest="stream_format",
        choices=["CMR", "CMRx", "RTCM3"],
        default="CMRx",
        help="Caster stream format: CMR, CMRx, or RTCM3 (default CMRx).",
    )

    status_group = parser.add_mutually_exclusive_group(required=True)
    status_group.add_argument("--enabled", action="store_true", help="Enable the NTRIP caster.")
    status_group.add_argument("--disabled", action="store_true", help="Disable the NTRIP caster.")

    return parser.parse_args()


def device_base_url(args):
    return f"{args.scheme}://{args.host}:{args.port}"


def io_port_for_caster_num(caster_num: int) -> int:
    return NTRIP_CASTER_NUM_TO_IO_PORT[caster_num]


def main():
    logger = setup_syslog_logging()
    args = get_args()

    user = args.user
    password = args.password
    base = device_base_url(args)

    io_port = io_port_for_caster_num(args.ntrip_caster_num)
    caster_port_effective = (
        args.caster_port if args.caster_port is not None else 2102
    )

    if args.tell:
        print(f"NTRIP Caster config for {base}")
        cp_note = (
            args.caster_port
            if args.caster_port is not None
            else "(default 2102 for enable only)"
        )
        print(
            f"ntrip-caster-num={args.ntrip_caster_num} io.xml port={io_port} "
            f"caster-tcp-port={cp_note} format={args.stream_format}"
        )

    if args.disabled:
        disable_q = f"port={io_port}&portType=NTripCaster"
        if args.caster_port is not None:
            disable_q += f"&casterPort={args.caster_port}"
        request_url = f"{base}/cgi-bin/io.xml?{disable_q}"
        if args.tell:
            print(f"Disable GET: {request_url}")
        logger.info("NTRIP caster disable %s", request_url)
        try:
            response = requests.get(request_url, auth=(user, password), timeout=60)
            response.raise_for_status()
            logger.info("Request successful status=%s", response.status_code)
            logger.info("Response: %s", response.text)
        except requests.exceptions.HTTPError as err:
            logger.error("HTTP error: %s", err)
            sys.exit(1)
        except requests.exceptions.RequestException as err:
            logger.error("Request error: %s", err)
            sys.exit(1)
        return

    if args.enabled:
        if not args.mountpoint:
            sys.exit("--mountpoint is required when using --enabled")

        mount_enc = quote(args.mountpoint, safe="")
        query = ntrip_caster_enable_query(args.stream_format).format(
            port=io_port,
            casterPort=caster_port_effective,
            mountPoint=mount_enc,
        )
        request_url = f"{base}/cgi-bin/io.xml?{query}"
        if args.tell:
            print(f"Enable GET: {request_url}")
        logger.info("NTRIP caster enable %s", request_url)
        try:
            response = requests.get(request_url, auth=(user, password), timeout=120)
            response.raise_for_status()
            logger.info("Request successful status=%s", response.status_code)
            logger.info("Response: %s", response.text)
        except requests.exceptions.HTTPError as err:
            logger.error("HTTP error: %s", err)
            sys.exit(1)
        except requests.exceptions.RequestException as err:
            logger.error("Request error: %s", err)
            sys.exit(1)


if __name__ == "__main__":
    main()
