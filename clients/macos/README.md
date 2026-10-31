# Ira for Mac

An app with its own window that pairs with your own IRA server as a device and
lets Ira find, read and open your files and read the window you were in, when
you ask; and lets you talk to Ira by voice or by typing. Option-Space brings
its window forward.

The user guide, permissions and the developer notes are in
[docs/clients/macos.md](../../docs/clients/macos.md).

```bash
swift build             # debug build (the Command Line Tools are enough)
scripts/test.sh         # the tests
scripts/make-app.sh     # dist/Ira.app, dist/Ira-<version>.zip and .dmg
```

No third-party dependencies: AppKit, SwiftUI, AVFoundation, Spotlight
(NSMetadataQuery), PDFKit, ScreenCaptureKit, Vision, Security and URLSession
all come with macOS.
