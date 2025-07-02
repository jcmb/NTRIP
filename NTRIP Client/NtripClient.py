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
from pprint import pprint
#import ssl
#from optparse import OptionParser


import argparse


version=0.4
useragent="NTRIP JCMBsoftPythonClient/%.1f" % version

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
                 port=2101,
                 caster="",
                 mountpoint="",
                 host=False,
                 lat=46,
                 lon=122,
                 height=1212,
                 ssl=False,
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
                    self.socket=ssl.wrap_socket(self.socket)

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
                                        sys.stderr.write(line+"\n")
                                    else:
                                        sys.stderr.write("Header: " + line+"\n")
                            if self.headerOutput:
                                self.headerFile.write(line+"\n")




                        for line in header_lines:
                            if line.find("SOURCETABLE")>0:
                                sys.stderr.write("Mount point does not exist\n")
                                sys.exit(1)
                            elif line.find("401 Unauthorized")>=0:
                                sys.stderr.write("Unauthorized request\n")
                                sys.exit(1)
                            elif line.find("404 Not Found")>=0:
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



                    data = "Initial data"
                    while data:
                        try:
#                            print("\nSleeping")
#                            time.sleep(0.01)
#                            print("\nSleep Finished. " + str(datetime.datetime.now()))
                            data=self.socket.recv(self.buffer)
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

if __name__ == '__main__':

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
        default=2101,
        nargs='?',  # Makes it optional: 0 or 1 argument
        help='The Ntripcaster port number.'
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
        import ssl
        ntripArgs['ssl']=True
    else:
        ntripArgs['ssl']=False

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

    else:
        if options.caster == None:
            print ("Incorrect number of arguments for NTRIP\n")
            parser.print_help()
            sys.exit(1)
        ntripArgs['user']=options.user+":"+options.password
        ntripArgs['caster']=options.caster
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
