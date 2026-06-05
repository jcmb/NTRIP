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


version=2.0
useragent="NTRIP JCMBsoftPythonClient/%.1f" % version
DEFAULT_CONFIG_PATH = Path.home() / "ntripclient.ntrip"
LAST_CONFIG_PATH_FILE = Path.home() / ".ntripclient-last.json"

CONFIG_DEFAULTS = {
    "mountpoint": "",
    "caster": "SPS855.com",
    "port": 2101,
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
    "ssl_insecure": True,
    "host": False,
    "maxReconnect": 1,
    "UDP": None,
    "V2": True,
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


class ChunkedDecodeError(ValueError):
    pass


class ChunkedDecoder:
    def __init__(self):
        self.buffer = bytearray()
        self.chunk_size = None
        self.done = False

    def feed(self, data):
        if self.done:
            return []

        if data:
            self.buffer.extend(data)

        decoded = []
        while True:
            if self.chunk_size is None:
                line_end = self.buffer.find(b"\r\n")
                if line_end < 0:
                    if self.buffer and chr(self.buffer[0]).lower() not in "0123456789abcdef":
                        raise ChunkedDecodeError("chunked stream did not start with a chunk size")
                    if len(self.buffer) > 128:
                        raise ChunkedDecodeError("chunk size line was too long")
                    break

                line = bytes(self.buffer[:line_end])
                del self.buffer[:line_end + 2]
                size_text = line.split(b";", 1)[0].strip()
                if not size_text:
                    raise ChunkedDecodeError("empty chunk size")
                try:
                    self.chunk_size = int(size_text, 16)
                except ValueError as exc:
                    raise ChunkedDecodeError(f"invalid chunk size: {size_text!r}") from exc

                if self.chunk_size == 0:
                    self.done = True
                    return decoded

            if len(self.buffer) < self.chunk_size + 2:
                break

            chunk = bytes(self.buffer[:self.chunk_size])
            separator = bytes(self.buffer[self.chunk_size:self.chunk_size + 2])
            if separator != b"\r\n":
                raise ChunkedDecodeError("chunk was not followed by CRLF")

            decoded.append(chunk)
            del self.buffer[:self.chunk_size + 2]
            self.chunk_size = None

        return decoded



class TransferProgress:
    def __init__(self):
        self.reset()

    def reset(self):
        self.total_bytes = 0
        self.start_time = None
        self.last_sample_time = None
        self.last_sample_bytes = 0
        self.rate = 0.0

    def add(self, nbytes):
        now = time.monotonic()
        if self.start_time is None:
            self.start_time = now
            self.last_sample_time = now
            self.last_sample_bytes = 0
        self.total_bytes += nbytes
        elapsed = now - self.last_sample_time
        if elapsed >= 0.5:
            self.rate = (self.total_bytes - self.last_sample_bytes) / elapsed
            self.last_sample_time = now
            self.last_sample_bytes = self.total_bytes

    def snapshot(self):
        now = time.monotonic()
        elapsed = (now - self.start_time) if self.start_time else 0.0
        return self.total_bytes, elapsed, self.rate


def format_data_size(num_bytes, decimals=1):
    if num_bytes < 1024:
        return f"{int(round(num_bytes))} B"
    size = float(num_bytes)
    for unit in ("KiB", "MiB", "GiB", "TiB"):
        size /= 1024.0
        if size < 1024:
            if decimals == 0:
                return f"{int(round(size))} {unit}"
            return f"{size:.{decimals}f} {unit}"
    if decimals == 0:
        return f"{int(round(size))} PiB"
    return f"{size:.{decimals}f} PiB"


def format_elapsed(seconds):
    total_seconds = int(seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_progress_line(total_bytes, elapsed_seconds, rate_bytes_per_second):
    return (
        f"{format_data_size(total_bytes)}  "
        f"{format_elapsed(elapsed_seconds)}  "
        f"[{format_data_size(rate_bytes_per_second, decimals=0)}/s]"
    )


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
                 HTTP="1.1",
                 stop_event=None,
                 progress_callback=None,
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
        self.stop_event = stop_event
        self.progress_callback = progress_callback

        self.socket=None

        if UDP_Port:
            self.UDP_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.UDP_socket.bind(('', 0))
            self.UDP_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        else:
            self.UDP_socket=None

    def stop(self):
        if self.stop_event:
            self.stop_event.set()
        if self.socket:
            try:
                self.socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self.socket.close()
            except OSError:
                pass
            self.socket=None

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
           sys.stderr.write(mountPointString)
        if self.headerOutput:
           self.headerFile.write(">>> NTRIP request\n")
           self.headerFile.write(mountPointString)
        return bytes(mountPointString,'ascii')

    def getGGABytes(self):
        now = datetime.datetime.now(datetime.UTC)
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
            while reconnectTry<=maxReconnect and not self.should_stop():
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
                    header_buffer = bytearray()
                    initial_body = b""
                    chunked_response = False
                    while not found_header and not self.should_stop():
                        try:
                            casterResponse=self.socket.recv(40960) #Note that the is does not handle really large source tables.
                        except OSError:
                            if self.should_stop():
                                return
                            raise

                        if not casterResponse:
                            break

                        header_buffer.extend(casterResponse)
                        header_end = header_buffer.find(b"\r\n\r\n")
                        separator_length = 4
                        if header_end < 0:
                            header_end = header_buffer.find(b"\n\n")
                            separator_length = 2
                        if header_end < 0:
                            first_line_end = header_buffer.find(b"\r\n")
                            separator_length = 2
                            if first_line_end < 0:
                                first_line_end = header_buffer.find(b"\n")
                                separator_length = 1
                            if first_line_end >= 0 and bytes(header_buffer[:first_line_end]).startswith(b"ICY 200 OK"):
                                header_end = first_line_end
                            else:
                                continue

                        found_header=True
                        header_bytes = bytes(header_buffer[:header_end])
                        initial_body = bytes(header_buffer[header_end + separator_length:])
                        header_text = header_bytes.decode('utf-8', errors='replace')
                        header_lines = header_text.replace("\r\n", "\n").split("\n")
                        chunked_response = any(
                            line.lower().startswith("transfer-encoding:")
                            and "chunked" in line.lower()
                            for line in header_lines
                        )

                        for line in header_lines:
                            if self.verbose:
                                sys.stderr.write("Header: " + line+"\n")
                            if self.headerOutput:
                                self.headerFile.write(line+"\n")
                        if self.verbose:
                            sys.stderr.write("End Of Header"+"\n")
                        if self.headerOutput:
                            self.headerFile.write("\n")




                        for line in header_lines:
                            if line.find("SOURCETABLE")>0:
                                if self.verbose:
                                    sys.stderr.write(line+"\n")
                                sys.stderr.write("Mount point does not exist\n")
                                sys.exit(1)
                            elif line.find("401 Unauthorized")>=0:
                                sys.stderr.write("Unauthorized request\n")
                                sys.exit(1)
                            elif line.find("404 Not Found")>=0:
                                if self.verbose:
                                    sys.stderr.write(str(header_lines)+"\n")
                                sys.stderr.write("Mount Point does not exist\n")
                                sys.exit(2)
                            elif line.find("ICY 200 OK")>=0:
                                #Request was valid
                                if self.verbose:
                                    sys.stderr.write( "%s Connected to NtripCaster.\n" % (datetime.datetime.now()))

                                if self.GGA and not self.V2:
                                    gga=self.getGGABytes()
                                    if self.verbose:
                                        sys.stderr.write("%s" % (gga.decode('ascii')))
                                    self.socket.sendall(gga)

                            elif line.find("HTTP/1.0 200 OK")>=0:
                                #Request was valid
                                if self.verbose:
                                    sys.stderr.write( "%s Connected to NtripCaster.\n" % (datetime.datetime.now()))
                                if self.GGA and not self.V2:
                                    gga=self.getGGABytes()
                                    if self.verbose:
                                        sys.stderr.write("%s" % (gga.decode('ascii')))
                                    self.socket.sendall(gga)

                            elif line.find("HTTP/1.1 200 OK")>=0:
                                #Request was valid
                                if self.verbose:
                                    sys.stderr.write( "%s Connected to NtripCaster.\n" % (datetime.datetime.now()))
                                if self.GGA and not self.V2:
                                    gga=self.getGGABytes()
                                    if self.verbose:
                                        sys.stderr.write("%s" % (gga.decode('ascii')))
                                    self.socket.sendall(gga)




                    decoder = ChunkedDecoder() if chunked_response else None
                    decode_failed = False

                    def write_stream_data(stream_data):
                        if not stream_data:
                            return
                        if self.progress_callback:
                            self.progress_callback(len(stream_data))
                        self.out.write(stream_data)
                        if self.UDP_socket:
                            self.UDP_socket.sendto(stream_data, ('<broadcast>', self.UDP_Port))

                    if initial_body:
                        if decoder:
                            try:
                                for decoded_chunk in decoder.feed(initial_body):
                                    write_stream_data(decoded_chunk)
                            except ChunkedDecodeError as exc:
                                sys.stderr.write(f"Caster response declared Transfer-Encoding: chunked, but stream data was not valid chunked encoding: {exc}\n")
                                decoder = None
                                write_stream_data(initial_body)
                        else:
                            write_stream_data(initial_body)

                    data = not decode_failed and not (decoder and decoder.done)
                    while data and not self.should_stop():
                        try:
#                            print("\nSleeping")
#                            time.sleep(0.01)
#                            print("\nSleep Finished. " + str(datetime.datetime.now()))
                            data=self.socket.recv(self.buffer)
                            if self.verbose:
                               sys.stderr.write("%s Data received: %s \n" % (datetime.datetime.now(), len(data)))

                            if decoder:
                                try:
                                    for decoded_chunk in decoder.feed(data):
                                        write_stream_data(decoded_chunk)
                                except ChunkedDecodeError as exc:
                                    sys.stderr.write(f"Caster response declared Transfer-Encoding: chunked, but stream data was not valid chunked encoding: {exc}\n")
                                    decoder = None
                                    write_stream_data(data)
                            else:
                                write_stream_data(data)
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

                        if decoder and decoder.done:
                            data=False

                    if decoder and not decoder.done and not decode_failed and not self.should_stop():
                        sys.stderr.write("Caster response declared Transfer-Encoding: chunked, but the stream ended before a terminating chunk was received\n")

                    if self.should_stop():
                        return

                    if self.verbose:
                        sys.stderr.write('Closing Connection\n')
                    self.socket.close()
                    self.socket=None

                    if reconnectTry < maxReconnect :
                        sys.stderr.write( "%s No Connection to NtripCaster.  Trying again in %i seconds\n" % (datetime.datetime.now(), sleepTime))
                        self.wait_or_stop(sleepTime)
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
                        self.wait_or_stop(sleepTime)
                        sleepTime *= factor
                        if sleepTime>maxReconnectTime:
                            sleepTime=maxReconnectTime
                    reconnectTry += 1

        except KeyboardInterrupt:
            if self.socket:
                self.socket.close()
            sys.exit()

    def should_stop(self):
        return self.stop_event is not None and self.stop_event.is_set()

    def wait_or_stop(self, seconds):
        if self.stop_event:
            self.stop_event.wait(seconds)
        else:
            time.sleep(seconds)

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


def load_last_config_path():
    if not LAST_CONFIG_PATH_FILE.exists():
        return None

    try:
        with LAST_CONFIG_PATH_FILE.open("r", encoding="utf-8") as last_config_file:
            loaded = json.load(last_config_file)
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(loaded, dict):
        return None

    last_path = optional_string(loaded.get("config_path"))
    if not last_path:
        return None
    return Path(last_path).expanduser()


def save_last_config_path(path):
    config_path = Path(path).expanduser()
    try:
        LAST_CONFIG_PATH_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LAST_CONFIG_PATH_FILE.open("w", encoding="utf-8") as last_config_file:
            json.dump({"config_path": str(config_path)}, last_config_file, indent=2)
            last_config_file.write("\n")
    except OSError as exc:
        print(f"Could not remember last config file {config_path}: {exc}", file=sys.stderr)
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

    if normalized["port"] is not None and normalized["port"] < 1:
        raise ValueError("port must be >= 1")

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
    parser.add_argument('caster', nargs='?', type=str, help='The Ntripcaster hostname or IP address. Default: SPS855.com')
    parser.add_argument('port', nargs='?', type=int, help='The Ntripcaster port number. Default: 2101')

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
    parser.add_argument("-s", "--ssl", "--tls", dest="ssl", action="store_true", default=argparse.SUPPRESS, help="Use TLS for the connection.")
    parser.add_argument("--no-ssl", "--no-tls", dest="ssl", action="store_false", default=argparse.SUPPRESS, help="Disable TLS from a config file.")
    parser.add_argument("--ssl-cafile", type=str, metavar="PEM", help="Trust this CA bundle or server PEM when validating TLS.")
    parser.add_argument("-k", "--ssl-insecure", action="store_true", default=argparse.SUPPRESS, help="Disable TLS certificate verification.")
    parser.add_argument("--ssl-secure", dest="ssl_insecure", action="store_false", default=argparse.SUPPRESS, help="Enable TLS certificate verification from a config file.")
    parser.add_argument("-H", "--host", action="store_true", default=argparse.SUPPRESS, help="Include host header; should be on for IBSS.")
    parser.add_argument("--no-host", dest="host", action="store_false", default=argparse.SUPPRESS, help="Disable host header from a config file.")
    parser.add_argument("-r", "--Reconnect", dest="maxReconnect", type=int, help="Number of reconnections. Default: 1")
    parser.add_argument("-D", "--UDP", type=int, help="Broadcast received data on the provided port.")
    parser.add_argument("-2", "--V2", action="store_true", default=argparse.SUPPRESS, help="Use NTRIP V2 (default).")
    parser.add_argument("--V1", dest="V2", action="store_false", default=argparse.SUPPRESS, help="Use NTRIP V1 instead of V2.")
    parser.add_argument("-f", "--outputFile", type=str, help="Write to this file, instead of stdout.")
    parser.add_argument("-m", "--maxtime", type=int, dest="maxConnectTime", help="Maximum length of the connection, in seconds. Default: 0")
    parser.add_argument('--HTTP', type=str, choices=['0.9', '1.0', '1.1'], help='Specify the HTTP protocol version.')
    parser.add_argument("--Header", action="store_true", dest="headerOutput", default=argparse.SUPPRESS, help="Output headers to stderr.")
    parser.add_argument("--no-Header", dest="headerOutput", action="store_false", default=argparse.SUPPRESS, help="Disable header output from a config file.")
    parser.add_argument("--HeaderFile", type=str, help="Output headers to this file, instead of stderr.")
    return parser


def apply_cli_options(config, options):
    for key in CONFIG_DEFAULTS:
        if hasattr(options, key):
            config[key] = getattr(options, key)
    if hasattr(options, "ssl") and not hasattr(options, "port"):
        if options.ssl and config.get("port") in (None, 2101):
            config["port"] = 52101
        elif not options.ssl and config.get("port") in (None, 52101):
            config["port"] = 2101
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
        if config["caster"] and config["caster"] != CONFIG_DEFAULTS["caster"]:
            raise ValueError("Caster should not be provided when using --org/IBSS mode")
        ntripArgs["user"] = config["user"] + "." + config["org"] + ":" + config["password"]
        if config["baseorg"]:
            ntripArgs["caster"] = config["baseorg"] + ".ibss.trimbleos.com"
        else:
            ntripArgs["caster"] = config["org"] + ".ibss.trimbleos.com"
        if config["port"] is None:
            ntripArgs["port"] = 2101
        else:
            ntripArgs["port"] = config["port"]
        if not config["host"]:
            sys.stderr.write("Warning: IBSS Mode without host header\n")
    else:
        if not config["caster"]:
            raise ValueError("A caster is required unless --org is provided")
        ntripArgs["user"] = config["user"] + ":" + config["password"]
        ntripArgs["caster"] = config["caster"]
        ntripArgs["port"] = 2101 if config["port"] is None else config["port"]

    if config["UDP"] is not None:
        ntripArgs["UDP_Port"] = config["UDP"]

    return ntripArgs, config


def build_source_table_args(config):
    source_config = dict(config)
    source_config["mountpoint"] = source_config.get("mountpoint") or "/"
    ntripArgs, normalized = build_ntrip_args(source_config)
    ntripArgs["mountpoint"] = "/"
    return ntripArgs, normalized


def response_uses_chunked_encoding(header_text):
    return any(
        line.lower().startswith("transfer-encoding:")
        and "chunked" in line.lower()
        for line in header_text.replace("\r\n", "\n").split("\n")
    )


def split_response_header(response):
    for separator in (b"\r\n\r\n", b"\n\n"):
        header_end = response.find(separator)
        if header_end >= 0:
            return response[:header_end], response[header_end + len(separator):]
    return b"", response


def decode_chunked_body(body):
    decoder = ChunkedDecoder()
    decoded = bytearray()
    for chunk in decoder.feed(body):
        decoded.extend(chunk)
    if not decoder.done:
        raise ChunkedDecodeError("stream ended before a terminating chunk was received")
    return bytes(decoded)


def connect_ntrip_socket(ntripArgs, timeout=15):
    ntrip_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if ntripArgs["ssl"]:
        import ssl
        if ntripArgs["ssl_insecure"]:
            context = ssl._create_unverified_context()
        else:
            context = ssl.create_default_context()
            if ntripArgs["ssl_cafile"]:
                context.load_verify_locations(cafile=ntripArgs["ssl_cafile"])
        ntrip_socket = context.wrap_socket(ntrip_socket, server_hostname=ntripArgs["caster"])

    ntrip_socket.settimeout(timeout)
    error_indicator = ntrip_socket.connect_ex((ntripArgs["caster"], ntripArgs["port"]))
    if error_indicator != 0:
        ntrip_socket.close()
        raise OSError(error_indicator, os.strerror(error_indicator))
    return ntrip_socket


def get_source_table_request_bytes(ntripArgs):
    if ntripArgs["HTTP"] == "0.9":
        request = "GET / \r\n"
    else:
        request = "GET / HTTP/%s\r\n" % ntripArgs["HTTP"]

    request += "User-Agent: %s\r\n" % useragent
    request += "Authorization: Basic %s\r\n" % base64.b64encode(bytes(ntripArgs["user"], "utf-8")).decode("utf-8")
    request += "Host: %s:%i\r\n" % (ntripArgs["caster"], ntripArgs["port"])
    if ntripArgs["V2"]:
        request += "Ntrip-Version: Ntrip/2.0\r\n"
    request += "Connection: close\r\n\r\n"
    return bytes(request, "ascii")


def read_source_table(config):
    ntripArgs, config = build_source_table_args(config)
    response = bytearray()
    ntrip_socket = connect_ntrip_socket(ntripArgs)
    try:
        request_bytes = get_source_table_request_bytes(ntripArgs)
        ntrip_socket.sendall(request_bytes)
        while len(response) < 2 * 1024 * 1024:
            chunk = ntrip_socket.recv(4096)
            if not chunk:
                break
            response.extend(chunk)
            if b"ENDSOURCETABLE" in response:
                break
    finally:
        ntrip_socket.close()

    raw_response = bytes(response)
    header_bytes, body = split_response_header(raw_response)
    header_text = header_bytes.decode("utf-8", errors="replace")
    if header_bytes and response_uses_chunked_encoding(header_text):
        try:
            body = decode_chunked_body(body)
        except ChunkedDecodeError as exc:
            sys.stderr.write(f"Caster response declared Transfer-Encoding: chunked, but source table data was not valid chunked encoding: {exc}\n")
    source_response = header_bytes + (b"\r\n\r\n" if header_bytes else b"") + body

    request = request_bytes.decode("ascii", errors="replace")
    source_table = source_response.decode("utf-8", errors="replace")
    write_source_table_exchange(request, source_table, config)
    if "401 Unauthorized" in source_table:
        raise ValueError("Unauthorized request")
    if "404 Not Found" in source_table:
        raise ValueError("Caster did not provide a source table")

    mountpoints = parse_source_table(source_table)
    if not mountpoints:
        raise ValueError("No mountpoints were found in the source table")
    return mountpoints


def write_source_table_exchange(request, response, config):
    if not bool_value(config.get("headerOutput", False)):
        return

    exchange = f">>> Source table request\n{request}\n<<< Source table response\n{response}"
    if response and not response.endswith("\n"):
        exchange += "\n"

    header_path = optional_string(config.get("HeaderFile"))
    if header_path:
        with open(Path(header_path).expanduser(), "w", encoding="utf-8") as header_file:
            header_file.write(exchange)
        return

    sys.stderr.write(exchange)


def parse_source_table(source_table):
    mountpoints = []
    for line in source_table.splitlines():
        line = line.strip()
        if not line.startswith("STR;"):
            continue

        fields = line.split(";")
        mountpoint = {
            "mountpoint": fields[1] if len(fields) > 1 else "",
            "identifier": fields[2] if len(fields) > 2 else "",
            "format": fields[3] if len(fields) > 3 else "",
            "format_details": fields[4] if len(fields) > 4 else "",
            "network": fields[7] if len(fields) > 7 else "",
            "country": fields[8] if len(fields) > 8 else "",
            "latitude": fields[9] if len(fields) > 9 else "",
            "longitude": fields[10] if len(fields) > 10 else "",
        }
        if mountpoint["mountpoint"]:
            mountpoints.append(mountpoint)

    return sorted(mountpoints, key=lambda item: item["mountpoint"].lower())


def safe_filename_part(value, default):
    value = optional_string(value) or default
    stem = Path(value.lstrip("/")).name or default
    sanitized = "".join(char if char.isalnum() or char in ("-", "_", ".") else "_" for char in stem)
    return sanitized or default


def config_filename_for_mountpoint(mountpoint):
    return f"{safe_filename_part(mountpoint, 'ntripclient')}.ntrip"


def config_filename_for_connection(config):
    caster = safe_filename_part(config.get("caster"), "caster")
    mountpoint = safe_filename_part(config.get("mountpoint"), "mountpoint")
    return f"{caster}-{mountpoint}.ntrip"


def print_connection_settings(ntripArgs, config):
    output = [
        "Server: " + ntripArgs["caster"],
        "Port: " + str(ntripArgs["port"]),
        "User: " + ntripArgs["user"],
        "mountpoint: " + ntripArgs["mountpoint"],
        "Reconnects: " + str(config["maxReconnect"]),
        "Max Connect Time: " + str(config["maxConnectTime"]),
        "Send GGA: " + str(ntripArgs["GGA"]),
        "HTTP Version: " + ntripArgs["HTTP"],
    ]
    if ntripArgs["V2"]:
        output.append("NTRIP: V2")
    else:
        output.append("NTRIP: V1")
    if ntripArgs["ssl"]:
        output.append("TLS Connection")
    else:
        output.append("Uncrypted Connection")
    sys.stderr.write("\n".join(output) + "\n\n")


def run_client(config, stop_event=None, client_callback=None, progress_callback=None, progress_only=False):
    global maxReconnect

    ntripArgs, config = build_ntrip_args(config)
    maxReconnect = config["maxReconnect"]

    if config["verbose"]:
        pprint(config, stream=sys.stderr)
    if config["verbose"] or config["Tell"]:
        print_connection_settings(ntripArgs, config)

    fileOutput = False
    headerFileOutput = False
    devnullOutput = False
    output_path = optional_string(config["outputFile"])
    header_path = optional_string(config["HeaderFile"])

    if output_path:
        f = open(Path(output_path).expanduser(), 'wb')
        ntripArgs['out'] = f
        fileOutput = True
    elif progress_only:
        f = open(os.devnull, 'wb')
        ntripArgs['out'] = f
        devnullOutput = True
    else:
        try:
            stdout = os.fdopen(sys.stdout.fileno(), "wb", closefd=False, buffering=0)
        except (AttributeError, OSError) as exc:
            raise ValueError("An output file is required when stdout is not available") from exc
        ntripArgs['out'] = stdout

    if config["headerOutput"] and header_path:
        h = open(Path(header_path).expanduser(), 'w')
        ntripArgs['headerFile'] = h
        headerFileOutput = True

    if progress_callback:
        ntripArgs['progress_callback'] = progress_callback

    n = NtripClient(**ntripArgs, stop_event=stop_event)
    if client_callback:
        client_callback(n)
    try:
        n.readData()
    finally:
        if client_callback:
            client_callback(None)
        if fileOutput or devnullOutput:
            f.close()
        if headerFileOutput:
            h.close()


def run_gui(config_path=DEFAULT_CONFIG_PATH):
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    launch_dir = Path.cwd()
    config_path = Path(config_path).expanduser()
    config_path_chosen_on_startup = config_path != DEFAULT_CONFIG_PATH
    if config_path == DEFAULT_CONFIG_PATH:
        last_config_path = load_last_config_path()
        if last_config_path and last_config_path.exists():
            config_path = last_config_path
            config_path_chosen_on_startup = True

    config = CONFIG_DEFAULTS.copy()
    try:
        config.update(load_config_file(config_path))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Could not load config file {config_path}: {exc}", file=sys.stderr)

    if config_path == DEFAULT_CONFIG_PATH and not config_path.exists():
        config_path = launch_dir / config_filename_for_connection(config)

    root = tk.Tk()
    root.title(f"NtripClient - {config_path}")
    root.geometry("650x980")

    path_var = tk.StringVar(value=str(config_path))
    status_var = tk.StringVar(value="")
    config_path_chosen = {"value": config_path_chosen_on_startup}
    client_state = {"event": None, "client": None, "thread": None}

    def update_window_title(*_):
        root.title(f"NtripClient - {path_var.get()}")

    def center_child_window(child, parent, width=None, height=None):
        parent.update_idletasks()
        child.update_idletasks()

        window_width = width or child.winfo_width()
        window_height = height or child.winfo_height()
        parent_x = parent.winfo_rootx()
        parent_y = parent.winfo_rooty()
        parent_width = parent.winfo_width()
        parent_height = parent.winfo_height()

        x = parent_x + max((parent_width - window_width) // 2, 0)
        y = parent_y + max((parent_height - window_height) // 2, 0)
        child.geometry(f"{window_width}x{window_height}{x:+d}{y:+d}")

    path_var.trace_add("write", update_window_title)

    container = ttk.Frame(root, padding=12)
    container.pack(fill="both", expand=True)

    def config_dialog_dir():
        current_path = Path(path_var.get()).expanduser()
        if config_path_chosen["value"] or current_path.exists():
            return current_path.parent
        return launch_dir

    def file_dialog_dir(var=None):
        if var:
            current_value = optional_string(var.get())
            if current_value:
                current_path = Path(current_value).expanduser()
                return current_path.parent
        return config_dialog_dir()

    def browse_config():
        selected = filedialog.askopenfilename(
            title="Choose config file",
            initialdir=str(config_dialog_dir()),
            filetypes=(("NTRIP config files", "*.ntrip"), ("JSON files", "*.json"), ("All files", "*.*")),
        )
        if selected:
            selected_path = Path(selected).expanduser()
            config_path_chosen["value"] = True
            path_var.set(selected)
            try:
                selected_config = CONFIG_DEFAULTS.copy()
                selected_config.update(load_config_file(selected_path, require=True))
                apply_config_to_fields(normalize_config(selected_config))
                save_last_config_path(selected_path)
                status_var.set(f"Loaded settings from {selected_path}")
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                messagebox.showerror("NtripClient", str(exc))

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
        ("GGA", "Send GGA", "check"),
        ("lat", "GGA latitude", "entry"),
        ("long", "GGA longitude", "entry"),
        ("height", "GGA height", "entry"),
        ("ssl", "Use TLS", "check"),
        ("ssl_validate", "Validate TLS certificate", "check"),
        ("ssl_cafile", "TLS CA file", "file"),
        ("maxReconnect", "Reconnects", "entry"),
        ("UDP", "UDP broadcast port", "entry"),
        ("maxConnectTime", "Max connection time", "entry"),
        ("HTTP", "HTTP version", "combo"),
        ("outputFile", "Output file", "savefile"),
        ("HeaderFile", "Header file", "savefile"),
    ]
    bool_fields = [
        ("verbose", "Verbose output"),
        ("Tell", "Print settings before connecting"),
        ("host", "Include host header"),
        ("V2", "NTRIP V2"),
        ("headerOutput", "Output headers"),
    ]

    text_vars = {}
    bool_vars = {}
    widgets = {}
    mountpoint_button = {"widget": None}

    def browse_file(var, save=False):
        if save:
            selected = filedialog.asksaveasfilename(title="Choose file", initialdir=str(file_dialog_dir(var)))
        else:
            selected = filedialog.askopenfilename(title="Choose file", initialdir=str(file_dialog_dir(var)))
        if selected:
            var.set(selected)

    for row, (key, label, field_type) in enumerate(text_fields):
        ttk.Label(fields_frame, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)
        value = config.get(key, "")
        var = tk.StringVar(value="" if value is None else str(value))
        text_vars[key] = var
        if field_type == "combo":
            widget = ttk.Combobox(fields_frame, textvariable=var, values=("0.9", "1.0", "1.1"), state="readonly")
        elif field_type == "check":
            var = tk.BooleanVar(value=bool_value(config.get(key, False)))
            if key == "ssl_validate":
                var.set(not bool_value(config.get("ssl_insecure", False)))
            text_vars.pop(key, None)
            bool_vars[key] = var
            widget = ttk.Checkbutton(fields_frame, variable=var)
        elif key == "mountpoint":
            widget = ttk.Combobox(fields_frame, textvariable=var, values=(), state="normal")
        else:
            show = "*" if field_type == "password" else None
            widget = ttk.Entry(fields_frame, textvariable=var, show=show)
        widgets[key] = widget
        widget.grid(row=row, column=1, sticky="ew", pady=4)
        if key == "mountpoint":
            mountpoint_button["widget"] = ttk.Button(fields_frame, text="Get Mountpoint", command=lambda: fetch_mountpoints_from_gui())
            mountpoint_button["widget"].grid(row=row, column=2, padx=(8, 0), pady=4)
        if field_type in ("file", "savefile"):
            browse_button = ttk.Button(fields_frame, text="Browse", command=lambda v=var, s=field_type == "savefile": browse_file(v, s))
            browse_button.grid(row=row, column=2, padx=(8, 0), pady=4)
            widgets[f"{key}_browse"] = browse_button

    bool_start = len(text_fields)
    for index, (key, label) in enumerate(bool_fields):
        var = tk.BooleanVar(value=bool_value(config.get(key, False)))
        bool_vars[key] = var
        ttk.Checkbutton(fields_frame, text=label, variable=var).grid(row=bool_start + index, column=0, columnspan=3, sticky="w", pady=3)

    def sync_tls_port(*_):
        port = text_vars["port"].get().strip()
        if bool_vars["ssl"].get():
            if port in ("", "2101"):
                text_vars["port"].set("52101")
        elif port in ("", "52101"):
            text_vars["port"].set("2101")

    def set_widget_enabled(widget, enabled):
        if not widget:
            return
        try:
            widget.state(["!disabled"] if enabled else ["disabled"])
        except AttributeError:
            widget.configure(state="normal" if enabled else "disabled")

    def refresh_dependent_fields(*_):
        gga_enabled = bool_vars["GGA"].get()
        for key in ("lat", "long", "height"):
            set_widget_enabled(widgets.get(key), gga_enabled)

        tls_enabled = bool_vars["ssl"].get()
        for key in ("ssl_validate", "ssl_cafile", "ssl_cafile_browse"):
            set_widget_enabled(widgets.get(key), tls_enabled)

    bool_vars["ssl"].trace_add("write", sync_tls_port)
    bool_vars["ssl"].trace_add("write", refresh_dependent_fields)
    bool_vars["GGA"].trace_add("write", refresh_dependent_fields)
    refresh_dependent_fields()

    fields_frame.columnconfigure(1, weight=1)

    progress_frame = ttk.LabelFrame(root, text="Data transfer", padding=(8, 6))
    progress_frame.pack(fill="x", padx=12, pady=(0, 4))
    progress_text_var = tk.StringVar(value=format_progress_line(0, 0, 0))
    ttk.Label(progress_frame, textvariable=progress_text_var).pack(anchor="w")
    progress_bar = ttk.Progressbar(progress_frame, mode="indeterminate")
    progress_bar.pack(fill="x", pady=(6, 0))
    progress_only_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(
        progress_frame,
        text="Display progress only",
        variable=progress_only_var,
    ).pack(anchor="w", pady=(8, 0))

    transfer_progress = TransferProgress()
    progress_tick_job = {"id": None}

    def refresh_progress_display():
        total, elapsed, rate = transfer_progress.snapshot()
        progress_text_var.set(format_progress_line(total, elapsed, rate))

    def reset_progress_display():
        if progress_tick_job["id"] is not None:
            root.after_cancel(progress_tick_job["id"])
            progress_tick_job["id"] = None
        try:
            progress_bar.stop()
        except tk.TclError:
            pass
        transfer_progress.reset()
        refresh_progress_display()

    def schedule_progress_tick():
        refresh_progress_display()
        if client_state["thread"] and client_state["thread"].is_alive():
            progress_tick_job["id"] = root.after(500, schedule_progress_tick)

    def on_progress(nbytes):
        transfer_progress.add(nbytes)
        root.after(0, refresh_progress_display)

    controls = ttk.Frame(root, padding=(12, 0, 12, 12))
    controls.pack(fill="x")
    ttk.Label(controls, textvariable=status_var).pack(fill="x", pady=(0, 8))

    def refresh_default_config_path(*_):
        if config_path_chosen["value"]:
            return
        draft = CONFIG_DEFAULTS.copy()
        for key, var in text_vars.items():
            value = var.get().strip()
            draft[key] = value if value else None
        path_var.set(str(launch_dir / config_filename_for_connection(draft)))

    text_vars["mountpoint"].trace_add("write", refresh_default_config_path)
    text_vars["caster"].trace_add("write", refresh_default_config_path)
    refresh_default_config_path()

    def collect_config():
        collected = CONFIG_DEFAULTS.copy()
        for key, var in text_vars.items():
            value = var.get().strip()
            collected[key] = value if value else None
        for key, var in bool_vars.items():
            if key == "ssl_validate":
                continue
            collected[key] = var.get()
        collected["ssl_insecure"] = not bool_vars["ssl_validate"].get()
        return normalize_config(collected)

    def apply_config_to_fields(new_config):
        for key, var in text_vars.items():
            value = new_config.get(key, "")
            var.set("" if value is None else str(value))
        for key, var in bool_vars.items():
            if key == "ssl_validate":
                var.set(not bool_value(new_config.get("ssl_insecure", False)))
            else:
                var.set(bool_value(new_config.get(key, False)))
        refresh_dependent_fields()

    def save_from_gui():
        collected = collect_config()
        selected = filedialog.asksaveasfilename(
            parent=root,
            title="Save config file",
            initialdir=str(config_dialog_dir()),
            initialfile=config_filename_for_connection(collected),
            defaultextension=".ntrip",
            filetypes=(("NTRIP config files", "*.ntrip"), ("JSON files", "*.json"), ("All files", "*.*")),
        )
        if not selected:
            status_var.set("Save canceled.")
            return None

        config_path_chosen["value"] = True
        path_var.set(selected)
        saved_path = save_config_file(collected, selected)
        save_last_config_path(saved_path)
        status_var.set(f"Saved settings to {saved_path}")
        return collected

    def show_mountpoint_dialog(mountpoints):
        dialog = tk.Toplevel(root)
        dialog.title("NTRIP MountPoints")
        dialog.transient(root)

        table_frame = ttk.Frame(dialog, padding=(12, 12, 12, 0))
        table_frame.pack(fill="both", expand=True)

        columns = ("mountpoint", "identifier", "format", "network", "country", "latitude", "longitude")
        tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        headings = {
            "mountpoint": "MountPoint",
            "identifier": "Base Station",
            "format": "Format",
            "network": "Network",
            "country": "Country",
            "latitude": "Latitude",
            "longitude": "Longitude",
        }
        mountpoint_width = max(
            220,
            min(480, (max([20] + [len(item["mountpoint"]) for item in mountpoints]) * 10) + 30),
        )
        widths = {
            "mountpoint": mountpoint_width,
            "identifier": 180,
            "format": 90,
            "network": 110,
            "country": 80,
            "latitude": 90,
            "longitude": 90,
        }
        for column in columns:
            tree.heading(column, text=headings[column])
            tree.column(column, width=widths[column], anchor="w")

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        for mountpoint in mountpoints:
            tree.insert(
                "",
                "end",
                values=(
                    mountpoint["mountpoint"],
                    mountpoint["identifier"],
                    mountpoint["format"],
                    mountpoint["network"],
                    mountpoint["country"],
                    mountpoint["latitude"],
                    mountpoint["longitude"],
                ),
            )

        def close_mountpoint_dialog():
            try:
                dialog.grab_release()
            except tk.TclError:
                pass
            dialog.destroy()
            root.lift()
            root.focus_force()
            widgets["mountpoint"].focus_set()

        def use_selected_mountpoint():
            selection = tree.selection()
            if not selection:
                return
            values = tree.item(selection[0], "values")
            text_vars["mountpoint"].set(values[0])
            status_var.set(f"Selected mountpoint {values[0]}")
            close_mountpoint_dialog()

        tree.bind("<Double-1>", lambda event: use_selected_mountpoint())
        button_frame = ttk.Frame(dialog, padding=(12, 0, 12, 12))
        button_frame.pack(fill="x")
        ttk.Button(button_frame, text="Use Selected", command=use_selected_mountpoint).pack(side="left")
        ttk.Button(button_frame, text="Cancel", command=close_mountpoint_dialog).pack(side="right")
        dialog.protocol("WM_DELETE_WINDOW", close_mountpoint_dialog)
        dialog_width = min(1200, sum(widths.values()) + 80)
        center_child_window(dialog, root, dialog_width, 420)
        dialog.grab_set()
        tree.focus_set()

    def fetch_mountpoints_from_gui():
        try:
            collected = collect_config()
        except Exception as exc:
            messagebox.showerror("NtripClient", str(exc))
            return

        if mountpoint_button["widget"]:
            mountpoint_button["widget"].configure(state="disabled")
        status_var.set("Fetching mountpoints from caster...")

        def worker():
            try:
                mountpoints = read_source_table(collected)
                root.after(0, lambda: widgets["mountpoint"].configure(values=[item["mountpoint"] for item in mountpoints]))
                root.after(0, lambda: show_mountpoint_dialog(mountpoints))
                root.after(0, lambda: status_var.set(f"Loaded {len(mountpoints)} mountpoints."))
            except Exception as exc:
                error = str(exc)
                root.after(0, lambda error=error: messagebox.showerror("NtripClient", error))
                root.after(0, lambda: status_var.set("Could not fetch mountpoints."))
            finally:
                if mountpoint_button["widget"]:
                    root.after(0, lambda: mountpoint_button["widget"].configure(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    def stop_from_gui():
        if client_state["event"]:
            client_state["event"].set()
        if client_state["client"]:
            client_state["client"].stop()
        start_button.configure(state="disabled")
        status_var.set("Stopping client...")

    def start_from_gui():
        if client_state["thread"] and client_state["thread"].is_alive():
            stop_from_gui()
            return

        try:
            collected = collect_config()
            build_ntrip_args(collected)
        except Exception as exc:
            messagebox.showerror("NtripClient", str(exc))
            return

        stop_event = threading.Event()
        client_state["event"] = stop_event
        start_button.configure(text="Stop", state="normal")
        status_var.set("Client running...")
        reset_progress_display()
        progress_bar.start(12)
        schedule_progress_tick()

        def set_client(client):
            client_state["client"] = client

        def worker():
            try:
                run_client(
                    collected,
                    stop_event=stop_event,
                    client_callback=set_client,
                    progress_callback=on_progress,
                    progress_only=progress_only_var.get(),
                )
                root.after(0, lambda: status_var.set("Client stopped."))
            except SystemExit as exc:
                code = exc.code
                if stop_event.is_set():
                    root.after(0, lambda: status_var.set("Client stopped."))
                else:
                    root.after(0, lambda code=code: status_var.set(f"Client exited with code {code}."))
            except Exception as exc:
                error = str(exc)
                if stop_event.is_set():
                    root.after(0, lambda: status_var.set("Client stopped."))
                else:
                    root.after(0, lambda error=error: messagebox.showerror("NtripClient", error))
                    root.after(0, lambda: status_var.set("Client stopped with an error."))
            finally:
                def reset_start_button():
                    if progress_tick_job["id"] is not None:
                        root.after_cancel(progress_tick_job["id"])
                        progress_tick_job["id"] = None
                    try:
                        progress_bar.stop()
                    except tk.TclError:
                        pass
                    refresh_progress_display()
                    client_state["event"] = None
                    client_state["client"] = None
                    client_state["thread"] = None
                    start_button.configure(text="Start", state="normal")
                root.after(0, reset_start_button)

        client_state["thread"] = threading.Thread(target=worker, daemon=True)
        client_state["thread"].start()

    ttk.Button(controls, text="Browse", command=browse_config).pack(side="left")
    ttk.Button(controls, text="Save", command=lambda: save_from_gui()).pack(side="left", padx=(8, 0))
    start_button = ttk.Button(controls, text="Start", command=start_from_gui)
    start_button.pack(side="left", padx=(8, 0))

    def close_gui():
        if client_state["thread"] and client_state["thread"].is_alive():
            stop_from_gui()
        root.destroy()

    ttk.Button(controls, text="Quit", command=close_gui).pack(side="right")
    root.protocol("WM_DELETE_WINDOW", close_gui)

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
        "--V1",
        dest="V2",
        action="store_false",
        help="Use NTRIP V1 instead of V2.",
    )
    parser.add_argument(
        "-2", "--V2",
        action="store_true",
        default=True,
        help="Use NTRIP V2 (default).",
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
        help="Output headers to stderr."
    )
    parser.add_argument(
        "--HeaderFile",
        type=str,
        default=None,
        help="Output headers to this file, instead of stderr."
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
