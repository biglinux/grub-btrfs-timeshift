#!/bin/bash

SERVICE="restore-snapshot-in-use"

case "$1" in
    restore)
        echo "Starting the restoration process..."
        pkexec env DISPLAY="$DISPLAY" XAUTHORITY="$XAUTHORITY" KDE_SESSION_VERSION=6 KDE_FULL_SESSION=true "/usr/local/bin/$SERVICE" --yes > /dev/null 2>&1

        if [[ $? -eq 0 ]]; then
            echo '<div id="snackbar_success" class="snackbar primary top active" stonejs>Restoration completed successfully! Please reboot the system.</div>'
        else
            echo '<div id="snackbar_error" class="snackbar error top active" stonejs>Error: Restore did not complete.</div>'
            exit 1
        fi
        ;;
    reboot)
        echo "Restarting the system..."
        pkexec reboot
        ;;
    *)
        echo "Usage: $0 {restore|reboot}"
        exit 1
        ;;
esac
