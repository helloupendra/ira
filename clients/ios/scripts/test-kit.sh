#!/bin/sh
# Run IraPhoneKit's tests on this Mac, with whatever toolchain it has.
#
# The kit builds for macOS too, so its tests need no iOS simulator. With only
# the Command Line Tools, the Swift Testing macros live in a folder the
# compiler is not told about, so this passes it on. CI runs the same tests on
# an iOS simulator as well (scripts/ci.sh).
set -eu
cd "$(dirname "$0")/../IraPhoneKit"
plugins=""
developer=$(xcode-select -p 2>/dev/null || true)
case "$developer" in
  */CommandLineTools)
    dir="$developer/usr/lib/swift/host/plugins/testing"
    if [ -d "$dir" ]; then plugins="-Xswiftc -plugin-path -Xswiftc $dir"; fi
    ;;
esac
# shellcheck disable=SC2086
exec swift test $plugins "$@"
