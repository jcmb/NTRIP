#! /usr/bin/perl
use strict;
use warnings;
use Time::HiRes qw(time);

$| = 1;

binmode(STDIN);
binmode(STDOUT);
binmode(STDERR);

my $interval = 1;
my $pass_through = 0;

sub usage {
    die("Usage: Count_Data.pl [--interval seconds] [--passthrough]\n");
}

while (@ARGV) {
    my $arg = shift @ARGV;

    if ($arg eq "--interval") {
        usage() unless @ARGV;
        $interval = shift @ARGV;
        usage() unless $interval =~ /^\d+(?:\.\d+)?$/ && $interval > 0;
    } elsif ($arg eq "--passthrough") {
        $pass_through = 1;
    } elsif ($arg eq "--help" || $arg eq "-h") {
        print "Usage: Count_Data.pl [--interval seconds] [--passthrough]\n";
        print "Reads stdin and reports byte counts to stderr.\n";
        print "Use --passthrough to copy stdin to stdout while counting.\n";
        exit 0;
    } else {
        usage();
    }
}

my $total = 0;
my $last_total = 0;
my $start_time = time();
my $last_report_time = $start_time;
my $buffer;

sub print_report {
    my ($final) = @_;
    my $now = time();
    my $elapsed = $now - $start_time;
    my $period = $now - $last_report_time;
    my $rate = $period > 0 ? ($total - $last_total) / $period : 0;
    my $average = $elapsed > 0 ? $total / $elapsed : 0;
    my $label = $final ? "Total" : "Count";

    printf STDERR "\r%s: %d bytes | current: %.1f B/s | average: %.1f B/s",
        $label, $total, $rate, $average;

    $last_total = $total;
    $last_report_time = $now;
}

while (1) {
    my $bytes_read = sysread(STDIN, $buffer, 65536);

    die "Error reading stdin: $!\n" unless defined $bytes_read;
    last if $bytes_read == 0;

    $total += $bytes_read;

    if ($pass_through) {
        my $offset = 0;
        while ($offset < $bytes_read) {
            my $bytes_written = syswrite(STDOUT, $buffer, $bytes_read - $offset, $offset);
            die "Error writing stdout: $!\n" unless defined $bytes_written;
            $offset += $bytes_written;
        }
    }

    print_report(0) if time() - $last_report_time >= $interval;
}

print_report(1);
print STDERR "\n";
