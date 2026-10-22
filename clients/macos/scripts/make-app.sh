#!/bin/sh
# Build Ira.app, a zip and a dmg with Swift Package Manager and the Command
# Line Tools alone: no Xcode project, no Xcode.
#
#   scripts/make-app.sh              this Mac's architecture
#   UNIVERSAL=1 scripts/make-app.sh  Apple silicon and Intel in one app (slower)
#
# Output, in clients/macos/dist/:
#   Ira.app, Ira-<version>.zip, Ira-<version>.dmg
#
# The app is signed ad hoc ("codesign --sign -"): macOS runs it after a
# right-click and Open the first time. A Developer ID signature and
# notarization come when the project has an Apple Developer account.
set -eu

here=$(cd "$(dirname "$0")/.." && pwd)
repo=$(cd "$here/../.." && pwd)
cd "$here"

version=$(sed -n 's/.*static let version = "\(.*\)".*/\1/p' Sources/IraKit/Support/Version.swift)
build=$(git -C "$repo" rev-list --count HEAD 2>/dev/null || echo 1)
dist="$here/dist"
app="$dist/Ira.app"

arch_flags=""
if [ "${UNIVERSAL:-0}" = 1 ]; then
  arch_flags="--arch arm64 --arch x86_64"
fi

echo "Building Ira $version ($build)"
# shellcheck disable=SC2086
swift build -c release $arch_flags
# shellcheck disable=SC2086
bin=$(swift build -c release $arch_flags --show-bin-path)

rm -rf "$app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
cp "$bin/Ira" "$app/Contents/MacOS/Ira"
printf 'APPL????' > "$app/Contents/PkgInfo"

# The icon: the repository's mark, drawn at every size macOS asks for, with
# the margin macOS icons have.
icon_svg="$repo/src/ira/web/static/icon.svg"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
iconset="$work/Ira.iconset"
mkdir -p "$iconset"
if ! sips -s format png -z 824 824 "$icon_svg" --out "$work/mark.png" >/dev/null 2>&1; then
  # An older sips without SVG: Quick Look renders it instead.
  qlmanage -t -s 824 -o "$work" "$icon_svg" >/dev/null 2>&1
  mv "$work/icon.svg.png" "$work/mark.png"
fi
sips -p 1024 1024 "$work/mark.png" --out "$work/icon-1024.png" >/dev/null
for size in 16 32 128 256 512; do
  sips -z "$size" "$size" "$work/icon-1024.png" --out "$iconset/icon_${size}x${size}.png" >/dev/null
  double=$((size * 2))
  sips -z "$double" "$double" "$work/icon-1024.png" --out "$iconset/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$iconset" -o "$app/Contents/Resources/Ira.icns"

# Info.plist: a menu-bar app (no Dock icon), and a plain sentence for each
# permission macOS asks about.
cat > "$app/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key><string>in.ira.mac</string>
  <key>CFBundleName</key><string>Ira</string>
  <key>CFBundleDisplayName</key><string>Ira</string>
  <key>CFBundleExecutable</key><string>Ira</string>
  <key>CFBundleIconFile</key><string>Ira</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$version</string>
  <key>CFBundleVersion</key><string>$build</string>
  <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
  <key>CFBundleDevelopmentRegion</key><string>en</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSUIElement</key><true/>
  <key>LSApplicationCategoryType</key><string>public.app-category.productivity</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSHumanReadableCopyright</key><string>IRA is open source under the MIT licence.</string>
  <key>NSMicrophoneUsageDescription</key><string>Ira listens only after you press the mic button, so you can talk to it. Your voice goes only to your own Ira server.</string>
  <key>NSScreenCaptureUsageDescription</key><string>Ira reads the text of the window in front only when you ask what is on your screen. The text is read on this Mac; no picture leaves it.</string>
  <key>NSDocumentsFolderUsageDescription</key><string>Ira finds and reads a file in Documents only when you ask about it.</string>
  <key>NSDesktopFolderUsageDescription</key><string>Ira finds and reads a file on the Desktop only when you ask about it.</string>
  <key>NSDownloadsFolderUsageDescription</key><string>Ira finds and reads a file in Downloads only when you ask about it.</string>
  <key>NSRemovableVolumesUsageDescription</key><string>Ira reads a file on a drive only when you ask, and only from folders you added.</string>
  <key>NSNetworkVolumesUsageDescription</key><string>Ira reads a file on a network drive only when you ask, and only from folders you added.</string>
  <key>NSContactsUsageDescription</key><string>Ira looks up a person in your contacts only when you ask, to put a name to a number or find whom to write to.</string>
  <key>NSCalendarsFullAccessUsageDescription</key><string>Ira reads your calendar when you ask what is on, and adds an event only after your yes.</string>
  <key>NSCalendarsUsageDescription</key><string>Ira reads your calendar when you ask what is on, and adds an event only after your yes.</string>
  <key>NSRemindersFullAccessUsageDescription</key><string>Ira reads and adds reminders when you ask.</string>
  <key>NSRemindersUsageDescription</key><string>Ira reads and adds reminders when you ask.</string>
  <key>NSAppleEventsUsageDescription</key><string>Ira uses Mail, Notes and Messages only when you ask: to search and read, to draft an email for you to send, or to send a message after your yes.</string>
</dict>
</plist>
PLIST
plutil -lint "$app/Contents/Info.plist" >/dev/null

codesign --force --sign - --identifier in.ira.mac --timestamp=none "$app"
codesign --verify --strict "$app"

zip="$dist/Ira-$version.zip"
dmg="$dist/Ira-$version.dmg"
rm -f "$zip" "$dmg"
ditto -c -k --keepParent "$app" "$zip"

stage="$work/dmg"
mkdir -p "$stage"
ditto "$app" "$stage/Ira.app"
ln -s /Applications "$stage/Applications"
hdiutil create -quiet -volname "Ira" -srcfolder "$stage" -ov -format UDZO "$dmg"

echo "Built:"
echo "  $app"
echo "  $zip"
echo "  $dmg"
