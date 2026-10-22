#!/bin/sh
# Run the tests with whatever toolchain this Mac has.
#
# With Xcode, `swift test` is all it takes. With only the Command Line Tools,
# the Swift Testing macros live in a folder the compiler is not told about, so
# this passes it on. CI runs this same script.
set -eu
cd "$(dirname "$0")/.."
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
