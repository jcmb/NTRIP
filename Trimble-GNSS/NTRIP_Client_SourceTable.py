#! /usr/bin/env python3

import requests
import argparse
from urllib.parse import urlencode, urlunsplit

import time

def get_mount_points_xml(
    server: str,
    password: str,
    device_id: str,
    device_password: str,
    org: str,
    use_ssl: bool,
    port: int = 80,
    admin_user: str = "admin",
    caster: int = 1,
    timeout: int = 30
):
    """
    Makes an HTTP GET request to retrieve XML data for NTRIP mount points.

    Args:
        server (str): The server hostname or IP address.
        password (str): The admin password.
        device_id (str): The device ID to be used in the request.
        device_password (str): The device password for authentication.
        org (str): The organization name for MICES.
        use_ssl (bool): Whether to use HTTPS (True) or HTTP (False).
        port (int, optional): The server port. Defaults to 80.
        admin_user (str, optional): The admin username. Defaults to "admin".
        caster (int, optional): The caster number (portId). Must be 1, 2, or 3. Defaults to 1.
        timeout (int, optional): The request timeout in seconds. Defaults to 30.

    Returns:
        str: The XML response text if the request is successful, otherwise an error message.
    """
    # Ensure caster is within the valid range
    if caster not in [1, 2, 3]:
        return "Error: 'caster' parameter must be an integer between 1 and 3."

    # Determine the scheme (http or https)
    scheme = "http"
#    scheme = "https" if host_ssl else "http"

    # The base path for the API endpoint
    path = "/xml/dynamic/getMountPoints.xml"

    # Construct the query parameters.
    # The example URL suggests a different user and password parameter structure than what's in the prompt.
    # Based on the URL example '/xml/dynamic/getMountPoints.xml?user=...&password=...&portId=...'
    # we'll map the prompt's device_id and device_password to these parameters.
    query_params = {
        'user': device_id,
        'password': device_password,
        'portId': caster+29,  # Corresponds to the caster number
        'useSsl': 1 if use_ssl else 0,
        'useMices': 1,
        'micesOrg': org,
    }

    # Encode the parameters to create the query string
    query_string = urlencode(query_params)

    # Combine the parts to form the full URL
    # The port is only included if it's not the default for the protocol
    netloc = server
    netloc += f":{port}"

    full_url = urlunsplit((scheme, netloc, path, query_string, ""))

    print(f"Making request to URL: {full_url}")

    try:
        # Make the GET request with the specified timeout
        start_time = time.time()
        response = requests.get(full_url, timeout=timeout)
        response.raise_for_status()  # Raises an HTTPError for bad responses (4xx or 5xx)

        # Record the end time
        end_time = time.time()

        # Calculate and print the duration
        duration = end_time - start_time
        print(f"Request to {full_url} took {duration:.2f} seconds.")

        # Return the XML content
        return response.text

    except requests.exceptions.HTTPError as err:
        return f"HTTP Error: {err}\nResponse content: {response.text}"
    except requests.exceptions.RequestException as err:
        return f"Request Error: {err}"

def getArgs():
    parser = argparse.ArgumentParser(description='Retrieve NTRIP mount points from a server.')

    # Define the command-line arguments
    parser.add_argument('server', type=str, help='The server hostname or IP address.')
    parser.add_argument('--port', type=int, default=80, help='The server port. Defaults to 80.')
    parser.add_argument('--admin-user', type=str, default='admin', help='Admin username. Defaults to "admin".')
    parser.add_argument('--password', type=str, required=True, help='Admin password.')
    parser.add_argument('--device-id', type=str, required=True, help='The device ID.')
    parser.add_argument('--device-password', type=str, required=True, help='The device password.')
    parser.add_argument('--org', type=str, required=True, help='The organization name for IBSS.')
    parser.add_argument('--use-ssl', action='store_true', help='Use HTTPS for the IBSS request.')
    parser.add_argument('--client', type=int, choices=[1, 2, 3], default=1, help='client number (portId) in the range 1-3. Defaults to 1.')
    parser.add_argument('--timeout', type=int, default=30, help='Request timeout in seconds. Defaults to 30.')

    # Parse the arguments from the command line
    args = parser.parse_args()

    return(args)

def main():
    args=getArgs()

    xml_data = get_mount_points_xml(
        server=args.server,
        password=args.password,
        device_id=args.device_id,
        device_password=args.device_password,
        org=args.org,
        use_ssl=args.use_ssl,
        port=args.port,
        admin_user=args.admin_user,
        caster=args.client,
        timeout=args.timeout
    )
    print("\n--- Response from Server ---")
    print(xml_data)


if __name__ == "__main__":
    # Initialize the argument parser
    # Call the main function with the parsed arguments
    main()

