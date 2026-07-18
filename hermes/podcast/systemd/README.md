# pi4 systemd units for Guru's Tech Bytes

Install on pi4:
```
cp hermes/podcast/systemd/gtb-*.{service,timer} ~/.config/systemd/user/
cp hermes/podcast/systemd/'gtb-alert@.service'   ~/.config/systemd/user/
loginctl enable-linger "$USER"
systemctl --user daemon-reload
systemctl --user enable --now gtb-podcast.timer gtb-topic-refresh.timer
systemctl --user list-timers 'gtb-*'
```
- `gtb-topic-refresh` 05:30 ET → `hermes/scripts/run-topic-refresh-pi4.sh --write`
- `gtb-podcast`       06:00 ET → `hermes/podcast/scripts/run-podcast-pi4.sh`
- Both `OnFailure=gtb-alert@%n` → Telegram via `hermes/bin/gtb-alert.sh`.
