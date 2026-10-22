import AppKit
import CoreText
import Foundation
import Testing
@testable import IraKit

@Suite("What Ira may read")
struct PathPolicyTests {
    let home: URL
    let policy: PathPolicy

    init() throws {
        home = try temporaryFolder()
        policy = PathPolicy(home: home)
    }

    @Test(arguments: [
        "~/Library/Keychains/login.keychain-db",
        "~/Library/Mail/V10/x.emlx",
        "~/Library/Application Support/Google/Chrome/Default/Cookies",
        "~/.ssh/id_ed25519",
        "~/.aws/credentials",
        "~/.gnupg/secring.gpg",
        "~/.config/gh/hosts.yml",
        "~/.kube/config",
        "~/.docker/config.json",
        "~/.netrc",
        "~/.zsh_history",
        "~/Projects/app/.env",
        "~/Projects/app/.env.production",
        "~/Projects/app/.git/config",
        "~/Desktop/server.pem",
        "~/Desktop/signing.key",
        "~/Desktop/cert.p12",
        "~/Documents/id_rsa",
        "~/Downloads/credentials",
        "~/Documents/vault.kdbx",
    ])
    func deniedEvenInsideHome(path: String) {
        #expect(policy.refusal(path) != nil, "should refuse \(path)")
    }

    @Test(arguments: [
        "/etc/passwd",
        "/Library/Keychains/System.keychain",
        "/private/var/db/x",
        "/Users/someone-else/Documents/a.pdf",
        "/Volumes/Backup/a.pdf",
    ])
    func outsideHomeIsRefused(path: String) {
        #expect(policy.refusal(path) != nil, "should refuse \(path)")
    }

    @Test func relativePathsAreRefused() {
        #expect(policy.refusal("Documents/a.pdf") == "give the full path, starting with / or ~/")
    }

    @Test(arguments: ["~/Documents/invoice.pdf", "~/Downloads/notes.md", "~/Desktop/Project Plan.docx"])
    func ordinaryFilesAreAllowed(path: String) {
        #expect(policy.refusal(path) == nil)
    }

    @Test func linksAreFollowed() throws {
        let ssh = home.appendingPathComponent(".ssh")
        try FileManager.default.createDirectory(at: ssh, withIntermediateDirectories: true)
        try "secret".write(to: ssh.appendingPathComponent("id_ed25519"), atomically: true, encoding: .utf8)
        let desktop = home.appendingPathComponent("Desktop")
        try FileManager.default.createDirectory(at: desktop, withIntermediateDirectories: true)
        let link = desktop.appendingPathComponent("innocent.txt")
        try FileManager.default.createSymbolicLink(at: link, withDestinationURL: ssh.appendingPathComponent("id_ed25519"))
        #expect(policy.refusal(link.path) != nil)
        let folderLink = desktop.appendingPathComponent("keys")
        try FileManager.default.createSymbolicLink(at: folderLink, withDestinationURL: ssh)
        #expect(policy.refusal(folderLink.appendingPathComponent("anything").path) != nil)
    }

    @Test func chosenFoldersNarrowIt() {
        let narrow = PathPolicy(home: home, only: ["~/Documents"])
        #expect(narrow.refusal("~/Documents/a.pdf") == nil)
        #expect(narrow.refusal("~/Downloads/a.pdf") == "that is outside the folders Ira may use on this Mac")
    }

    @Test func addedFoldersOutsideHome() throws {
        let drive = try temporaryFolder()
        let wider = PathPolicy(home: home, extra: [drive.path])
        #expect(wider.refusal(drive.appendingPathComponent("a.pdf").path) == nil)
        #expect(wider.refusal(drive.appendingPathComponent(".secret/a.pdf").path) != nil)
        let system = PathPolicy(home: home, extra: ["/etc"])
        #expect(system.refusal("/etc/hosts") == "Ira never reads system folders")
    }

    @Test func displayUsesTilde() {
        #expect(policy.display(home.appendingPathComponent("Downloads/a.pdf")) == "~/Downloads/a.pdf")
    }

    @Test func openingNeverRunsThings() throws {
        let downloads = home.appendingPathComponent("Downloads")
        try FileManager.default.createDirectory(at: downloads, withIntermediateDirectories: true)
        let script = downloads.appendingPathComponent("run")
        try "#!/bin/sh\necho hi\n".write(to: script, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: script.path)
        #expect(Toolbox.openRefusal(script.path, policy: policy) == "I never open programs or scripts")
        for name in ["setup.command", "install.pkg", "evil.scpt", "link.webloc", "x.sh", "a.terminal"] {
            #expect(Toolbox.openRefusal(downloads.appendingPathComponent(name).path, policy: policy) != nil, "\(name)")
        }
        #expect(Toolbox.openRefusal(downloads.appendingPathComponent("report.pdf").path, policy: policy) == nil)
        #expect(Toolbox.openRefusal("/Applications/Safari.app", policy: policy) == nil)
        #expect(Toolbox.openRefusal(downloads.appendingPathComponent("Fake.app").path, policy: policy)
            == "I open apps only from the Applications folders")
        #expect(Toolbox.openRefusal("~/.ssh/config", policy: policy) != nil)
    }
}

@Suite("Reading files")
struct FileTextTests {
    @Test func docxFromAFixture() throws {
        let url = try #require(Bundle.module.url(forResource: "tiny", withExtension: "docx", subdirectory: "Fixtures"))
        let text = try DocxText.extract(from: Data(contentsOf: url))
        #expect(text == "Sunrise Dental Clinic\nInvoice 42\tTotal: 1,200 & tax\nकल सुबह 9 बजे\nSecond line")
        let read = try FileText.read(url, maxChars: 20)
        #expect(read.kind == "Word document")
        #expect(read.truncated)
        #expect(read.text == "Sunrise Dental Clini")
    }

    @Test func notADocx() {
        #expect(throws: ToolFailure.self) { try DocxText.extract(from: Data("hello, I am not a zip file at all".utf8)) }
        #expect(throws: ToolFailure.self) { try DocxText.extract(from: Data()) }
    }

    @Test func aDamagedDocx() throws {
        let url = try #require(Bundle.module.url(forResource: "tiny", withExtension: "docx", subdirectory: "Fixtures"))
        var data = try Data(contentsOf: url)
        let name = try #require(data.range(of: Data("word/document.xml".utf8)))
        data.replaceSubrange(name.upperBound + 4..<name.upperBound + 64, with: Data(repeating: 0, count: 60))
        #expect(throws: ToolFailure.self) { try DocxText.extract(from: data) }
    }

    /// A one-page PDF with real text, drawn with Core Graphics: no fixture needed.
    static func makePDF(_ lines: [String], at url: URL) throws {
        var box = CGRect(x: 0, y: 0, width: 400, height: 300)
        let context = try #require(CGContext(url as CFURL, mediaBox: &box, nil))
        context.beginPDFPage(nil)
        let font = CTFontCreateWithName("Helvetica" as CFString, 14, nil)
        for (index, line) in lines.enumerated() {
            let attributed = NSAttributedString(string: line, attributes: [.font: font])
            let ctLine = CTLineCreateWithAttributedString(attributed)
            context.textPosition = CGPoint(x: 20, y: 260 - CGFloat(index) * 24)
            CTLineDraw(ctLine, context)
        }
        context.endPDFPage()
        context.closePDF()
    }

    @Test func pdfText() throws {
        let folder = try temporaryFolder()
        let url = folder.appendingPathComponent("invoice.pdf")
        try FileTextTests.makePDF(["Invoice 42 for Sunrise Dental", "Total due 1200"], at: url)
        let read = try FileText.read(url, maxChars: 20_000)
        #expect(read.kind == "PDF")
        #expect(read.pages == 1)
        #expect(read.text.contains("Invoice 42"))
        #expect(read.text.contains("Total due 1200"))
        #expect(!read.truncated)
        let cut = try FileText.read(url, maxChars: 10)
        #expect(cut.truncated)
        #expect(cut.text.count == 10)
    }

    @Test func aScannedPDFSaysSo() throws {
        let folder = try temporaryFolder()
        let url = folder.appendingPathComponent("scan.pdf")
        try FileTextTests.makePDF([], at: url)
        #expect(throws: ToolFailure.self) { try FileText.read(url, maxChars: 100) }
    }

    @Test func textMarkdownRtfAndHtml() throws {
        let folder = try temporaryFolder()
        let notes = folder.appendingPathComponent("notes.md")
        try "# Plan\n\n- kal subah 9 baje\r\n".write(to: notes, atomically: true, encoding: .utf8)
        let md = try FileText.read(notes, maxChars: 1000)
        #expect(md.kind == "Markdown")
        #expect(md.text == "# Plan\n\n- kal subah 9 baje\n")

        let rtf = folder.appendingPathComponent("letter.rtf")
        let attributed = NSAttributedString(string: "Dear Avery, your appointment is at 14:30.")
        let data = try attributed.data(
            from: NSRange(location: 0, length: attributed.length), documentAttributes: [.documentType: NSAttributedString.DocumentType.rtf])
        try data.write(to: rtf)
        #expect(try FileText.read(rtf, maxChars: 1000).text.contains("appointment is at 14:30"))

        let page = folder.appendingPathComponent("page.html")
        try "<html><script>steal()</script><p>Hello <b>there</b></p></html>".write(to: page, atomically: true, encoding: .utf8)
        let html = try FileText.read(page, maxChars: 1000).text
        #expect(html.contains("Hello"))
        #expect(!html.contains("steal"))
    }

    @Test func refusals() throws {
        let folder = try temporaryFolder()
        #expect(throws: ToolFailure("there is no file at that path")) {
            try FileText.read(folder.appendingPathComponent("missing.txt"), maxChars: 10)
        }
        #expect(throws: ToolFailure("that is a folder; ask me to find files in it instead")) {
            try FileText.read(folder, maxChars: 10)
        }
        let picture = folder.appendingPathComponent("photo.heic")
        try Data([0, 1, 2]).write(to: picture)
        #expect(throws: ToolFailure.self) { try FileText.read(picture, maxChars: 10) }
    }
}

@Suite("Tool definitions")
struct ToolSchemaTests {
    @Test func everyToolIsWellFormed() throws {
        let names = Toolbox.definitions.compactMap { $0["name"]?.stringValue }
        #expect(names.count == Toolbox.definitions.count)
        #expect(names.count <= 30)
        #expect(Set(names).count == names.count)
        for tool in Toolbox.definitions {
            let name = try #require(tool["name"]?.stringValue)
            #expect(name.range(of: #"^[a-z][a-z0-9_]{2,40}$"#, options: .regularExpression) != nil, "\(name)")
            #expect((tool["description"]?.stringValue?.count ?? 0) > 20, "\(name)")
            #expect((tool["description"]?.stringValue?.count ?? 0) <= 1000, "\(name)")
            let parameters = try #require(tool["parameters"])
            #expect(parameters["type"] == "object", "\(name)")
            #expect(parameters["properties"]?.objectValue != nil, "\(name)")
            #expect(parameters.encoded().utf8.count < 8 * 1024, "\(name)")
            for required in parameters["required"]?.arrayValue ?? [] {
                #expect(parameters["properties"]?[required.stringValue ?? ""] != nil, "\(name)")
            }
            let skill = try #require(tool["skill"]?.stringValue)
            #expect(skill.range(of: #"^[a-z][a-z0-9_]{1,30}$"#, options: .regularExpression) != nil)
            let tier = try #require(tool["tier"]?.intValue)
            #expect((0...3).contains(tier))
        }
    }

    @Test func skillsAndTiers() {
        func spec(_ name: String) -> (String?, Int?) {
            let tool = Toolbox.definitions.first { $0["name"]?.stringValue == name }
            return (tool?["skill"]?.stringValue, tool?["tier"]?.intValue)
        }
        #expect(spec("files_find") == ("files", 0))
        #expect(spec("file_read") == ("files", 0))
        #expect(spec("file_open") == ("files", 1))
        #expect(spec("screen_read") == ("screen", 0))
    }

    @Test func theHelloFitsAFrame() {
        let hello = DeviceProtocol.hello(label: "Studio Mac", tools: Toolbox.definitions).encoded()
        #expect(hello.utf8.count < DeviceProtocol.maxFrameBytes)
    }

    @Test func argumentsAreChecked() async {
        let home = FileManager.default.temporaryDirectory
        let toolbox = Toolbox(policy: { PathPolicy(home: home) }, frontApp: { nil }, opener: { _ in true }, log: IraLog(directory: nil), record: { _ in })
        await #expect(throws: ToolFailure("unknown argument(s): sneaky")) {
            try await toolbox.call("file_read", args: ["path": "~/a.txt", "sneaky": true])
        }
        await #expect(throws: ToolFailure("path must be text")) {
            try await toolbox.call("file_read", args: ["path": 3])
        }
        await #expect(throws: ToolFailure("this Mac has no tool 'rm_rf'")) {
            try await toolbox.call("rm_rf", args: [:])
        }
        await #expect(throws: ToolFailure("arguments must be an object")) {
            try await toolbox.call("files_find", args: "everything")
        }
        await #expect(throws: ToolFailure.self) {
            try await toolbox.call("files_find", args: ["kind": "passwords"])
        }
    }

    @Test func whatIReadRecordsNamesNotContents() async throws {
        let home = try temporaryFolder()
        let file = home.appendingPathComponent("Documents/secret-plan.txt")
        try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        try "the launch is on Friday".write(to: file, atomically: true, encoding: .utf8)
        let log = EventLog<Activity>()
        let toolbox = Toolbox(policy: { PathPolicy(home: home) }, frontApp: { nil }, opener: { _ in true }, log: IraLog(directory: nil), record: { log.add($0) })
        let result = try await toolbox.call("file_read", args: ["path": .string(file.path)])
        #expect(result["text"] == "the launch is on Friday")
        #expect(result["summary"] == "Read secret-plan.txt (text).")
        let entry = try #require(log.all.first)
        #expect(entry.tool == "file_read")
        #expect(entry.ok)
        #expect(entry.target.hasSuffix("secret-plan.txt"))
        #expect(!entry.target.contains("Friday"))

        await #expect(throws: ToolFailure.self) {
            try await toolbox.call("file_read", args: ["path": "~/.ssh/id_rsa"])
        }
        #expect(log.all.count == 2)
        #expect(log.all[1].ok == false)
    }

    @Test func openGoesThroughTheOpener() async throws {
        let home = try temporaryFolder()
        let file = home.appendingPathComponent("report.pdf")
        try Data("%PDF".utf8).write(to: file)
        let opened = EventLog<URL>()
        let toolbox = Toolbox(policy: { PathPolicy(home: home) }, frontApp: { nil }, opener: { opened.add($0); return true }, log: IraLog(directory: nil), record: { _ in })
        let result = try await toolbox.call("file_open", args: ["path": .string(file.path)])
        #expect(result["summary"] == "Opened report.pdf.")
        #expect(opened.all == [file])
    }
}

@Suite("Finding files")
struct FileSearchTests {
    @Test func predicateWordsKindAndDate() {
        let now = Date(timeIntervalSince1970: 1_800_000_000)
        let query = FileSearch.Query(text: "tax  invoice*", kind: "pdf", modifiedWithinDays: 2, folder: nil)
        #expect(query.words == ["tax", "invoice"])
        let format = FileSearch.predicate(for: query, now: now).predicateFormat
        #expect(format.contains("kMDItemFSName LIKE[cd] \"*tax*\""))
        #expect(format.contains("kMDItemTextContent CONTAINS[cd] \"invoice\""))
        #expect(format.contains("kMDItemContentTypeTree == \"com.adobe.pdf\""))
        #expect(format.contains("kMDItemFSContentChangeDate >= CAST("))
        #expect(format.contains("kMDItemDateAdded >= CAST("))
    }

    /// Spotlight refuses an AND or OR with one part (the app crashed on it once).
    @Test(arguments: [
        FileSearch.Query(text: "irae2emarker", kind: nil, modifiedWithinDays: nil, folder: nil),
        FileSearch.Query(text: nil, kind: "pdf", modifiedWithinDays: nil, folder: nil),
        FileSearch.Query(text: "a b", kind: "image", modifiedWithinDays: 3, folder: nil),
        FileSearch.Query(text: nil, kind: nil, modifiedWithinDays: nil, folder: nil),
    ])
    func noCompoundHasASinglePart(query: FileSearch.Query) {
        func check(_ predicate: NSPredicate) {
            guard let compound = predicate as? NSCompoundPredicate else { return }
            #expect(compound.subpredicates.count >= 2, "\(compound.predicateFormat)")
            for case let part as NSPredicate in compound.subpredicates { check(part) }
        }
        check(FileSearch.predicate(for: query))
    }

    @Test func anEmptyQueryMeansRecentFiles() {
        let format = FileSearch.predicate(for: FileSearch.Query(text: "", kind: nil, modifiedWithinDays: nil, folder: nil)).predicateFormat
        #expect(format.contains("kMDItemFSContentChangeDate >= "))
    }

    @Test func folderNames() {
        let home = URL(fileURLWithPath: "/Users/avery")
        #expect(FileSearch.folderPath("downloads", home: home) == "/Users/avery/Downloads")
        #expect(FileSearch.folderPath("~/Projects", home: home) == "~/Projects")
        #expect(FileSearch.folderPath("Projects/app", home: home) == "/Users/avery/Projects/app")
    }
}

@Suite("Finding a folder by what you call it")
struct FolderMatchTests {
    // A folder called invoice-reminder-service, asked for the ways people say it.
    @Test(arguments: ["invoicereminder service", "Invoicereminder servise", "invoice reminder service", "reminder service", "invo reminder"])
    func findsTheService(query: String) {
        #expect(FolderMatch.score(query: query, name: "invoice-reminder-service") != nil, "\(query)")
    }

    @Test(arguments: ["client-data", "CATALOG.md", "service-room-photos-2019", "reminder"])
    func notEverythingMatches(name: String) {
        #expect(FolderMatch.score(query: "invoicereminder service", name: name) == nil, "\(name)")
    }

    @Test func exactAndPrefixRankFirst() throws {
        let exact = try #require(FolderMatch.score(query: "invoice reminder service", name: "invoice-reminder-service"))
        let prefix = try #require(FolderMatch.score(query: "invoice reminder", name: "invoice-reminder-service"))
        let fuzzy = try #require(FolderMatch.score(query: "invoicereminder servise", name: "invoice-reminder-service"))
        #expect(exact > prefix)
        #expect(prefix > fuzzy)
        #expect(FolderMatch.words("IraForMac_v2-final") == ["ira", "for", "mac", "v2", "final"])
    }

    @Test func aShortWalkFindsItWhereSpotlightCannot() throws {
        let home = try temporaryFolder()
        let manager = FileManager.default
        for path in ["Documents/GitHub/invoice-reminder-service/src", "Documents/GitHub/ira", "Documents/notes",
                     "Documents/GitHub/node_modules/invoice-reminder-service", "Documents/.hidden/invoice-reminder-service",
                     "Documents/a/b/c/d/invoice-reminder-service-deep"] {
            try manager.createDirectory(at: home.appendingPathComponent(path), withIntermediateDirectories: true)
        }
        let found = FolderMatch.walk([home.appendingPathComponent("Documents")], query: "Invoicereminder servise", policy: PathPolicy(home: home))
        #expect(found.map { PathPolicy(home: home).display($0.url) } == ["~/Documents/GitHub/invoice-reminder-service"])
    }

    @Test func aSearchSaysWhatItCouldNotLookInto() throws {
        let home = try temporaryFolder()
        for folder in FolderGrants.guarded {
            try FileManager.default.createDirectory(at: home.appendingPathComponent(folder), withIntermediateDirectories: true)
        }
        let defaults = UserDefaults(suiteName: "ira-tests-\(UUID().uuidString)")!
        let grants = FolderGrants(defaults: defaults, home: home, identity: "build-a")
        #expect(grants.blocked(in: [home]) == ["Documents", "Desktop", "Downloads"])
        grants.record("Documents", .granted)
        grants.record("Desktop", .denied)
        #expect(grants.blocked(in: [home]) == ["Desktop", "Downloads"])
        #expect(grants.blocked(in: [home.appendingPathComponent("Documents/GitHub")]) == [])
        #expect(grants.notSearched(["Desktop", "Downloads"]) == "macOS keeps Ira out of Desktop. Switch on “Desktop Folder” in System Settings → Privacy & Security → Files and Folders → Ira, then ask again. I can't search Downloads yet. Press Allow for it in Ira's checklist (Settings → Permissions) and answer macOS with Allow, then ask again.")
        #expect(Toolbox.findSummary([], policy: PathPolicy(home: home), notSearched: ["Documents"])
            == "Nothing matched where I could look. I can't search Documents yet. Press Allow for it in Ira's checklist (Settings → Permissions) and answer macOS with Allow, then ask again.")
        // Asking on purpose records the answer (a test folder is not guarded, so it is allowed).
        #expect(grants.ask("Downloads") == .granted)
        #expect(grants.access("Downloads") == .granted)
        // A folder this Mac does not have is not a reason to say anything.
        try FileManager.default.removeItem(at: home.appendingPathComponent("Desktop"))
        #expect(grants.blocked(in: [home]) == [])
    }

    @Test func answersGivenToAnotherBuildDoNotCount() throws {
        let home = try temporaryFolder()
        try FileManager.default.createDirectory(at: home.appendingPathComponent("Documents"), withIntermediateDirectories: true)
        let defaults = UserDefaults(suiteName: "ira-tests-\(UUID().uuidString)")!
        FolderGrants(defaults: defaults, home: home, identity: "build-a").record("Documents", .denied)
        let rebuilt = FolderGrants(defaults: defaults, home: home, identity: "build-b")
        #expect(rebuilt.access("Documents") == .notAsked)
        // Before 0.2.2 no build was noted: those answers count as not asked too.
        defaults.set("granted", forKey: "folderAccess.Desktop")
        #expect(rebuilt.access("Desktop") == .notAsked)
        // Looking again turns an old "no" into the answer macOS gives now.
        let same = FolderGrants(defaults: defaults, home: home, identity: "build-a")
        same.recheck("Documents")
        #expect(same.access("Documents") == .granted)
    }

    @Test func screenRecordingKnowsARebuiltIra() {
        let defaults = UserDefaults(suiteName: "ira-tests-\(UUID().uuidString)")!
        let first = ScreenGrant(defaults: defaults, identity: "cdhash H\"aaaa\"")
        #expect(first.state(permitted: false) == .missing)
        #expect(first.requestOnce(permitted: false) == false)
        #expect(first.state(permitted: true) == .granted)
        let rebuilt = ScreenGrant(defaults: defaults, identity: "identifier \"in.ira.mac\" and certificate leaf = H\"bbbb\"")
        #expect(rebuilt.state(permitted: false) == .rebuilt(certain: true))
        #expect(ScreenGrant.advice(.rebuilt(certain: true))?.hasPrefix("Ira was rebuilt: remove the old Ira from Screen Recording and add this one.") == true)
        // macOS is asked once per build, so it lists this one.
        #expect(rebuilt.requestOnce(permitted: false) == true)
        #expect(rebuilt.requestOnce(permitted: false) == false)
        // The same build switched off later is just off.
        #expect(rebuilt.state(permitted: true) == .granted)
        #expect(rebuilt.state(permitted: false) == .missing)
        #expect(ScreenGrant.advice(.missing) == nil)

        // An install from before 0.2.2 noted no build: it may be listed.
        let older = UserDefaults(suiteName: "ira-tests-\(UUID().uuidString)")!
        older.set(true, forKey: "firstRunDone")
        let upgraded = ScreenGrant(defaults: older, identity: "build-c")
        #expect(upgraded.state(permitted: false) == .rebuilt(certain: false))
        #expect(upgraded.requestOnce(permitted: false) == true)
        #expect(ScreenGrant(defaults: older, identity: "build-d").requestOnce(permitted: false) == false)
    }

    @Test func theFolderToolFallsBackToTheWalk() async throws {
        let home = try temporaryFolder()
        try FileManager.default.createDirectory(
            at: home.appendingPathComponent("Documents/GitHub/invoice-reminder-service"), withIntermediateDirectories: true)
        let defaults = UserDefaults(suiteName: "ira-tests-\(UUID().uuidString)")!
        let grants = FolderGrants(defaults: defaults, home: home)
        for folder in FolderGrants.guarded { grants.record(folder, .granted) }
        let toolbox = Toolbox(policy: { PathPolicy(home: home) }, frontApp: { nil }, opener: { _ in true },
                              folderGrants: grants, log: IraLog(directory: nil), record: { _ in })
        let result = try await toolbox.call("files_find", args: ["kind": "folder", "query": "Invoicereminder servise"])
        let first = try #require(result["results"]?.arrayValue?.first)
        #expect(first["name"] == "invoice-reminder-service")
        #expect(first["folder"] == "~/Documents/GitHub")
        #expect(result["notSearched"] == nil)
    }
}
