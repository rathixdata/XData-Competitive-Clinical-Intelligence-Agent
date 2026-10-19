#!/bin/bash
# XData CI Agent - one-command install and start for macOS (also works on Linux).
#
#   curl -fsSL https://raw.githubusercontent.com/rathixdata/XData-Competitive-Clinical-Intelligence-Agent/refs/heads/claude/laughing-knuth-16lb2c/desktop/install-mac.sh | bash
#
# Needs nothing pre-installed: no Docker, Homebrew, Xcode, Python, Node or administrator password.
# Everything goes into ~/XData-CI-Agent (its own Python, Node, the app and an embedded PostgreSQL with
# pgvector). Running the command again updates the app and keeps your data. A "Start XData CI Agent"
# icon is put on your Desktop for later starts.
set -euo pipefail

REPO="rathixdata/XData-Competitive-Clinical-Intelligence-Agent"
BRANCH="${XDATA_BRANCH:-claude/laughing-knuth-16lb2c}"
HOME_DIR="${XDATA_HOME:-$HOME/XData-CI-Agent}"
APP="$HOME_DIR/app"
TOOLS="$HOME_DIR/tools"
VENV="$HOME_DIR/venv"
NODE_VERSION="22.12.0"
PGSERVER_VERSION="0.1.4"

say() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
fail() {
  printf '\n\033[1;31mThe installation stopped: %s\033[0m\n' "$*"
  printf 'Please send a screenshot of this window so it can be fixed.\n'
  exit 1
}
trap 'fail "a step failed (line $LINENO)"' ERR

case "$(uname -s)" in
  Darwin) OS=darwin ;;
  Linux) OS=linux ;;
  *) fail "this installer supports macOS and Linux" ;;
esac
case "$(uname -m)" in
  arm64 | aarch64) ARCH=arm64 ;;
  x86_64 | amd64) ARCH=x64 ;;
  *) fail "unsupported processor type $(uname -m)" ;;
esac

mkdir -p "$HOME_DIR" "$TOOLS"
cd "$HOME_DIR"

printf '\n\033[1mXData Competitive & Clinical Intelligence Agent\033[0m\n'
printf 'Installing into %s (about 5 minutes the first time).\n' "$HOME_DIR"

# ---- your sign-in email (asked once, on the first install) -------------------------------------
if [ ! -f "$HOME_DIR/settings.env" ] && [ -z "${XDATA_SETUP_EMAIL:-}" ] && [ -r /dev/tty ]; then
  printf '\nWhich email address do you want to sign in with? '
  read -r XDATA_SETUP_EMAIL < /dev/tty || true
fi
export XDATA_SETUP_EMAIL="${XDATA_SETUP_EMAIL:-}"

# ---- uv: installs a private Python, no admin rights needed ---------------------------------------
UV="${XDATA_UV:-}"
if [ -z "$UV" ]; then
  if command -v uv > /dev/null 2>&1; then
    UV="$(command -v uv)"
  else
    UV="$TOOLS/uv/uv"
    if [ ! -x "$UV" ]; then
      say "Downloading the Python installer (uv)"
      curl -fsSL https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$TOOLS/uv" UV_NO_MODIFY_PATH=1 sh > /dev/null
    fi
  fi
fi
[ -x "$UV" ] || fail "uv was not installed"

# ---- the app itself -------------------------------------------------------------------------------
say "Downloading the latest version of the app"
rm -rf "$APP.new" && mkdir -p "$APP.new"
if [ -n "${XDATA_SOURCE_TARBALL:-}" ]; then
  tar -xzf "$XDATA_SOURCE_TARBALL" -C "$APP.new" --strip-components=1
else
  curl -fsSL "https://codeload.github.com/$REPO/tar.gz/refs/heads/$BRANCH" | tar -xz -C "$APP.new" --strip-components=1
fi
[ -f "$APP.new/desktop/xdata_local.py" ] || fail "the download is incomplete"

# ---- Node.js (only used to build the web pages) ---------------------------------------------------
NODE_DIR="${XDATA_NODE_DIR:-$TOOLS/node-v$NODE_VERSION}"
if [ ! -x "$NODE_DIR/bin/node" ]; then
  say "Downloading Node.js $NODE_VERSION (used to build the web pages)"
  mkdir -p "$NODE_DIR"
  curl -fsSL "https://nodejs.org/dist/v$NODE_VERSION/node-v$NODE_VERSION-$OS-$ARCH.tar.gz" | tar -xz -C "$NODE_DIR" --strip-components=1
fi

say "Building the web app"
(
  cd "$APP.new/frontend"
  export PATH="$NODE_DIR/bin:$PATH"
  npm ci --no-audit --no-fund --loglevel=error > "$HOME_DIR/npm-install.log" 2>&1 || { tail -20 "$HOME_DIR/npm-install.log"; exit 1; }
  npm run build > "$HOME_DIR/web-build.log" 2>&1 || { tail -20 "$HOME_DIR/web-build.log"; exit 1; }
  rm -rf node_modules # not needed at run time; keeps the install small
)

# ---- Python environment with the backend and an embedded PostgreSQL --------------------------------
say "Installing Python and the app's components"
"$UV" venv --quiet --allow-existing --python 3.11 "$VENV"
"$UV" pip install --quiet --python "$VENV/bin/python" "$APP.new/backend" "pgserver==$PGSERVER_VERSION"

rm -rf "$APP.old"
[ -d "$APP" ] && mv "$APP" "$APP.old"
mv "$APP.new" "$APP"
rm -rf "$APP.old"

# ---- a Desktop icon for later starts ---------------------------------------------------------------
LAUNCHER="$HOME_DIR/Start XData CI Agent.command"
cat > "$LAUNCHER" << EOF
#!/bin/bash
# Starts XData CI Agent and opens it in your browser. Close this window (or press Ctrl-C) to stop it.
exec "$VENV/bin/python" "$APP/desktop/xdata_local.py"
EOF
chmod +x "$LAUNCHER"
if [ -d "$HOME/Desktop" ]; then
  cp "$LAUNCHER" "$HOME/Desktop/Start XData CI Agent.command"
  chmod +x "$HOME/Desktop/Start XData CI Agent.command"
fi

trap - ERR
say "Installed. Starting XData CI Agent"
printf 'Next time, double-click "Start XData CI Agent" on your Desktop.\n'
exec "$VENV/bin/python" "$APP/desktop/xdata_local.py" < /dev/null
