#! /usr/bin/perl
$| = 1;
my $s;

die ("Usage: Time_Length <Length of time string> <Seconds to generate Time>")  if ($#ARGV != 1);
#print $ARGV[0];
my $Desired_Length=$ARGV[0];
my $Test_Time=$ARGV[1];
my $Padding;

while ($Test_Time--) {
    $s = "Current Time: " . localtime() . " ";
    if (length($s) < $Desired_Length) {
	$Padding = $Desired_Length - length($s);
    }
    print $s . "*" x $Padding;
    printf ("\n");
    sleep (1)
#    print $_ ."\n";
}
