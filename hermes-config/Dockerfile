# Thin wrapper over the official Nous Research Hermes image.
# Goal: keep Nous's runtime untouched, but add GIT-MANAGED skills baked
# into the image at a path OUTSIDE the /opt/data volume, so the volume
# mount can never shadow them (Option A).
FROM nousresearch/hermes-agent:latest

# Git is the source of truth for these skills. They land outside /opt/data.
# A one-time entry in /opt/data/config.yaml (skills.external_dirs) tells
# Hermes to also scan this directory. See config.snippet.yaml + README.
COPY skills/ /opt/skills-repo/

# The base image provides the runtime. The start command ("gateway run")
# is set in railway.json / Railway's Deploy settings, matching how the
# service runs today.
