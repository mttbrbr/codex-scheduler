#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$HOME/.agents/skills/codex-scheduler"
BIN_DIR="$HOME/.local/bin"
mkdir -p "$SKILL_DIR/scripts" "$BIN_DIR"
install -m 644 "$HERE/SKILL.md" "$SKILL_DIR/SKILL.md"
install -m 755 "$HERE/scripts/codex_scheduler.py" "$SKILL_DIR/scripts/codex_scheduler.py"
ln -sfn "$SKILL_DIR/scripts/codex_scheduler.py" "$BIN_DIR/codex-scheduler"
printf '\nSkill: %s\nCLI: %s\n' "$SKILL_DIR" "$BIN_DIR/codex-scheduler"
printf 'Se ~/.local/bin non è nel PATH, usa il percorso completo.\nRiavvia Codex CLI per rilevare la Skill.\n'
