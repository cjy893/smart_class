#!/bin/sh
#

DAEMON="/root/edge_compute_device"
CONFIG="/root/config/milkv_config.yaml"
LOGFILE="/mnt/data/edge_compute_device.log"
LIB_PATH="/mnt/system/lib:/mnt/system/usr/lib:/mnt/system/usr/lib/3rd"

{
    echo "=== auto.sh: $(date) ==="
    echo "DAEMON=$DAEMON"
    echo "CONFIG=$CONFIG"

    if [ ! -f "$DAEMON" ]; then
        echo "FATAL: binary not found: $DAEMON"
        exit 1
    fi

    if [ ! -f "$CONFIG" ]; then
        echo "FATAL: config not found: $CONFIG"
        exit 1
    fi

    for i in $(seq 1 10); do
        if [ -f /mnt/data/sensor_cfg.ini ]; then
            echo "sensor_cfg.ini ready"
            break
        fi
        echo "waiting for sensor_cfg.ini... ($i/10)"
        sleep 1
    done

    echo "Starting $DAEMON..."
    cd /root && LD_LIBRARY_PATH="$LIB_PATH" "$DAEMON" "$CONFIG" &
    echo "Started with pid $!"

} >> "$LOGFILE" 2>&1
