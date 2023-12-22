#!/usr/bin/perl

use strict;
use AptPkg::Config '$_config';
use AptPkg::System '$_system';
use AptPkg::Version;

# initialise the global config object with the default values
$_config->init;

# determine the appropriate system type
$_system = $_config->system;

# fetch a versioning system
my $vs = $_system->versioning;


my $name = $ARGV[0];
shift;
my $pkg_version = "";
if (@ARGV == 1) {
  $pkg_version = $ARGV[0];
  shift;
}

sub usage {
    die "Usage: $0 PACKAGE VERSION\n";
}

if (not defined $name) {
  usage();
}

my $version = "";
my $directory = "";

sub nextpkg
{
  my %parsed;
  my $lastkey;
  while (<>) {
      last if /^$/;
      if (my ($key, $value) = m/^(\S+):(.*)/) {
          $value =~ s/^\s+//;
          $parsed{$key} = $value;
          $lastkey=$key;
      }
      else {
          s/ //;
          s/^\.$//;
          chomp;
          $parsed{$lastkey} .= "\n" . $_;
      }
  }
  return %parsed;
}

while (my %package = nextpkg()) {
  if ($package{Package} eq $name) {
    if($pkg_version eq "") {
      if($version eq "" or $vs->compare($version, $package{Version}) < 0) {
        $version = $package{Version};
        $directory = $package{Directory};
      }
    }
    else {
      if($vs->compare($pkg_version, $package{Version}) == 0) {

        $version = $package{Version};
        $directory = $package{Directory};
      }
    }
  }
}

print $directory
