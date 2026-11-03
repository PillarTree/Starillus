#!/bin/sh
# Build the starillus-desktop Debian package.
set -e
cd debian
dpkg-buildpackage -b -uc -us
cd ..
echo "Built starillus-desktop package."
