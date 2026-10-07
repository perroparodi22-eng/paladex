#!/usr/bin/env bash
# Join out/slices/*.mp4 (in frame order) and lay the full soundtrack under them.
#   scripts/join-slices.sh [output]   (default out/paladex-launch-en.mp4)
# The soundtrack (voice, ducked music, SFX) is rendered on its own, which is quick:
# no video frames are drawn for an audio-only render.
set -euo pipefail
cd "$(dirname "$0")/.."
output=${1:-out/paladex-launch-en.mp4}
ls out/slices/slice-*.mp4 | sort | sed "s|^|file '$PWD/|; s|$|'|" > out/slices/list.txt
ffmpeg -y -loglevel error -f concat -safe 0 -i out/slices/list.txt -c copy out/slices/video.mp4
[ -f out/audio.wav ] || node scripts/render-audio.mjs out/audio.wav
ffmpeg -y -loglevel error -i out/slices/video.mp4 -i out/audio.wav -map 0:v -map 1:a -c:v copy -c:a aac -b:a 320k -shortest -movflags +faststart "$output"
ffprobe -v error -show_entries format=duration:stream=codec_name,nb_frames -of compact "$output"
echo "joined -> $output"
