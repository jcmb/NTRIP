#! /bin/bash
source ./configuration$CFG_NUM
echo -en "POST /$BASE$1 HTTP/1.1\r\n">$TMP_DATA_PATH/IBSS_Login-$1.txt
echo -en "Host: $ORG.ibss.trimbleos.com:2101\r\n">>$TMP_DATA_PATH/IBSS_Login-$1.txt
echo -en "X-VERSION=4.15\r\n">>$TMP_DATA_PATH/IBSS_Login-$1.txt
echo -en "X-WARRANTY-DATE=2011-04-01\r\n">>$TMP_DATA_PATH/IBSS_Login-$1.txt
echo -en "X-OPTION-KEY=1fYtudk.gx1gnqOELT0ea5vUTBTOiavGBAVg8rfTQaaW7rLn/W7SvZ/hG2wATc2wkzrMwZuGNG2s\r\n">>$TMP_DATA_PATH/IBSS_Login-$1.txt

if [ $CHUNKED ]
then
    echo -en "Transfer-Encoding: chunked\r\n" >>$TMP_DATA_PATH/IBSS_Login-$1.txt
fi

echo -en "X-SERIALNUM=GAMELC$2\r\n">>$TMP_DATA_PATH/IBSS_Login-$1.txt
echo -en "X-DEVICE=SPS852\r\n">>$TMP_DATA_PATH/IBSS_Login-$1.txt
echo -en "Ntrip-Version: Ntrip/2.0\r\n">>$TMP_DATA_PATH/IBSS_Login-$1.txt
echo -en "User-Agent: NTRIP GRK_trimble 1.41.2.13\r\n">>$TMP_DATA_PATH/IBSS_Login-$1.txt
echo -en "Authorization: Basic U1BTODUyLUdBTUVMQzEwMDM6cGFzc3dvcmQ=\r\n">>$TMP_DATA_PATH/IBSS_Login-$1.txt
echo -en "NTRIP-STR: GRK Test Server $1. Do not use;CMR;0(1),1(1),2(1);2;GPS+GLONASS;;;39.90;-105.11;1;0;Trimble SPS852;none;Y;N;9600;none;\r\n">>$TMP_DATA_PATH/IBSS_Login-$1.txt
echo -en "\r\n" >>$TMP_DATA_PATH/IBSS_Login-$1.txt

before="$(date +%s)"

if [ "$FAKE_LOAD" == "1" ]
then
    if [ $CHUNKED ]
    then
	echo  Starting NTRIP Server Connection $1, Faked Chunked
	./Time_Length.pl $BPS $TEST_TIME | ./Make_Chunks.pl | cat $TMP_DATA_PATH/IBSS_Login-$1.txt - | nc  $ORG.$IBSS_SERVER 2101 >$TMP_DATA_PATH/server_reply_$BASE$1
    else
	echo  Starting NTRIP Server Connection $1, Faked
	./Time_Length.pl $BPS $TEST_TIME | cat $TMP_DATA_PATH/IBSS_Login-$1.txt - | nc  $ORG.$IBSS_SERVER 2101 >$TMP_DATA_PATH/server_reply_$BASE$1
    fi
else
    if [ $CHUNKED ]
    then
	echo  Starting NTRIP Server Connection $1, Chunked
        tail -f -c 1000 $TMP_DATA_PATH/nc_data | ./Break_Pipe.pl $TEST_TIME | ./Make_Chunks.pl | cat $TMP_DATA_PATH/IBSS_Login-$1.txt - | nc   $ORG.$IBSS_SERVER 2101 >$TMP_DATA_PATH/server_reply_$BASE$1
    else
	echo  Starting NTRIP Server Connection $1
	tail -f -c  1000 $TMP_DATA_PATH/nc_data |  ./Break_Pipe.pl $TEST_TIME | cat $TMP_DATA_PATH/IBSS_Login-$1.txt - |  nc   $ORG.$IBSS_SERVER 2101 >$TMP_DATA_DIR/server_reply_$BASE$1 >/$TMP_DATA_PATH/server_reply_$BASE$1
    fi
fi

after="$(date +%s)"
tested_time=$(expr $after - $before);

echo  NTRIP Server Connection $1, Closing after $tested_time seconds, expected test time $TEST_TIME
echo "$1,-1,-1,$tested_time" >ntrip_server_results$CFG_NUM.csv

if [ $DELETE_FILES ]
then
   rm $TMP_DATA_PATH/server_reply_$BASE$1
   rm $TMP_DATA_PATH/IBSS_Login-$1.txt
fi

