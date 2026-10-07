#!/usr/bin/env bash
# Render one slice of the ad (video only), so several machines can render in parallel.
#   scripts/render-slice.sh <from> <to>   ->  out/slices/slice-<from>-<to>.mp4
# Join the slices with scripts/join-slices.sh. Every frame is a pure function of its
# number, so slices cut anywhere join seamlessly; the encoder settings come from
# remotion.config.ts, so all slices match.
set -euo pipefail
cd "$(dirname "$0")/.."
from=$1
to=$2
mkdir -p out/slices
out="out/slices/slice-$(printf %05d "$from")-$(printf %05d "$to").mp4"
npx remotion render PaladexLaunch "$out" --frames="$from-$to" --muted --concurrency="${CONCURRENCY:-2}"
echo "slice -> $out"
