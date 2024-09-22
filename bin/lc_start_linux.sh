#!/usr/bin/env bash
# Stand-alone starting script for remote drivers hosted on a linux machine
# Environment preparation should be done during login.
if [ -z "$1" ]
  then
    echo "Usage: $0 lab_name driver_name"
    exit 1
fi
if [ -z "$2" ]
  then
    echo "Usage: $0 lab_name driver_name"
    exit 1
fi
nohup python -m lclib $1 start $2 > lclib.nohup.out &
