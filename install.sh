#!/usr/bin/env bash
# Installs the yaksh CLI from a GitHub release.
#
#   curl -fsSL https://raw.githubusercontent.com/plivo-labs/yaksh/main/install.sh | bash
#
# YAKSH_VERSION installs one version, such as 0.2.1. The default is the newest release.
# YAKSH_INSTALL_DIR is where the binary goes. The default is ~/.yaksh/bin.
set -euo pipefail

repo="https://github.com/plivo-labs/yaksh/releases"
install_dir="${YAKSH_INSTALL_DIR:-$HOME/.yaksh/bin}"

fail() {
  echo "error: $*" >&2
  exit 1
}

case "$(uname -s)" in
  Linux) os=linux ;;
  Darwin) os=darwin ;;
  *) fail "the CLI has no build for $(uname -s). Build it from source: see the CLI docs" ;;
esac
case "$(uname -m)" in
  x86_64 | amd64) arch=amd64 ;;
  arm64 | aarch64) arch=arm64 ;;
  *) fail "the CLI has no build for $(uname -m). Build it from source: see the CLI docs" ;;
esac

if [ -n "${YAKSH_VERSION:-}" ]; then
  tag="v${YAKSH_VERSION#v}"
else
  # releases/latest redirects to releases/tag/<tag>. Both files then come from that one release.
  latest=$(curl -fsSL -o /dev/null -w '%{url_effective}' "$repo/latest") || fail "cannot find the newest release"
  tag="${latest##*/}"
fi
base="$repo/download/$tag"
archive="yaksh_${os}_${arch}.tar.gz"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp" "${staged:-}"' EXIT

curl -fsSL -o "$tmp/$archive" "$base/$archive" || fail "cannot download $base/$archive"
curl -fsSL -o "$tmp/checksums.txt" "$base/checksums.txt" || fail "cannot download $base/checksums.txt"

want=$(awk -v name="$archive" '$2 == name { print $1 }' "$tmp/checksums.txt")
[ -n "$want" ] || fail "checksums.txt has no line for $archive"
if command -v sha256sum >/dev/null 2>&1; then
  got=$(sha256sum "$tmp/$archive" | awk '{ print $1 }')
else
  got=$(shasum -a 256 "$tmp/$archive" | awk '{ print $1 }')
fi
[ "$got" = "$want" ] || fail "$archive does not match its checksum"

tar -xzf "$tmp/$archive" -C "$tmp" yaksh
mkdir -p "$install_dir"
# Copy next to the old binary, then rename: a rename in one folder replaces the file whole.
staged="$install_dir/.yaksh-install-$$"
cp "$tmp/yaksh" "$staged"
chmod 755 "$staged"
mv -f "$staged" "$install_dir/yaksh"

echo "installed yaksh $tag in $install_dir"
case ":$PATH:" in
  *":$install_dir:"*) ;;
  *) echo "add it to your PATH: export PATH=\"$install_dir:\$PATH\"" ;;
esac
