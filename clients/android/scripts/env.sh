# shellcheck shell=sh
# The Android toolchain for this shell, without touching your shell profile.
#   . clients/android/scripts/env.sh
# JDK 17 and the Android SDK; set JAVA_HOME or ANDROID_HOME first to use others.

if [ -z "${JAVA_HOME:-}" ] || ! "$JAVA_HOME/bin/java" -version 2>&1 | grep -q '"17\.'; then
  if [ -x /usr/libexec/java_home ]; then
    JAVA_HOME="$(/usr/libexec/java_home -v 17 2>/dev/null)"
  fi
fi
export JAVA_HOME
export ANDROID_HOME="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
export ANDROID_SDK_ROOT="$ANDROID_HOME"

for dir in \
  "$JAVA_HOME/bin" \
  "$ANDROID_HOME/platform-tools" \
  "$ANDROID_HOME/cmdline-tools/latest/bin" \
  /opt/homebrew/share/android-commandlinetools/cmdline-tools/latest/bin; do
  case ":$PATH:" in
    *":$dir:"*) ;;
    *) [ -d "$dir" ] && PATH="$dir:$PATH" ;;
  esac
done
export PATH
