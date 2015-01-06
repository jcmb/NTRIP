#! /bin/bash
source ./configuration
#rm /tmp/ntrip_*.bin
rm ntrip_results.txt

for ((i=FIRST_CLIENT; i <= LAST_CLIENT;i++))
do
#   echo NTRIP Connection $i
if [ $ADD_NUMBER_TO_USER_PASS ]
then
#   ./do_ntrip_single.sh $i $i  &
   ./do_ntrip_single_with_retry.sh $i $i  &
else
#   ./do_ntrip_single.sh $i &
   ./do_ntrip_single_with_retry.sh $i &
fi
   sleep $STARTUP_DELAY
done

sleep 1
echo Waiting $TEST_TIME seconds for sub processes to finish
sleep $TEST_TIME
sleep 15
#The 15 is for the 10 second timeout on connections and then some bonus time
echo NTRIP Testing has finished
