#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Install the ros2bag-converter skill for Claude Code and/or Codex CLI.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

install_claude() {
  local dst="$HOME/.claude/skills/ros2bag-converter"
  mkdir -p "$dst"
  cp -R "$HERE/SKILL.md" "$HERE/scripts" "$dst/"
  echo "Claude skill  -> $dst  (auto-discovered by Claude Code)"
}

install_codex() {
  local skill="$HOME/.codex/skills/ros2bag-converter"
  mkdir -p "$skill" "$HOME/.codex/prompts"
  cp -R "$HERE/scripts" "$skill/"
  sed "s|{{SKILL_DIR}}|$skill|g" "$HERE/codex/ros2bag-convert.md" \
    > "$HOME/.codex/prompts/ros2bag-convert.md"
  echo "Codex prompt  -> ~/.codex/prompts/ros2bag-convert.md   (run as /ros2bag-convert)"
  echo "Codex script  -> $skill/scripts/ros2bag_convert.py"
}

target="${1:-all}"
case "$target" in
  claude) install_claude ;;
  codex)  install_codex ;;
  all)    install_claude; install_codex ;;
  *) echo "usage: $0 [claude|codex|all]" >&2; exit 1 ;;
esac
echo "Done."
