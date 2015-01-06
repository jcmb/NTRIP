#! /usr/bin/perl
$|=1;

die ("Usage: Break_Pipe <Length of time in Seconds to pipe before exiting>")  if ($#ARGV != 0);
#print $ARGV[0];
my $Test_Time=$ARGV[0];
$ARGV[0]="";
$#ARGV=-1;
my $Start_Time=time();

my $End_Time=$Start_Time + $Test_Time;

#print "$Start_Time $End_Time\n";

while (<>) {
    print;
    if (time()>= $End_Time) {
	exit;
}
}
