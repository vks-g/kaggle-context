#!/bin/sh
# kctx installer: installs the `kctx` command with uv, then asks you a few questions.
#
#   curl -fsSL https://raw.githubusercontent.com/vks-g/kctx/main/install.sh | sh
#   curl -fsSL https://raw.githubusercontent.com/vks-g/kctx/main/install.sh | sh -s -- <competition-url>
#
# Environment:
#   KCTX_SPEC    what to install (default: kctx from PyPI; e.g. "git+https://github.com/vks-g/kctx" for main)
#   KCTX_NO_RUN  set to 1 to install without starting kctx
set -eu

SPEC="${KCTX_SPEC:-kctx}"

say() { printf '%s\n' "$*"; }
die() {
  printf 'kctx: %s\n' "$*" >&2
  exit 1
}

if ! command -v uv >/dev/null 2>&1; then
  say "Installing uv (Astral's Python package manager; it also fetches Python if needed)..."
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- https://astral.sh/uv/install.sh | sh
  else
    die "curl or wget is required to install uv"
  fi
  if [ -f "$HOME/.local/bin/env" ]; then
    # shellcheck disable=SC1091
    . "$HOME/.local/bin/env"
  fi
  PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi
command -v uv >/dev/null 2>&1 || die "uv was installed but isn't on PATH yet; open a new terminal and re-run"

say "Installing kctx..."
uv tool install --quiet --force --reinstall "$SPEC"

BIN="$(uv tool dir --bin)"
KCTX="$BIN/kctx"
[ -x "$KCTX" ] || die "install finished but $KCTX is missing"

case ":$PATH:" in
  *":$BIN:"*) ;;
  *) say "Tip: run 'uv tool update-shell' (or add $BIN to PATH) so 'kctx' works in new terminals." ;;
esac

if [ "${KCTX_NO_RUN:-0}" = "1" ]; then
  say "Installed. Run 'kctx' to start."
  exit 0
fi

# Under `curl | sh`, stdin is the pipe, not your keyboard, so reconnect the terminal.
# Prefer the real device (e.g. /dev/ttys003): macOS can't poll the /dev/tty alias with
# kqueue, which breaks prompt libraries and CLIs such as `claude`.
TTY_DEV=$(tty <&2 2>/dev/null) || TTY_DEV=/dev/tty
case "$TTY_DEV" in
  /dev/*) ;;
  *) TTY_DEV=/dev/tty ;;
esac
if (: <"$TTY_DEV") 2>/dev/null; then
  exec "$KCTX" "$@" <"$TTY_DEV"
fi
say "Installed. There's no interactive terminal here, so run 'kctx' yourself."
