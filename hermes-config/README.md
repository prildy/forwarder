# hermes-config

Git-managed skills + config for the Hermes Agent running on Railway.

This repo builds a thin image **on top of** `nousresearch/hermes-agent:latest`
and bakes the skills under `skills/` into the image at `/opt/skills-repo`
(outside the `/opt/data` volume, so the volume mount can't hide them).
Editing a skill → push → Railway rebuilds → agent picks it up on next deploy.
Runtime data (DB, sessions, memories) stays on the `/opt/data` volume.

## Layout
```
Dockerfile            # FROM nousresearch/hermes-agent + COPY skills -> /opt/skills-repo
railway.json          # Dockerfile builder + start command
.dockerignore         # keep secrets / volume data out of the build
.gitignore
config.snippet.yaml   # ONE-TIME edit to apply to /opt/data/config.yaml
skills/<category>/<skill>/SKILL.md
```

## One-time Railway switch (from Source Image -> GitHub)
1. Service -> Settings -> Source: **Disconnect** `nousresearch/hermes-agent:latest`.
2. Connect this GitHub repo + branch. "Deploy on push" turns on automatically.
3. Leave the `/opt/data` volume, Variables (API keys, API_SERVER_ENABLED=true,
   port 8642) and private networking exactly as they are — none are in git.
4. Merge `config.snippet.yaml` into `/opt/data/config.yaml` on the volume (once),
   then restart the service.

## Verify before relying on it
- Confirm `skills.external_dirs` is the correct key for your Hermes version.
- Confirm the start command: today the service runs `gateway run`; keep it
  (railway.json sets it, overriding the image default).
- Skill naming: `SKILL.md` has `name: bbma-playbook` but its folder is `bbma`.
  Align these (rename folder to `bbma-playbook`, or set `name: bbma`) to be safe.

## Deploy data expected by the agent (/opt/data on the volume)
.env, config.yaml, sessions/, skills/, memories/, home/, logs/
