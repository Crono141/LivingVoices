#!/usr/bin/env bash
# The voice-over's own ComfyUI instances, TTS suite only:
#   tools/comfy2.sh start | stop | status          renderer '1': card 1 (beside the LLM), .comfy2
#   tools/comfy2.sh start | stop | status 0b       renderer '0b': card 0's SECOND renderer, .comfy3 -- night window only
# Ports come from config.local.json's renderers (tools/lvconfig.py). Card 0's first renderer is a ComfyUI shared with
# other work (renderers '0'). (2026-11-01, the producer approved) one IndexTTS-2 keeps a card ~50% busy in ~7 GB, so a
# second one on card 0 renders beside it for the night window (~1.5x card 0's output); its worker steps aside while
# the shared ComfyUI has a job of someone else's.
set -euo pipefail
VO=$(cd "$(dirname "$0")/.." && pwd)
cfg() { python3 -c "import sys; sys.path.insert(0, '$VO/tools'); import lvconfig as L; print($1)"; }
if [[ ${2:-} == 0b ]]; then B=$VO/.comfy3; INST=0b; DEV=0; else B=$VO/.comfy2; INST=1; DEV=1; fi
URL=$(cfg "L.RENDERERS['$INST']"); PORT=${URL##*:}; COMFY=$(cfg L.COMFYUI); OUT=$(cfg L.COMFY_OUT)
up() { curl -s -m 2 http://127.0.0.1:$PORT/system_stats >/dev/null; }
case "${1:-status}" in
start)
    up && { echo "already up"; exit 0; }
    cd "$COMFY"
    # "Port 42422 is already in use" with nothing listening (2026-10-13): a port above 32767 lies in Linux's ephemeral range
    # (32768-60999), so an outgoing local connection made while ComfyUI loads can be handed it as its source port,
    # and the server's own bind then fails. It varies run to run: try again, up to 5 times. The lasting fix is
    # reserving the port: net.ipv4.ip_local_reserved_ports (tools/systemd/README.md).
    for attempt in 1 2 3 4 5; do
        CUDA_VISIBLE_DEVICES=$DEV nohup "$COMFY/venv/bin/python" main.py --listen 127.0.0.1 --port $PORT --base-directory "$B" --temp-directory "$B/temp" \
            --output-directory "$OUT" --disable-auto-launch --disable-api-nodes \
            --disable-all-custom-nodes --whitelist-custom-nodes tts_audio_suite > "$B/comfy2.log" 2>&1 &
        echo $! > "$B/pid"
        for _ in $(seq 100); do
            up && { echo "up (pid $(cat "$B/pid"))"; exit 0; }
            kill -0 "$(cat "$B/pid")" 2>/dev/null || break
            sleep 3
        done
        if grep -q "already in use" "$B/comfy2.log"; then echo "port $PORT taken at bind (attempt $attempt); retrying"; sleep 5; continue; fi
        kill -0 "$(cat "$B/pid")" 2>/dev/null && { echo "!!! not up after 5 min"; exit 1; }
        echo "!!! died; see $B/comfy2.log"; exit 1
    done
    echo "!!! port $PORT taken at bind 5 times; see $B/comfy2.log"; exit 1 ;;
stop)
    # wait for it to be gone: a start straight after found the port still held ("Port 42422 is already in use")
    # and died with no other message (2026-10-12)
    if [[ -f $B/pid ]] && kill "$(cat "$B/pid")" 2>/dev/null; then
        for _ in $(seq 30); do kill -0 "$(cat "$B/pid")" 2>/dev/null || break; sleep 1; done
        echo stopped
    else
        echo "not running"
    fi
    rm -f "$B/pid" ;;
status) up && echo "up" || echo "down" ;;
esac
