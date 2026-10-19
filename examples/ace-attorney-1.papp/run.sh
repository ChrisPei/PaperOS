#!/bin/sh
set -eu
game_dir=/mnt/us/paperos/games/ace-attorney-1
game_file="$game_dir/game.nds"
if [ -f "$game_dir/current.sha256" ]; then
    IFS= read -r game_digest < "$game_dir/current.sha256" || true
    case "$game_digest" in
        *[!0-9a-f]*|'') ;;
        *) if [ "${#game_digest}" -eq 64 ]; then game_file="$game_dir/$game_digest.nds"; fi ;;
    esac
fi
exec "$PAPEROS_APP_DIR/paperos-nds" --standalone \
    --nds-rom "$game_file" \
    --nds-data "$PAPEROS_DATA_DIR" \
    2>"$PAPEROS_DATA_DIR/session.log"
