// Draws Ira for iPhone's App Store icon (1024 x 1024, no transparency) from the
// four bars of src/ira/web/static/icon.svg, full bleed: iOS rounds the corners.
//
//     swift scripts/make-icon.swift Ira/Assets.xcassets/AppIcon.appiconset/AppIcon.png
import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

let size = 1024
let scale = CGFloat(size) / 32  // the SVG's viewBox is 32 x 32
guard CommandLine.arguments.count == 2,
    let context = CGContext(
        data: nil, width: size, height: size, bitsPerComponent: 8, bytesPerRow: 0,
        space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)
else {
    FileHandle.standardError.write(Data("usage: make-icon.swift OUT.png\n".utf8))
    exit(2)
}
context.setFillColor(CGColor(srgbRed: 0x1f / 255, green: 0x6f / 255, blue: 0x5c / 255, alpha: 1))
context.fill(CGRect(x: 0, y: 0, width: size, height: size))
context.setFillColor(CGColor(srgbRed: 1, green: 1, blue: 1, alpha: 1))
// (x, y, height) of each bar in the SVG, 3 wide with round ends; y measured from the top.
for (x, y, height) in [(7.0, 13.0, 6.0), (12.0, 9.0, 14.0), (17.0, 6.0, 20.0), (22.0, 11.0, 10.0)] {
    let rect = CGRect(x: x * scale, y: CGFloat(size) - (y + height) * scale, width: 3 * scale, height: height * scale)
    context.addPath(CGPath(roundedRect: rect, cornerWidth: 1.5 * scale, cornerHeight: 1.5 * scale, transform: nil))
}
context.fillPath()
let url = URL(fileURLWithPath: CommandLine.arguments[1])
guard let image = context.makeImage(),
    let destination = CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil)
else { exit(1) }
CGImageDestinationAddImage(destination, image, nil)
exit(CGImageDestinationFinalize(destination) ? 0 : 1)
