#!/bin/sh
# Copy the built stack images to a small target VM without building there.
#
#   ./deploy/school/ship_images.sh <ssh-destination> [ssh options...]
#   e.g. ./deploy/school/ship_images.sh user@school-vm.example
#
# Run from the repository root on a machine where `docker compose build` already
# ran. Images stream compressed over SSH; nothing is written to the target's disk
# except the loaded image layers.
set -eu

if [ "$#" -lt 1 ]; then
  sed -n '4,5p' "$0" >&2
  exit 2
fi
DEST=$1
shift

IMAGES="android-fleet-dashboard-android-manager:latest android-fleet-dashboard-frontend:latest prom/prometheus:v3.2.1 grafana/grafana:11.6.0"
for image in $IMAGES; do
  docker image inspect "$image" >/dev/null 2>&1 || docker pull "$image"
done

echo "shipping: $IMAGES"
# shellcheck disable=SC2086
docker save $IMAGES | gzip -1 | ssh "$@" "$DEST" 'gunzip | docker load'
ssh "$@" "$DEST" 'df -h / | tail -1'
