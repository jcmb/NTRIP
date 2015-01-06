#! /bin/bash 
CFG_NUM=$1
export CFG_NUM
source ./configuration$CFG_NUM


if [ $FAKE_LOAD == 0 ] 
then
    let TOTAL_TIME=$(($TEST_TIME+ (($LAST_SERVER-$FIRST_SERVER+1)* ($STARTUP_DELAY)) + 15))
    echo "Total Time: $TOTAL_TIME"
   nc   $SOURCE_SERVER $SOURCE_PORT | ./Break_Pipe.pl $TOTAL_TIME >$TMP_DATA_PATH/nc_data&
   echo "Connecting to $SOURCE_SERVER $SOURCE_PORT"
   sleep 5
fi


for ((i=FIRST_SERVER; i <= LAST_SERVER;i++))
do
#   echo NTRIP Connection $i
if [ $ADD_NUMBER_TO_USER_PASS ]
then
   ./do_ntrip_server_single.sh $i $i  &
else
   ./do_ntrip_server_single.sh $i &
fi
   sleep $STARTUP_DELAY
done

sleep 1
echo Waiting $TEST_TIME seconds for sub processes to finish
sleep $TEST_TIME
sleep 15
#The 15 is for the 10 second timeout on connections and then some bonus time
echo NTRIP Testing has finished

if [ $FAKE_LOAD == 0 ] 
then
    rm $TMP_DATA_PATH/nc_data
fi
