#! /bin/bash
#usage user password server (inc port) mount
curl --silent -f  --no-buffer --connect-timeout 10  -H "Ntrip-Version: Ntrip/2.0" -H "User-Agent: NTRIP CURL_NTRIP_TEST/0.1" -u $1:$2  http://$3/$4
