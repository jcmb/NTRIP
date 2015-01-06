#! /usr/bin/perl
$|=1;

while (<>) {
    printf ("%X\r\n" ,length($_));
    print $_ ."\r\n";
}
