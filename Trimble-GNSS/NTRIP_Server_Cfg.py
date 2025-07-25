#! /usr/bin/env python3

"""
This script allows for configuration of a Trimble GNSS receiver's NTRIR Server connections.
"""

import argparse
import logging
import logging.handlers
import os
from pprint import pprint
import requests
import sys

def setup_syslog_logging():
    """Configures and returns a logger that sends messages to syslog."""

    # Give our logger a name
    logger = logging.getLogger('API_Request_Logger')
    logger.setLevel(logging.INFO) # Set the minimum level of messages to log

    # Determine the syslog address based on the operating system
    if sys.platform == 'linux':
        # For most modern Linux systems
        address = '/dev/log'
    elif sys.platform == 'darwin':
        # For macOS
        address = '/var/run/syslog'
    elif sys.platform == 'win32':
        # For Windows, syslog is not native.
        # Requires a syslog server listening on UDP port 514.
        address = ('localhost', 514)
    else:
        # Fallback for other OSes
        address = ('localhost', 514)

    # Create the syslog handler
    try:
        handler = logging.handlers.SysLogHandler(address=address)
    except (ConnectionRefusedError, FileNotFoundError):
        print(f"Error: Could not connect to syslog at {address}.")
        print("On Windows, ensure a syslog server is running. On Linux/macOS, check permissions.")
        sys.exit(1)

    # Create a formatter and add it to the handler
    # This format includes the script name, log level, and message
    formatter = logging.Formatter('%(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)

    # Add the handler to the logger
    logger.addHandler(handler)

    return logger


def get_args():
    parser = argparse.ArgumentParser(
        description="A Python program to configure and run an NTRIP client.",
        # This line enables reading arguments from a file
        fromfile_prefix_chars='@'
    )

    # General Configuration
    parser.add_argument("--host", required=True, help="Host address of the device.")
    parser.add_argument("--port", default=80, type=int, help="Port of the device.")
    parser.add_argument("--user", required=True, help="User name for the device.")
    parser.add_argument("--password", required=True, help="Password for the device.")

    parser.add_argument("-v", "--verbose", help="Report verbose diags", action="store_true")
    parser.add_argument("--tell", help="Report from staging", action="store_true")


    # NTRIP Server Configuration
    parser.add_argument(
        "--ntrip-server-num",
        type=int,
        choices=[1, 2, 3],
        default=1,
        help="NTRIP server number to use (1-3).",
    )
    parser.add_argument(
        "--ntrip-mode",
        choices=["IBSS", "Normal"],
        default="IBSS",
        help="NTRIP operation mode.",
    )

    # NTRIP Caster Details (for up to 3 casters)
    group = parser.add_argument_group(f"NTRIP Server Options")
    group.add_argument(f"--caster_user", help=f"Username for NTRIP caste.")
    group.add_argument(f"--caster_password", help=f"Password for NTRIP caster.")
    group.add_argument(f"--caster_TLS", help=f"If TLS should be used")
    group.add_argument(f"--ibss_org", help=f"Org if in IBSS mode.")
    group.add_argument(f"--caster_ip", help=f"IP address or hostname of NTRIP caster in normal mode.")
    group.add_argument(f"--caster_port", type=int, help=f"Port of NTRIP caster in normal mode 2101 for non TLS, 2105 for TLS")

    # Mountpoint (conditionally required)
    parser.add_argument(
        "--mountpoint",
        help="Mountpoint for the NTRIP caster. Required if NTRIP mode is 'Normal'.",
    )

    parser.add_argument(
        "--format",
        choices=["CMR", "CMRx"],
        help="format for the stream to be sent to the NTRIP caster. ",
    )
    # Enable/Disable Switch
    status_group = parser.add_mutually_exclusive_group(required=True)
    status_group.add_argument("--enabled", action="store_true", help="Enable the NTRIP client.")
    status_group.add_argument("--disabled", action="store_true", help="Disable the NTRIP client.")

    args = parser.parse_args()
    return(args)



def main():
    """
    Main function to parse arguments and run the NTRIP client.
    """
    # Conditional requirement for mountpoint

    logger = setup_syslog_logging()



    args=get_args()

    host = getattr(args, f"host")
    port = getattr(args, f"port")

    user = getattr(args, f"user")
    password = getattr(args, f"password")

    caster_user = getattr(args, f"caster_user")
    caster_password = getattr(args, f"caster_password")
    caster_format = getattr(args, f"format")


    if args.ntrip_mode == "IBSS":
        caster_ip = None
        caster_port = None
        caster_TLS = True
        ibss_org= getattr(args, f"ibss_org")
    else:
        caster_TLS = getattr(args, f"caster_TLS")
        caster_ip = getattr(args, f"caster_ip")
        caster_port = getattr(args, f"caster_port")
        if caster_port == None:
            if caster_TLS:
                caster_port=2105
            else:
                caster_port=2101

    tell = getattr(args, f"tell")
    ntrip_server_num=getattr(args, f"ntrip_server_num")

    if ntrip_server_num == 1:
        io_port=31
    elif ntrip_server_num == 2:
        io_port=39
    elif ntrip_server_num == 3:
        io_port=40

    if args.format == "CMR":
        CMR_type=1 # CMR+
    else:
        CMR_type=6 # CMRx

    if tell:
        print(f"Configuring NTRIP client for host: {args.host}, port: {args.port}")
        print(f"Using NTRIP Caster: {args.ntrip_server_num}")
        print(f"Mode: {args.ntrip_mode}")


    if args.disabled:
        logger.info(f"NTRIP client is to be disabled. {host}:{port}")
#        request_URL="http://{}:{}/cgi-bin/io.xml?port=31&portType=NTripServe&useMices=on&ntripStdVersion=2&casterAddr=ibss%3A52101&sslEnableCheckbox=on&micesOrg=ibss&mountPoint=WESTMINSTER_2011&username=SPS855-5814R31542&fakePassword=0&password=Trimble&password2=Trimble&datatype=cmr&CMR=6
        request_URL="http://{}:{}/cgi-bin/io.xml?port={}&portType=NTripServer".format(host,port,io_port)
#        print(request_URL)

        try:
            # The `auth` parameter handles the Authorization header automatically
            response = requests.get(request_URL, auth=(user, password))

            # This will raise an exception if the status code is 4xx or 5xx
            response.raise_for_status()

            # If the request was successful
            logger.info("✅ Request Successful!")
            logger.info("Status Code:" +  str(response.status_code))
            logger.info("Response:" + response.text)

        except requests.exceptions.HTTPError as err:
            logger.error(f"❌ HTTP Error: {err} {host}:{port}")
            sys.exit(1)
        except requests.exceptions.RequestException as err:
            logger.error(f"❌ An error occurred: {err} {host}:{port}")
            sys.exit(1)

    if args.enabled:
        # Select the specified NTRIP caster's details
        if  not args.mountpoint:
            sys.exit("--mountpoint is required when --ntrip-mode is enabled")
#        pprint(args)

        if args.ntrip_mode == "Normal":
            if not all([caster_ip, caster_port, castet_user, caster_password,caster_TLS]):
                print(f"Error: All parameters [caster_ip, caster_port, ntrip_user, ntrip_password,caster_TLS] for the NTRIP server in normal connnection must be provided.")
                sys.exit(1)
        else:
            if not all([caster_user, caster_password,ibss_org]):
                print(f"Error: All parameters [ ntrip_user, ntrip_password,ibss_org] for the NTRIP server connnection in IBSS mode must be provided.")
                sys.exit(1)


        if args.ntrip_mode == "IBSS":
            request_URL="http://{}:{}/cgi-bin/io.xml?port={}&portType=NTripServer&ntripEnable=1&useMices=on&ntripStdVersion=2&casterAddr={}%3A52101&sslEnableCheckbox=on&micesOrg={}&mountPoint={}&username={}&fakePassword=0&password={}&password2={}datatype=cmr&CMR={}".\
                format(host,port,io_port,ibss_org,ibss_org,args.mountpoint,caster_user,caster_password,caster_password,CMR_type)
#            print(request_URL)

        try:
            # The `auth` parameter handles the Authorization header automatically
            logger.info(f"NTRIP client is to be enabled. {host}:{port}")
            response = requests.get(request_URL, auth=(user, password))

            # This will raise an exception if the status code is 4xx or 5xx
            response.raise_for_status()

            # If the request was successful
            logger.info("✅ Request Successful!")
            logger.info("Status Code:" + str(response.status_code))
            logger.info("Response:" + response.text)

        except requests.exceptions.HTTPError as err:
            logger.error(f"❌ HTTP Error: {err}  {host}:{port}")
            sys.exit(1)
        except requests.exceptions.RequestException as err:
            logger.error(f"❌ An error occurred: {err}  {host}:{port}")
            sys.exit(1)

if __name__ == "__main__":
    main()


"""
Enable
http://sps855.com/cgi-bin/io.xml?port=31&portType=NTripServer&ntripEnable=1&useMices=on&ntripStdVersion=2&casterAddr=ibss%3A52101&sslEnableCheckbox=on&micesOrg=ibss&mountPoint=WESTMINSTER_2011&username=SPS855-5814R31542&fakePassword=0&password=Trimble&password2=Trimble&datatype=cmr&CMR=6

Disable

<connected>1</connected>
<status>NtripStatusRunning</status>
<ibssExtErr>ExtendedErrCodeNotPresent</ibssExtErr>

<connected>0</connected>
<status>NtripStatusErr401Unauthorized</status>
<ibssExtErr>ExtendedErrCodeNotPresent</ibssExtErr>

"""
