#!/bin/bash
# Sample script to build almalinux9to10 using prebuilt buck

# download the prebuilt buck pex latest version
# wget https://jitpack.io/com/github/facebook/buck/2022.05.05.01/buck-2022.05.05.01.pex -O /root/buck-2022.05.05.01.pex

# make a local build of almalinux9to10 via prebuilt buck pex
# assuming the almalinux9to10 is cloned in /root/almalinux9to10
cd /root/almalinux9to10 || exit
/root/buck-2022.05.05.01.pex build :almalinux9to10
