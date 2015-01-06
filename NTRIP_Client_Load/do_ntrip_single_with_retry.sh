#! /bin/bash
echo Starting NTRIP Connection $1
source ./configuration

if [ $IBSS == 0 ]
then
    USERNAME=$USER$2
    CASTER=$NTRIP_CASTER
else
    USERNAME=$USER$2.$ORG
    CASTER=$BASE_ORG.$NTRIP_CASTER
fi

rm $TMP_DATA_PATH/ntrip_$1.bin &> /dev/null
BEFORE="$(date +%s)"
CONNECTIONS=0
AFTER="$(date +%s)"
elapsed_seconds="$(expr $AFTER - $BEFORE)"
while [ $elapsed_seconds -lt $TEST_TIME ]
do
#echo    curl -f -o $TMP_DATA_PATH/ntrip_$1.bin --connect-timeout 10 -m $(expr $TEST_TIME - $elapsed_seconds)   -H "Ntrip-Version: Ntrip/2.0" -H "User-Agent: NTRIP CURL_NTRIP_TEST/0.1" -u $USERNAME:$PASS$2  http://$CASTER/$BASE
    curl -f -o $TMP_DATA_PATH/ntrip_$1.bin --connect-timeout 10 -m  $(expr $TEST_TIME - $elapsed_seconds)  -H "Ntrip-Version: Ntrip/2.0" -H "User-Agent: NTRIP CURL_NTRIP_TEST/0.1" -u $USERNAME:$PASS$2  http://$CASTER/$BASE &>/dev/null
    Result=$?
    CONNECTIONS=$(expr $CONNECTIONS + 1)
    AFTER="$(date +%s)"
    elapsed_seconds="$(expr $AFTER - $BEFORE)"
done

filename=$TMP_DATA_PATH/ntrip_$1.bin

if [ `uname` == "Darwin" ]
then
   eval `stat -s $TMP_DATA_PATH"/ntrip_"$1".bin"`
else
   st_size=$(stat -c%s $TMP_DATA_PATH"/ntrip_"$1".bin")
fi

echo $1,$Result,$st_size, $(expr $AFTER - $BEFORE),$CONNECTIONS >>ntrip_results.txt
echo NTRIP Connection $1 ended with a result of $Result

if [ $DELETE_FILES ]
then
   rm $TMP_DATA_PATH/ntrip_$1.bin
fi
