#!/usr/bin/perl

use strict;

my $in;

if ($#ARGV >= 0) {
    unless (open($in,  "<", $ARGV[0])){
      die "could not open $ARGV[0] for reading.";
    }
}
else {
    $in  = *STDIN;
}

sub readdsc
{
  my %parsed;
  my $lastkey;
  while (<$in>) {
      if (my ($key, $value) = m/^(\S+):(.*)/) {
          $value =~ s/^\s+//;
          if ($value ne "") {
            $parsed{$key} = $value;
          }
          $lastkey=$key;
      }
      if (m/^ /) {
          s/ //;
          s/^\.$//;
          chomp;
          if ($parsed{$lastkey} ne "") {
            $parsed{$lastkey} .= "\n"
          }
          $parsed{$lastkey} .= $_;
      }
  }
  return %parsed;
}

my %package = readdsc();

my @files = split /\n/, $package{Files};
foreach my $file( @files ) {
  my @attrs = split ' ', $file;
  print "$attrs[2]\n";
}
