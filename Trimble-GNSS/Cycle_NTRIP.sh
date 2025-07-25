#!/bin/bash

cd /home/gkirk/Trimble-GNSS

logger "Disabling SPS855_COM-S2.cfg"
./NTRIP_Server_Cfg.py  @SPS855_COM-S2.cfg  --disable
sleep 5
logger "Enabling SPS855_COM-S2.cfg"
./NTRIP_Server_Cfg.py  @SPS855_COM-S2.cfg  --enable
logger "Cycle_NTRIP Complete"
