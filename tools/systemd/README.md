# The nightly run

`wow-voiceover.timer` starts `tools/nightly.py` at 01:00 every night. In order, it:

1. imports the in-game reports (`/lv bad`, see `server/`) on Sundays and queues those lines for retakes;
2. applies the review page's accept/retry marks;
3. plans and queues the race/class sentences of every directed line (`variants.py`);
4. renders anything queued until 09:00 on every renderer in `config.local.json` (`overnight.py`): the director, the
   speech check and the retake rounds run inside it;
5. prepares the race/class splices (`splices.py`) and re-encodes changed lines to 64 kbps;
6. builds the release (`client/build_release.py`) and, if `share_dir` is set, publishes `LivingVoices.zip` and
   `LivingVoices-update.zip` there. An engine version not listed in `client/ENGINE_TESTED` is published only as
   `LivingVoices-<version>-test.zip`.

Summary: `data/overnight_reports/nightly-<date>.md`; log: `data/overnight_reports/nightly.log`.

## Install

    sed -e "s#/path/to/LivingVoices#$PWD/../..#; s#/path/to/ComfyUI#$HOME/ComfyUI#" wow-voiceover.service \
        > ~/.config/systemd/user/wow-voiceover.service
    cp wow-voiceover.timer ~/.config/systemd/user/
    mkdir -p ../../data/overnight_reports
    systemctl --user daemon-reload && systemctl --user enable --now wow-voiceover.timer
    systemctl --user list-timers        # NEXT should read tomorrow 01:00

Off again: `systemctl --user disable --now wow-voiceover.timer`. Progress: `overnight.py status`.

## Ports above 32767 and Linux's ephemeral range (2026-10-13)

A ComfyUI port inside Linux's ephemeral range (32768-60999) can be handed out as the source port of an outgoing local
connection while ComfyUI loads; the server's own bind then fails with "Port ... is already in use" although nothing
listens there. `comfy2.sh start` retries up to five times; the lasting fix is reserving the ports (once, as root):

    echo 'net.ipv4.ip_local_reserved_ports = 42400-42431' | sudo tee /etc/sysctl.d/90-livingvoices-ports.conf
    sudo sysctl --system
