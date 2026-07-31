#!/usr/bin/env bash
# Adds/removes an opportunistic secondary node (e.g. a laptop joined over Tailscale) as an
# HAProxy backend server for the `web` service. See DEPLOY_OPPORTUNISTIC_NODE.md for the
# full setup this is one step of.
#
# Usage:
#   scripts/add-opportunistic-node.sh add <name> <host:port>
#   scripts/add-opportunistic-node.sh remove <name>
#   scripts/add-opportunistic-node.sh list
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CFG="$APP_DIR/haproxy/haproxy.cfg"
BEGIN="    # BEGIN-OPPORTUNISTIC-NODES"
END="    # END-OPPORTUNISTIC-NODES"

usage() {
  echo "Usage:"
  echo "  $0 add <name> <host:port>   # e.g. $0 add laptop1 100.64.12.34:8000"
  echo "  $0 remove <name>"
  echo "  $0 list"
  exit 2
}

[[ -f "$CFG" ]] || { echo "Not found: $CFG" >&2; exit 1; }
grep -qF "$BEGIN" "$CFG" || { echo "Marker '$BEGIN' not found in $CFG — has the file been edited?" >&2; exit 1; }

action="${1:-}"
case "$action" in
  list)
    awk -v b="$BEGIN" -v e="$END" '
      $0 == b {inside=1; next}
      $0 == e {inside=0}
      inside && NF {print}
    ' "$CFG"
    ;;

  add)
    name="${2:?name required, e.g. laptop1}"
    addr="${3:?host:port required, e.g. 100.64.12.34:8000}"
    [[ "$name" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "name must be alphanumeric/-/_ only" >&2; exit 1; }
    [[ "$addr" =~ ^[A-Za-z0-9._-]+:[0-9]+$ ]] || { echo "addr must look like host:port" >&2; exit 1; }

    tmp="$(mktemp)"
    awk -v b="$BEGIN" -v e="$END" -v name="$name" -v addr="$addr" '
      $0 == b {
        print
        inside=1
        seen_names[name]=1
        next
      }
      $0 == e {
        inside=0
        print "    server node-" name " " addr " check inter 10s fall 3 rise 2"
        print
        next
      }
      inside {
        # Drop any existing line for this node name — add is idempotent (re-add = update address).
        if ($0 ~ ("server node-" name " ")) next
        print
        next
      }
      { print }
    ' "$CFG" > "$tmp"
    mv "$tmp" "$CFG"
    echo "Added/updated node-${name} -> ${addr} in $CFG"
    ;;

  remove)
    name="${2:?name required}"
    tmp="$(mktemp)"
    awk -v b="$BEGIN" -v e="$END" -v name="$name" '
      $0 == b {inside=1; print; next}
      $0 == e {inside=0; print; next}
      inside && $0 ~ ("server node-" name " ") {next}
      {print}
    ' "$CFG" > "$tmp"
    mv "$tmp" "$CFG"
    echo "Removed node-${name} (if present) from $CFG"
    ;;

  *)
    usage
    ;;
esac

if [[ "$action" == "add" || "$action" == "remove" ]]; then
  echo "Restarting lb to apply..."
  ( cd "$APP_DIR" && docker compose -f docker-compose.prod.yml up -d --no-deps --force-recreate lb )
  echo "Done. Check: docker compose -f docker-compose.prod.yml exec lb cat /usr/local/etc/haproxy/haproxy.cfg"
fi
