#!/bin/bash
set -e
source /opt/ros/jazzy/setup.bash
# Mounted WS1 install — optional, some containers don't need it
if [ -f /opt/ws1_install/setup.bash ]; then
    source /opt/ws1_install/setup.bash
fi
exec "$@"
