#!/bin/bash
# Docker entrypoint: bootstrap config files into the mounted volume, then run birkin.
set -e

BIRKIN_HOME="/opt/data"
INSTALL_DIR="/opt/birkin"

# --- Privilege dropping via gosu ---
# When started as root (the default), optionally remap the birkin user/group
# to match host-side ownership, fix volume permissions, then re-exec as birkin.
if [ "$(id -u)" = "0" ]; then
    if [ -n "$BIRKIN_UID" ] && [ "$BIRKIN_UID" != "$(id -u birkin)" ]; then
        echo "Changing birkin UID to $BIRKIN_UID"
        usermod -u "$BIRKIN_UID" birkin
    fi

    if [ -n "$BIRKIN_GID" ] && [ "$BIRKIN_GID" != "$(id -g birkin)" ]; then
        echo "Changing birkin GID to $BIRKIN_GID"
        groupmod -g "$BIRKIN_GID" birkin
    fi

    actual_birkin_uid=$(id -u birkin)
    if [ "$(stat -c %u "$BIRKIN_HOME" 2>/dev/null)" != "$actual_birkin_uid" ]; then
        echo "$BIRKIN_HOME is not owned by $actual_birkin_uid, fixing"
        chown -R birkin:birkin "$BIRKIN_HOME"
    fi

    echo "Dropping root privileges"
    exec gosu birkin "$0" "$@"
fi

# --- Running as birkin from here ---
source "${INSTALL_DIR}/.venv/bin/activate"

# Create essential directory structure.  Cache and platform directories
# (cache/images, cache/audio, platforms/whatsapp, etc.) are created on
# demand by the application — don't pre-create them here so new installs
# get the consolidated layout from get_birkin_dir().
# The "home/" subdirectory is a per-profile HOME for subprocesses (git,
# ssh, gh, npm …).  Without it those tools write to /root which is
# ephemeral and shared across profiles.  See issue #4426.
mkdir -p "$BIRKIN_HOME"/{cron,sessions,logs,hooks,memories,skills,skins,plans,workspace,home}

# .env
if [ ! -f "$BIRKIN_HOME/.env" ]; then
    cp "$INSTALL_DIR/.env.example" "$BIRKIN_HOME/.env"
fi

# config.yaml
if [ ! -f "$BIRKIN_HOME/config.yaml" ]; then
    cp "$INSTALL_DIR/cli-config.yaml.example" "$BIRKIN_HOME/config.yaml"
fi

# SOUL.md
if [ ! -f "$BIRKIN_HOME/SOUL.md" ]; then
    cp "$INSTALL_DIR/docker/SOUL.md" "$BIRKIN_HOME/SOUL.md"
fi

# Sync bundled skills (manifest-based so user edits are preserved)
if [ -d "$INSTALL_DIR/skills" ]; then
    python3 "$INSTALL_DIR/tools/skills_sync.py"
fi

exec birkin "$@"
