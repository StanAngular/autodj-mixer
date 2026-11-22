---
name: reference-hermes-skill-sync
description: How the mixer skill reaches Hermes: nightly cron copies /opt/autodj-mixer/SKILL.md after git pull
metadata:
  type: reference
---

2026-11-20: Hermes cron `autodj-mixer-skill-sync` (06:00 daily, git pull then copy /opt/autodj-mixer/SKILL.md to /home/hermes/.hermes/skills/software-development/autodj-mixer/SKILL.md). Open snag: Hermes git remote needs a token in ~/.hermes/.env, SSH remote, or gh login. Edit the skill in the shared repo, not in Hermes's copy.
