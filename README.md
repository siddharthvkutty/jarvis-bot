# 🛠️ Jarvis Bot (Maintenance Repo)

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.9%2B-blue?style=flat&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Discord-5865F2?logo=discord&logoColor=white" alt="Discord">
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat" alt="License: MIT">
</p>

This repository contains the **maintenance and development version** of a multi-purpose Discord bot.

## Features
- 🎵 Music playback (YouTube via yt-dlp)
- 📊 User stats & leaderboard (messages/commands tracked, no economy)
- 🎨 Image generation (imedit, yuta, invite, profile cards)
- 🎱 Coinflip & 8ball
- 👻 Random background chatter

## Setup
1. `python -m venv .venv && ./.venv/bin/pip install -r requirements.txt`
2. Create a `.env` file with:
   ```
   DISCORD_TOKEN=your_bot_token_here
   ```
   Get the token from the [Discord Developer Portal](https://discord.com/developers/applications) → your app → **Bot** tab.
3. Run it: `./.venv/bin/python bot-stable.py`

### Running on boot (systemd, Arch)
Create `/etc/systemd/system/jarvis-bot.service`:
```ini
[Unit]
Description=Jarvis Discord Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=siddharth
WorkingDirectory=/home/siddharth/Projects/jarvis-bot
ExecStart=/home/siddharth/Projects/jarvis-bot/.venv/bin/python bot-stable.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```
Then: `sudo systemctl daemon-reload && sudo systemctl enable --now jarvis-bot.service`

## Troubleshooting

**Music: bot joins the voice channel but plays no sound.**
`discord.py` doesn't auto-load the Opus codec on Linux the way it does on Windows, so voice audio silently fails to encode even though `ffmpeg` runs fine. Confirm both:
```bash
which ffmpeg          # must resolve to a binary
ldconfig -p | grep opus   # must list libopus.so.0
```
The bot explicitly calls `discord.opus.load_opus("libopus.so.0")` on startup to work around this — if you ever move this to a distro where opus is packaged under a different filename, update that call to match (`ldconfig -p | grep opus` shows the exact name to use).

**Stale slash commands showing in Discord (e.g. old `/pay`, `/shop`).**
Discord caches the slash command list client-side. After removing a command from the code, restart the bot (so `on_ready` re-runs `bot.tree.sync()`) and restart your Discord client. If it persists, the command may have been registered as guild-specific by an old version of the bot, which a global sync won't clear.

**Music: `/play` fails with `HTTP Error 403: Forbidden` (either from `yt-dlp` itself or from `ffmpeg` opening the stream URL).**
YouTube regularly changes its extraction defenses, and `yt-dlp` ships frequent point-releases just to keep up — a `yt-dlp` even a couple months old will start getting 403'd. Fix:
```bash
./.venv/bin/pip install --upgrade yt-dlp
```
Then update the pinned version in `requirements.txt` to match. If `/play` breaks again later with a 403, this is the first thing to check before assuming it's the bot's own code.

## Notes

- This is a **maintenance / experimental repo**
- Features may break or change frequently
- Data is stored locally using JSON files
