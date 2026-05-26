#!/usr/bin/env -S python3 -u
"""
This is heavily based on the NtripPerlClient program written by BKG.
Then heavily based on a unavco original.

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

"""

import socket
import sys
import datetime
import base64
import time
import os
import json
import threading
from pathlib import Path
from pprint import pprint
#import ssl
#from optparse import OptionParser


import argparse


version=0.4
useragent="NTRIP JCMBsoftPythonClient/%.1f" % version
DEFAULT_CONFIG_PATH = Path.home() / ".ntripclient.json"

CONFIG_DEFAULTS = {
    "mountpoint": "",
    "caster": "",
    "port": None,
    "user": "IBS",
    "password": "IBS",
    "org": "",
    "baseorg": "",
    "lat": 39.56,
    "long": -105.5,
    "height": 1200.0,
    "GGA": False,
    "verbose": False,
    "Tell": False,
    "ssl": False,
    "ssl_cafile": "",
    "ssl_insecure": False,
    "host": False,
    "maxReconnect": 1,
    "UDP": None,
    "V2": False,
    "outputFile": "",
    "maxConnectTime": 0,
    "HTTP": "1.1",
    "headerOutput": False,
    "HeaderFile": "",
}

# reconnect parameter (fixed values):
factor=2 # How much the sleep time increases with each failed attempt
maxReconnect=1
maxReconnectTime=1200
sleepTime=1 # So the first one is 1 second



class NtripClient(object):
    def __init__(self,
                 buffer=5000,
                 user="",
                 out=sys.stdout,
                 port=None,
                 caster="",
                 mountpoint="",
                 host=False,
                 lat=46,
                 lon=122,
                 height=1212,
                 ssl=False,
                 ssl_cafile=None,
                 ssl_insecure=False,
                 verbose=False,
                 UDP_Port=None,
                 V2=False,
                 headerFile=sys.stderr,
                 headerOutput=False,
                 maxConnectTime=0,
                 GGA=False,
                 HTTP="1.1"
                 ):
        self.buffer=buffer
        self.user=base64.b64encode(bytes(user,'utf-8')).decode("utf-8")
#        print(self.user)
        self.out=out
        self.port=port
        self.caster=caster
        self.mountpoint=mountpoint
        self.setPosition(lat, lon)
        self.height=height
        self.verbose=verbose
        self.ssl=ssl
        self.ssl_cafile = ssl_cafile
        self.ssl_insecure = ssl_insecure
        self.host=host
        self.UDP_Port=UDP_Port
        self.V2=V2
        self.headerFile=headerFile
        self.headerOutput=headerOutput
        self.maxConnectTime=maxConnectTime
        self.GGA=GGA
        self.HTTP=HTTP

        self.socket=None

        if UDP_Port:
            self.UDP_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.UDP_socket.bind(('', 0))
            self.UDP_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        else:
            self.UDP_socket=None


    def setPosition(self, lat, lon):
        self.flagN="N"
        self.flagE="E"
        if lon>180:
            lon=(lon-360)*-1
            self.flagE="W"
        elif (lon<0 and lon>= -180):
            lon=lon*-1
            self.flagE="W"
        elif lon<-180:
            lon=lon+360
            self.flagE="E"
        else:
            self.lon=lon
        if lat<0:
            lat=lat*-1
            self.flagN="S"
        self.lonDeg=int(lon)
        self.latDeg=int(lat)
        self.lonMin=(lon-self.lonDeg)*60
        self.latMin=(lat-self.latDeg)*60

    def getMountPointBytes(self):
        if self.HTTP=="0.9":
            mountPointString = "GET %s \r\nUser-Agent: %s\r\nAuthorization: Basic %s\r\n" % (self.mountpoint, useragent, self.user)
        else:
            mountPointString = "GET %s HTTP/%s\r\nUser-Agent: %s\r\nAuthorization: Basic %s\r\n" % (self.mountpoint, self.HTTP, useragent, self.user)
#        mountPointString = "GET %s HTTP/1.1\r\nUser-Agent: %s\r\n" % (self.mountpoint, useragent)
        if self.host or self.V2:
           hostString = "Host: %s:%i\r\n" % (self.caster,self.port)
           mountPointString+=hostString
        if self.GGA and self.V2:
           GGAString = "Ntrip-GGA: %s" % (self.getGGABytes().decode('ascii'))
           mountPointString+=GGAString
        if self.V2:
           mountPointString+="Ntrip-Version: Ntrip/2.0\r\n"
        mountPointString+="\r\n"
        if self.verbose:
           print (mountPointString)
        return bytes(mountPointString,'ascii')

    def getGGABytes(self):
        now = datetime.datetime.utcnow()
        ggaString= "GPGGA,%02d%02d%04.2f,%02d%011.8f,%1s,%03d%011.8f,%1s,1,05,0.19,+00400,M,%5.3f,M,," % \
            (now.hour,now.minute,now.second,self.latDeg,self.latMin,self.flagN,self.lonDeg,self.lonMin,self.flagE,self.height)
        checksum = self.calcultateCheckSum(ggaString)
#        if self.verbose:
#            print  ("$%s*%s\r\n" % (ggaString, checksum))
        return bytes("$%s*%s\r\n" % (ggaString, checksum),'ascii')

    def calcultateCheckSum(self, stringToCheck):
        xsum_calc = 0
        for char in stringToCheck:
            xsum_calc = xsum_calc ^ ord(char)
        return "%02X" % xsum_calc

    def readData(self):
        reconnectTry=1
        sleepTime=1
        reconnectTime=0
        if self.maxConnectTime > 0 :
            EndConnect=datetime.timedelta(seconds=self.maxConnectTime)
        try:
            while reconnectTry<=maxReconnect:
                found_header=False
                if self.verbose:
                    sys.stderr.write('Connection {0} of {1}\n'.format(reconnectTry,maxReconnect))

                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                if self.ssl:
                    import ssl
                    if self.ssl_insecure:
                        context = ssl._create_unverified_context()
                    else:
                        context = ssl.create_default_context()
                        if self.ssl_cafile:
                            context.load_verify_locations(cafile=self.ssl_cafile)
                    self.socket = context.wrap_socket(
                        self.socket, server_hostname=self.caster
                    )
#                    self.socket=ssl.wrap_socket(self.socket)

                error_indicator = self.socket.connect_ex((self.caster, self.port))
                if error_indicator==0:
                    sleepTime = 1
                    connectTime=datetime.datetime.now()

                    self.socket.settimeout(10)
#                    self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 256)
                    self.socket.sendall(self.getMountPointBytes())
                    while not found_header:
                        casterResponse=self.socket.recv(40960) #Note that the is does not handle really large source tables.

#                        print(casterResponse)
                        header_lines = casterResponse.decode('utf-8').split("\r\n")

                        for line in header_lines:
                            if line=="":
                                if not found_header:
                                    found_header=True
                                    if self.verbose:
                                        sys.stderr.write("End Of Header"+"\n")
                            else:
                                if self.verbose:
                                    if found_header:
                                        sys.stderr.write("Body: " + line+"\n")
                                    else:
                                        sys.stderr.write("Header: " + line+"\n")
                            if self.headerOutput:
                                self.headerFile.write(line+"\n")




                        for line in header_lines:
                            if line.find("SOURCETABLE")>0:
                                if self.verbose:
                                    print(line)
                                sys.stderr.write("Mount point does not exist\n")
                                sys.exit(1)
                            elif line.find("401 Unauthorized")>=0:
                                sys.stderr.write("Unauthorized request\n")
                                sys.exit(1)
                            elif line.find("404 Not Found")>=0:
                                if self.verbose:
                                    print(header_lines)
                                sys.stderr.write("Mount Point does not exist\n")
                                sys.exit(2)
                            elif line.find("ICY 200 OK")>=0:
                                #Request was valid
                                if self.verbose:
                                    sys.stderr.write( "%s Connected to NtripCaster.\n" % (datetime.datetime.now()))

                                if self.GGA and not self.V2:
                                    gga=self.getGGABytes()
                                    if self.verbose:
                                        print  ("%s" % (gga.decode('ascii')))
                                    self.socket.sendall(gga)

                            elif line.find("HTTP/1.0 200 OK")>=0:
                                #Request was valid
                                if self.verbose:
                                    sys.stderr.write( "%s Connected to NtripCaster.\n" % (datetime.datetime.now()))
                                if self.GGA and not self.V2:
                                    gga=self.getGGABytes()
                                    if self.verbose:
                                        print  ("%s" % (gga.decode('ascii')))
                                    self.socket.sendall(gga)

                            elif line.find("HTTP/1.1 200 OK")>=0:
                                #Request was valid
                                if self.verbose:
                                    sys.stderr.write( "%s Connected to NtripCaster.\n" % (datetime.datetime.now()))
                                if self.GGA and not self.V2:
                                    gga=self.getGGABytes()
                                    if self.verbose:
                                        print  ("%s" % (gga.decode('ascii')))
                                    self.socket.sendall(gga)
                            else:
                                print(line)




                    data = "Initial data"
                    while data:
                        try:
#                            print("\nSleeping")
#                            time.sleep(0.01)
#                            print("\nSleep Finished. " + str(datetime.datetime.now()))
                            data=self.socket.recv(self.buffer)
                            if self.verbose:
                               sys.stderr.write("%s Data received: %s \n" % (datetime.datetime.now(), len(casterResponse)))

                            self.out.write(data)
#                            self.out.buffer.write(data)
                            if self.UDP_socket:
                                self.UDP_socket.sendto(data, ('<broadcast>', self.UDP_Port))
#                            print (datetime.datetime.now()-connectTime)
#                            print(self.maxConnectTime)
                            if self.maxConnectTime :
                                if datetime.datetime.now() > connectTime+EndConnect:
                                    if self.verbose:
                                        sys.stderr.write("Connection Time exceeded\n")
                                    sys.exit(0)
#                            self.socket.sendall(self.getGGAString())



                        except socket.timeout:
                            if self.verbose:
                                sys.stderr.write('Connection TimedOut\n')
                                sys.stderr.write( "%s Disconnected from NtripCaster.\n" % (datetime.datetime.now()))

                            data=False
                        except socket.error:
                            if self.verbose:
                                sys.stderr.write('Connection Error\n')
                            data=False

                    if self.verbose:
                        sys.stderr.write('Closing Connection\n')
                    self.socket.close()
                    self.socket=None

                    if reconnectTry < maxReconnect :
                        sys.stderr.write( "%s No Connection to NtripCaster.  Trying again in %i seconds\n" % (datetime.datetime.now(), sleepTime))
                        time.sleep(sleepTime)
                        sleepTime *= factor

                        if sleepTime>maxReconnectTime:
                            sleepTime=maxReconnectTime
                    else:
                        sys.exit(1)


                    reconnectTry += 1
                else:
                    self.socket=None
                    if self.verbose:
                        print ("Error indicator: ", error_indicator)

                    if reconnectTry < maxReconnect :
                        sys.stderr.write( "%s No Connection to NtripCaster.  Trying again in %i seconds\n" % (datetime.datetime.now(), sleepTime))
                        time.sleep(sleepTime)
                        sleepTime *= factor
                        if sleepTime>maxReconnectTime:
                            sleepTime=maxReconnectTime
                    reconnectTry += 1

        except KeyboardInterrupt:
            if self.socket:
                self.socket.close()
            sys.exit()

def load_config_file(path, require=False):
    config_path = Path(path).expanduser()
    if not config_path.exists():
        if require:
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        return {}

    with config_path.open("r", encoding="utf-8") as config_file:
        loaded = json.load(config_file)

    if not isinstance(loaded, dict):
        raise ValueError("Configuration file must contain a JSON object")

    # Accept the NtripClient constructor spelling too, but save using the CLI key.
    if "lon" in loaded and "long" not in loaded:
        loaded["long"] = loaded["lon"]

    return {key: loaded[key] for key in CONFIG_DEFAULTS if key in loaded}


def save_config_file(config, path):
    config_path = Path(path).expanduser()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    saved = {key: config.get(key, CONFIG_DEFAULTS[key]) for key in CONFIG_DEFAULTS}
    with config_path.open("w", encoding="utf-8") as config_file:
        json.dump(saved, config_file, indent=2, sort_keys=True)
        config_file.write("\n")
    return config_path


def config_arg_was_supplied(argv):
    return any(arg == "--config" or arg.startswith("--config=") for arg in argv)


def bool_value(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "y", "on")
    return bool(value)


def optional_string(value):
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def optional_int(value, field_name):
    value = optional_string(value)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an integer") from exc


def required_int(value, field_name):
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc


def required_float(value, field_name):
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a number") from exc


def normalize_config(config):
    normalized = CONFIG_DEFAULTS.copy()
    normalized.update({key: value for key, value in config.items() if key in CONFIG_DEFAULTS})

    for key in ("mountpoint", "caster", "user", "password", "org", "baseorg", "ssl_cafile", "outputFile", "HeaderFile"):
        value = optional_string(normalized.get(key))
        normalized[key] = value or ""

    normalized["port"] = optional_int(normalized.get("port"), "port")
    normalized["UDP"] = optional_int(normalized.get("UDP"), "UDP")
    normalized["maxReconnect"] = required_int(normalized.get("maxReconnect"), "maxReconnect")
    normalized["maxConnectTime"] = required_int(normalized.get("maxConnectTime"), "maxConnectTime")
    normalized["lat"] = required_float(normalized.get("lat"), "lat")
    normalized["long"] = required_float(normalized.get("long"), "long")
    normalized["height"] = required_float(normalized.get("height"), "height")

    for key in ("GGA", "verbose", "Tell", "ssl", "ssl_insecure", "host", "V2", "headerOutput"):
        normalized[key] = bool_value(normalized.get(key))

    if normalized["HTTP"] not in ("0.9", "1.0", "1.1"):
        raise ValueError('HTTP must be one of "0.9", "1.0", or "1.1"')

    if normalized["maxConnectTime"] < 0:
        raise ValueError("Max Connection Time must be >= 0")

    if normalized["maxReconnect"] < 1:
        raise ValueError("Reconnects must be >= 1")

    return normalized


def build_arg_parser():
    parser = argparse.ArgumentParser(
        description="NtripClient.py - A client for Ntrip casters.",
        epilog="NtripClient.py [options] mountpoint [caster] [port]\n"
               "Run with no arguments to open the GUI. Use --config to load saved parameters.",
        formatter_class=argparse.RawTextHelpFormatter,
        argument_default=argparse.SUPPRESS,
    )

    parser.add_argument('-V', '--version', action='version', version=f'%(prog)s {version}')
    parser.add_argument("--config", nargs="?", const=str(DEFAULT_CONFIG_PATH), metavar="FILE", help="Read parameters from FILE, or from the default config file if FILE is omitted.")
    parser.add_argument("--save-config", nargs="?", const=None, metavar="FILE", help="Save the effective parameters to FILE, or to the active config file if FILE is omitted.")

    parser.add_argument('mountpoint', nargs='?', type=str, help='The Ntrip mountpoint.')
    parser.add_argument('caster', nargs='?', type=str, help='The Ntripcaster hostname or IP address.')
    parser.add_argument('port', nargs='?', type=int, help='The Ntripcaster port number. Default of 2101')

    parser.add_argument("-u", "--user", type=str, help="The Ntripcaster username. Default: IBS")
    parser.add_argument("-p", "--password", type=str, help="The Ntripcaster password. Default: IBS")
    parser.add_argument("-o", "--org", type=str, help="Use IBSS and the provided organization for the user. Caster and Port are not needed in this case.")
    parser.add_argument("-b", "--baseorg", type=str, help="The org that the base is in. IBSS Only, assumed to be the user org.")
    parser.add_argument("-t", "--lat", type=float, help="Your latitude. Default: 39.56")
    parser.add_argument("--GGA", action="store_true", default=argparse.SUPPRESS, help="Enable GGA output.")
    parser.add_argument("--no-GGA", dest="GGA", action="store_false", default=argparse.SUPPRESS, help="Disable GGA output from a config file.")
    parser.add_argument("-g", "--long", type=float, help="Your longitude. Default: -105.5")
    parser.add_argument("-e", "--height", type=float, help="Your ellipsoid height. Default: 1200.0")
    parser.add_argument("-v", "--verbose", action="store_true", default=argparse.SUPPRESS, help="Enable verbose output.")
    parser.add_argument("--no-verbose", dest="verbose", action="store_false", default=argparse.SUPPRESS, help="Disable verbose output from a config file.")
    parser.add_argument("-T", "--Tell", action="store_true", default=argparse.SUPPRESS, help="Tell Settings.")
    parser.add_argument("--no-Tell", dest="Tell", action="store_false", default=argparse.SUPPRESS, help="Disable Tell output from a config file.")
    parser.add_argument("-s", "--ssl", action="store_true", default=argparse.SUPPRESS, help="Use SSL for the connection.")
    parser.add_argument("--no-ssl", dest="ssl", action="store_false", default=argparse.SUPPRESS, help="Disable SSL from a config file.")
    parser.add_argument("--ssl-cafile", type=str, metavar="PEM", help="Trust this CA bundle or server PEM when verifying TLS.")
    parser.add_argument("-k", "--ssl-insecure", action="store_true", default=argparse.SUPPRESS, help="Disable TLS certificate verification.")
    parser.add_argument("--ssl-secure", dest="ssl_insecure", action="store_false", default=argparse.SUPPRESS, help="Enable TLS certificate verification from a config file.")
    parser.add_argument("-H", "--host", action="store_true", default=argparse.SUPPRESS, help="Include host header; should be on for IBSS.")
    parser.add_argument("--no-host", dest="host", action="store_false", default=argparse.SUPPRESS, help="Disable host header from a config file.")
    parser.add_argument("-r", "--Reconnect", dest="maxReconnect", type=int, help="Number of reconnections. Default: 1")
    parser.add_argument("-D", "--UDP", type=int, help="Broadcast received data on the provided port.")
    parser.add_argument("-2", "--V2", action="store_true", default=argparse.SUPPRESS, help="Make a NTRIP V2 Connection.")
    parser.add_argument("--no-V2", dest="V2", action="store_false", default=argparse.SUPPRESS, help="Disable NTRIP V2 from a config file.")
    parser.add_argument("-f", "--outputFile", type=str, help="Write to this file, instead of stdout.")
    parser.add_argument("-m", "--maxtime", type=int, dest="maxConnectTime", help="Maximum length of the connection, in seconds. Default: 0")
    parser.add_argument('--HTTP', type=str, choices=['0.9', '1.0', '1.1'], help='Specify the HTTP protocol version.')
    parser.add_argument("--Header", action="store_true", dest="headerOutput", default=argparse.SUPPRESS, help="Write headers to stderr.")
    parser.add_argument("--no-Header", dest="headerOutput", action="store_false", default=argparse.SUPPRESS, help="Disable header output from a config file.")
    parser.add_argument("--HeaderFile", type=str, help="Write headers to this file, instead of stderr.")
    return parser


def apply_cli_options(config, options):
    for key in CONFIG_DEFAULTS:
        if hasattr(options, key):
            config[key] = getattr(options, key)
    return config


def build_ntrip_args(config):
    config = normalize_config(config)
    if not config["mountpoint"]:
        raise ValueError("A mountpoint is required. Provide one in the GUI, the config file, or the CLI.")

    ntripArgs = {
        "lat": config["lat"],
        "lon": config["long"],
        "height": config["height"],
        "host": config["host"],
        "GGA": config["GGA"],
        "ssl": config["ssl"],
        "ssl_cafile": optional_string(config["ssl_cafile"]) if config["ssl"] else None,
        "ssl_insecure": config["ssl_insecure"] if config["ssl"] else False,
        "V2": config["V2"],
        "verbose": config["verbose"],
        "headerOutput": config["headerOutput"],
        "maxConnectTime": config["maxConnectTime"],
        "HTTP": config["HTTP"],
    }

    mountpoint = config["mountpoint"]
    if mountpoint[0:1] != "/":
        mountpoint = "/" + mountpoint
    ntripArgs["mountpoint"] = mountpoint

    if config["org"]:
        if config["caster"]:
            raise ValueError("Caster should not be provided when using --org/IBSS mode")
        ntripArgs["user"] = config["user"] + "." + config["org"] + ":" + config["password"]
        if config["baseorg"]:
            ntripArgs["caster"] = config["baseorg"] + ".ibss.trimbleos.com"
        else:
            ntripArgs["caster"] = config["org"] + ".ibss.trimbleos.com"
        if config["port"] is None:
            ntripArgs["port"] = 52101 if config["ssl"] else 2101
        else:
            ntripArgs["port"] = config["port"]
        if not config["host"]:
            print("Warning: IBSS Mode without host header")
    else:
        if not config["caster"]:
            raise ValueError("A caster is required unless --org is provided")
        ntripArgs["user"] = config["user"] + ":" + config["password"]
        ntripArgs["caster"] = config["caster"]
        ntripArgs["port"] = 2101 if config["port"] is None else config["port"]

    if config["UDP"] is not None:
        ntripArgs["UDP_Port"] = config["UDP"]

    return ntripArgs, config


def print_connection_settings(ntripArgs, config):
    print("Server: " + ntripArgs["caster"])
    print("Port: " + str(ntripArgs["port"]))
    print("User: " + ntripArgs["user"])
    print("mountpoint: " + ntripArgs["mountpoint"])
    print("Reconnects: " + str(config["maxReconnect"]))
    print("Max Connect Time: " + str(config["maxConnectTime"]))
    print("Send GGA: " + str(ntripArgs["GGA"]))
    print("HTTP Version: " + ntripArgs["HTTP"])
    if ntripArgs["V2"]:
        print("NTRIP: V2")
    else:
        print("NTRIP: V1")
    if ntripArgs["ssl"]:
        print("SSL Connection")
    else:
        print("Uncrypted Connection")
    print("")


def run_client(config):
    global maxReconnect

    ntripArgs, config = build_ntrip_args(config)
    maxReconnect = config["maxReconnect"]

    if config["verbose"]:
        pprint(config)
    if config["verbose"] or config["Tell"]:
        print_connection_settings(ntripArgs, config)

    fileOutput = False
    headerFileOutput = False
    output_path = optional_string(config["outputFile"])
    header_path = optional_string(config["HeaderFile"])

    if output_path:
        f = open(Path(output_path).expanduser(), 'wb')
        ntripArgs['out'] = f
        fileOutput = True
    else:
        try:
            stdout = os.fdopen(sys.stdout.fileno(), "wb", closefd=False, buffering=0)
        except (AttributeError, OSError) as exc:
            raise ValueError("An output file is required when stdout is not available") from exc
        ntripArgs['out'] = stdout

    if header_path:
        h = open(Path(header_path).expanduser(), 'w')
        ntripArgs['headerFile'] = h
        ntripArgs['headerOutput'] = True
        headerFileOutput = True

    n = NtripClient(**ntripArgs)
    try:
        n.readData()
    finally:
        if fileOutput:
            f.close()
        if headerFileOutput:
            h.close()


def run_gui(config_path=DEFAULT_CONFIG_PATH):
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    config_path = Path(config_path).expanduser()
    config = CONFIG_DEFAULTS.copy()
    try:
        config.update(load_config_file(config_path))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Could not load config file {config_path}: {exc}", file=sys.stderr)

    root = tk.Tk()
    root.title("NtripClient")
    root.geometry("650x720")

    path_var = tk.StringVar(value=str(config_path))
    status_var = tk.StringVar(value="Enter connection parameters, then save or start the client.")

    container = ttk.Frame(root, padding=12)
    container.pack(fill="both", expand=True)

    path_frame = ttk.Frame(container)
    path_frame.pack(fill="x", pady=(0, 8))
    ttk.Label(path_frame, text="Config file").pack(side="left")
    path_entry = ttk.Entry(path_frame, textvariable=path_var)
    path_entry.pack(side="left", fill="x", expand=True, padx=8)

    def browse_config():
        selected = filedialog.asksaveasfilename(
            title="Choose config file",
            initialfile=Path(path_var.get()).name,
            defaultextension=".json",
            filetypes=(("JSON files", "*.json"), ("All files", "*.*")),
        )
        if selected:
            path_var.set(selected)

    ttk.Button(path_frame, text="Browse", command=browse_config).pack(side="left")

    canvas = tk.Canvas(container, highlightthickness=0)
    scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
    fields_frame = ttk.Frame(canvas)
    fields_frame.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=fields_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    text_fields = [
        ("mountpoint", "Mountpoint", "entry"),
        ("caster", "Caster", "entry"),
        ("port", "Port", "entry"),
        ("user", "User", "entry"),
        ("password", "Password", "password"),
        ("org", "IBSS organization", "entry"),
        ("baseorg", "IBSS base org", "entry"),
        ("lat", "Latitude", "entry"),
        ("long", "Longitude", "entry"),
        ("height", "Height", "entry"),
        ("maxReconnect", "Reconnects", "entry"),
        ("UDP", "UDP broadcast port", "entry"),
        ("maxConnectTime", "Max connection time", "entry"),
        ("HTTP", "HTTP version", "combo"),
        ("ssl_cafile", "SSL CA file", "file"),
        ("outputFile", "Output file", "savefile"),
        ("HeaderFile", "Header file", "savefile"),
    ]
    bool_fields = [
        ("GGA", "Send GGA"),
        ("verbose", "Verbose output"),
        ("Tell", "Print settings before connecting"),
        ("ssl", "Use SSL"),
        ("ssl_insecure", "Disable TLS verification"),
        ("host", "Include host header"),
        ("V2", "NTRIP V2"),
        ("headerOutput", "Write headers"),
    ]

    text_vars = {}
    bool_vars = {}

    def browse_file(var, save=False):
        if save:
            selected = filedialog.asksaveasfilename(title="Choose file")
        else:
            selected = filedialog.askopenfilename(title="Choose file")
        if selected:
            var.set(selected)

    for row, (key, label, field_type) in enumerate(text_fields):
        ttk.Label(fields_frame, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)
        value = config.get(key, "")
        var = tk.StringVar(value="" if value is None else str(value))
        text_vars[key] = var
        if field_type == "combo":
            widget = ttk.Combobox(fields_frame, textvariable=var, values=("0.9", "1.0", "1.1"), state="readonly")
        else:
            show = "*" if field_type == "password" else None
            widget = ttk.Entry(fields_frame, textvariable=var, show=show)
        widget.grid(row=row, column=1, sticky="ew", pady=4)
        if field_type in ("file", "savefile"):
            ttk.Button(fields_frame, text="Browse", command=lambda v=var, s=field_type == "savefile": browse_file(v, s)).grid(row=row, column=2, padx=(8, 0), pady=4)

    bool_start = len(text_fields)
    for index, (key, label) in enumerate(bool_fields):
        var = tk.BooleanVar(value=bool_value(config.get(key, False)))
        bool_vars[key] = var
        ttk.Checkbutton(fields_frame, text=label, variable=var).grid(row=bool_start + index, column=0, columnspan=3, sticky="w", pady=3)

    fields_frame.columnconfigure(1, weight=1)

    controls = ttk.Frame(root, padding=(12, 0, 12, 12))
    controls.pack(fill="x")
    ttk.Label(controls, textvariable=status_var).pack(fill="x", pady=(0, 8))

    def collect_config():
        collected = CONFIG_DEFAULTS.copy()
        for key, var in text_vars.items():
            value = var.get().strip()
            collected[key] = value if value else None
        for key, var in bool_vars.items():
            collected[key] = var.get()
        return normalize_config(collected)

    def save_from_gui():
        collected = collect_config()
        saved_path = save_config_file(collected, path_var.get())
        status_var.set(f"Saved settings to {saved_path}")
        return collected

    def start_from_gui():
        try:
            collected = save_from_gui()
            build_ntrip_args(collected)
        except Exception as exc:
            messagebox.showerror("NtripClient", str(exc))
            return

        start_button.configure(state="disabled")
        status_var.set("Client running...")

        def worker():
            try:
                run_client(collected)
                root.after(0, lambda: status_var.set("Client stopped."))
            except SystemExit as exc:
                code = exc.code
                root.after(0, lambda code=code: status_var.set(f"Client exited with code {code}."))
            except Exception as exc:
                error = str(exc)
                root.after(0, lambda error=error: messagebox.showerror("NtripClient", error))
                root.after(0, lambda: status_var.set("Client stopped with an error."))
            finally:
                root.after(0, lambda: start_button.configure(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    ttk.Button(controls, text="Save Settings", command=lambda: save_from_gui()).pack(side="left")
    start_button = ttk.Button(controls, text="Save and Start", command=start_from_gui)
    start_button.pack(side="left", padx=(8, 0))
    ttk.Button(controls, text="Quit", command=root.destroy).pack(side="right")

    root.mainloop()


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        run_gui()
        return 0

    parser = build_arg_parser()
    try:
        options = parser.parse_args(argv)
        config_path = Path(getattr(options, "config", DEFAULT_CONFIG_PATH)).expanduser()
        config = CONFIG_DEFAULTS.copy()
        if hasattr(options, "config"):
            config.update(load_config_file(config_path, require=True))
        config = apply_cli_options(config, options)

        if hasattr(options, "save_config"):
            save_config_file(normalize_config(config), options.save_config or config_path)

        run_client(config)
        return 0
    except FileNotFoundError as exc:
        parser.error(str(exc))
    except json.JSONDecodeError as exc:
        parser.error(f"Configuration file is not valid JSON: {exc}")
    except ValueError as exc:
        parser.error(str(exc))


def _legacy_main_unused():

    # Note: The 'usage' string is less crucial with argparse as it generates a good one automatically.
    # However, you can still customize it or format it if needed.
    # For now, let's leverage argparse's default usage generation.

    parser = argparse.ArgumentParser(
        description="NtripClient.py - A client for Ntrip casters.",
        epilog="NtripClient.py [options] mountpoint [caster] [port]  -- Connects to an Ntrip caster.\n"
               "Note: 'caster', 'port', are optional if --org is provided.",
        formatter_class=argparse.RawTextHelpFormatter
    )


    # Version argument (often handled directly by argparse)
    parser.add_argument(
        '-V', '--version', action='version', version=f'%(prog)s {version}'
    )

    # Positional Arguments
    parser.add_argument(
        'mountpoint',
        type=str,
        help='The Ntrip mountpoint.'
    )

    parser.add_argument(
        'caster',
        type=str,
        nargs='?',  # Makes it optional: 0 or 1 argument
        help='The Ntripcaster hostname or IP address.'
    )
    parser.add_argument(
        'port',
        type=int,
        nargs='?',  # Makes it optional: 0 or 1 argument
        help='The Ntripcaster port number. Default of 2101'
    )

    # Optional Arguments
    parser.add_argument(
        "-u", "--user",
        type=str,
        default="IBS",
        help="The Ntripcaster username. Default: %(default)s"
    )
    parser.add_argument(
        "-p", "--password",
        type=str,
        default="IBS",
        help="The Ntripcaster password. Default: %(default)s"
    )
    parser.add_argument(
        "-o", "--org",
        type=str,
        help="Use IBSS and the provided organization for the user. Caster and Port are not needed in this case."
        " Default: %(default)s (Note: optparse default was None, argparse default for missing is None unless specified)"
    )
    parser.add_argument(
        "-b", "--baseorg",
        type=str,
        help="The org that the base is in. IBSS Only, assumed to be the user org."
    )
    parser.add_argument(
        "-t", "--lat",
        type=float,
        default=39.56,
        help="Your latitude. Default: %(default).2f" # Added .2f for formatting float default
    )
    parser.add_argument(
        "--GGA",
        action="store_true",
        default=False,
        help="Enable GGA output."
    )
    parser.add_argument(
        "-g", "--long",
        type=float,
        default=-105.5,
        help="Your longitude. Default: %(default).1f" # Added .1f for formatting float default
    )
    parser.add_argument(
        "-e", "--height",
        type=float,
        default=1200.0, # Make sure default is float if type is float
        help="Your ellipsoid height. Default: %(default).1f"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        default=False,
        help="Enable verbose output."
    )
    parser.add_argument(
        "-T", "--Tell",
        action="store_true",
        default=False,
        help="Tell Settings."
    )
    parser.add_argument(
        "-s", "--ssl",
        action="store_true",
        default=False,
        help="Use SSL for the connection."
    )
    parser.add_argument(
        "--ssl-cafile",
        type=str,
        default=None,
        metavar="PEM",
        help="Trust this CA bundle or server PEM when verifying TLS (recommended for self-signed casters).",
    )
    parser.add_argument(
        "-k", "--ssl-insecure",
        action="store_true",
        default=False,
        help="Disable TLS certificate verification (insecure; use only for testing).",
    )
    parser.add_argument(
        "-H", "--host",
        action="store_true",
        default=False,
        help="Include host header; should be on for IBSS."
    )
    parser.add_argument(
        "-r", "--Reconnect",
        dest="maxReconnect",
        type=int,
        default=1,
        help="Number of reconnections. Default: %(default)s"
    )
    parser.add_argument(
        "-D", "--UDP",
        type=int,
        default=None,
        help="Broadcast received data on the provided port."
    )
    parser.add_argument(
        "-2", "--V2",
        action="store_true",
        default=False,
        help="Make a NTRIP V2 Connection."
    )
    parser.add_argument(
        "-f", "--outputFile",
        type=str,
        default=None,
        help="Write to this file, instead of stdout."
    )
    parser.add_argument(
        "-m", "--maxtime",
        type=int,
        dest="maxConnectTime",
        default=0,
        help="Maximum length of the connection, in seconds. Default: %(default)s"
    )
    parser.add_argument(
        '--HTTP',
        type=str,  # Specify the type as string
        choices=['0.9', '1.0', '1.1'],  # Define the allowed choices as strings
        default='1.1',  # Set the default value as a string
        help='Specify the HTTP protocol version (choices: "0.9", "1.0", "1.1", default: "%(default)s")'
    )
    parser.add_argument(
        "--Header",
        action="store_true",
        dest="headerOutput",
        default=False,
        help="Write headers to stderr."
    )
    parser.add_argument(
        "--HeaderFile",
        type=str,
        default=None,
        help="Write headers to this file, instead of stderr."
    )

    # Parse the arguments
    options = parser.parse_args()
    if options.verbose:
        pprint(options)

# You can now access your arguments like:
# print(f"Caster: {args.caster}")
# print(f"Port: {args.port}")
# print(f"Mountpoint: {args.mountpoint}")
# print(f"User: {args.user}")
# print(f"HTTP Version: {args.HTTP}")    (options, args) = parser.parse_args()
    ntripArgs = {}
    ntripArgs['lat']=options.lat
    ntripArgs['lon']=options.long
    ntripArgs['height']=options.height
    ntripArgs['host']=options.host
    ntripArgs['GGA']=options.GGA


    if options.ssl:
        ntripArgs['ssl']=True
        ntripArgs['ssl_cafile'] = options.ssl_cafile
        ntripArgs['ssl_insecure'] = options.ssl_insecure
    else:
        ntripArgs['ssl']=False
        ntripArgs['ssl_cafile'] = None
        ntripArgs['ssl_insecure'] = False

    if options.org:
        if options.caster != None :
            print ("Incorrect number of arguments for IBSS. You do not need to provide the server and port\n")
            parser.print_help()
            sys.exit(1)
        ntripArgs['user']=options.user+"."+options.org + ":" + options.password
        if options.baseorg:
            ntripArgs['caster']=options.baseorg + ".ibss.trimbleos.com"
        else:
            ntripArgs['caster']=options.org + ".ibss.trimbleos.com"

        if options.port == None:
            if options.ssl :
                ntripArgs['port']=52101
            else :
                ntripArgs['port']=2101
        else:
            ntripArgs['port']=options.port
        ntripArgs['mountpoint']=options.mountpoint
        if options.host == False:
            print("Warning: IBSS Mode without host header")

    else:
        if options.caster == None:
            print ("Incorrect number of arguments for NTRIP\n")
            parser.print_help()
            sys.exit(1)
        ntripArgs['user']=options.user+":"+options.password
        ntripArgs['caster']=options.caster
        if options.port == None:
            ntripArgs['port']=2101
        else:
            ntripArgs['port']=options.port
        ntripArgs['mountpoint']=options.mountpoint

    if ntripArgs['mountpoint'][0:1] !="/":
        ntripArgs['mountpoint'] = "/"+ntripArgs['mountpoint']

    ntripArgs['V2']=options.V2

    ntripArgs['verbose']=options.verbose
    ntripArgs['headerOutput']=options.headerOutput
    ntripArgs['maxConnectTime']=options.maxConnectTime

    if options.UDP:
         ntripArgs['UDP_Port']=int(options.UDP)

    maxReconnect=options.maxReconnect
    maxConnectTime=options.maxConnectTime
    ntripArgs['HTTP']=options.HTTP

    if maxConnectTime < 0:
        sys.stderr.write("Max Connection Time must be >= 0\n")
        sys.exit(1)


    if options.verbose or options.Tell:
        print ("Server: " + ntripArgs['caster'])
        print ("Port: " + str(ntripArgs['port']))
        print ("User: " + ntripArgs['user'])
        print ("mountpoint: " +ntripArgs['mountpoint'])
        print ("Reconnects: " + str(maxReconnect))
        print ("Max Connect Time: " + str (maxConnectTime))
        print ("Send GGA: " + str (ntripArgs['GGA']))
        print ("HTTP Version: " + (ntripArgs['HTTP']))
        if ntripArgs['V2']:
            print ("NTRIP: V2")
        else:
            print ("NTRIP: V1")
        if ntripArgs["ssl"]:
            print ("SSL Connection")
        else:
            print ("Uncrypted Connection")
        print ("")



    fileOutput=False

    if options.outputFile:
        f = open(options.outputFile, 'wb')
        ntripArgs['out']=f
        fileOutput=True
    else:
        stdout= os.fdopen(sys.stdout.fileno(), "wb", closefd=False,buffering=0)
        ntripArgs['out']=stdout

    if options.HeaderFile:
        h = open(options.HeaderFile, 'w')
        ntripArgs['headerFile']=h
        ntripArgs['headerOutput']=True

    n = NtripClient(**ntripArgs)
    try:
        n.readData()
    finally:
        if fileOutput:
            f.close()
        if options.HeaderFile:
            h.close()


if __name__ == '__main__':
    sys.exit(main())
