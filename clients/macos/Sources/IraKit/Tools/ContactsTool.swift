import Contacts
import Foundation

/// `contacts_lookup`: people in the Mac's Contacts (iCloud, Google, Exchange: all
/// the accounts added to it), by name, number or email.
public enum ContactsTool {
    static let maxResults = 10

    public static let denied =
        "Contacts is off for Ira. Allow Ira in System Settings → Privacy & Security → Contacts, then ask again"

    static func ensureAccess(_ store: CNContactStore) async throws {
        switch CNContactStore.authorizationStatus(for: .contacts) {
        case .authorized: return
        case .notDetermined:
            let granted = (try? await store.requestAccess(for: .contacts)) ?? false
            if !granted { throw ToolFailure(denied) }
        default:
            throw ToolFailure(denied)
        }
    }

    /// What kind of search a query is: a number, an email, or a name.
    public enum Kind: Equatable { case number(String), email(String), name(String) }

    public static func kind(of query: String) -> Kind {
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.contains("@") { return .email(trimmed.lowercased()) }
        let digits = trimmed.filter(\.isNumber)
        let letters = trimmed.filter(\.isLetter)
        if digits.count >= 4 && letters.isEmpty { return .number(digits) }
        return .name(trimmed)
    }

    /// Whether a stored number is the one asked about: the same last digits, so
    /// "+91 98765 43210", "098765 43210" and "9876543210" all match.
    public static func sameNumber(_ query: String, _ stored: String) -> Bool {
        let a = query.filter(\.isNumber)
        let b = stored.filter(\.isNumber)
        guard a.count >= 4, b.count >= 4 else { return false }
        let tail = min(10, a.count, b.count)
        if a.count >= 7 && b.count >= 7 {
            return a.suffix(tail) == b.suffix(tail)
        }
        // A short query ("43210") matches the end of a number.
        return b.hasSuffix(a)
    }

    public static func lookup(_ query: String) async throws -> JSONValue {
        let store = CNContactStore()
        try await ensureAccess(store)
        let keys: [CNKeyDescriptor] = [
            CNContactGivenNameKey, CNContactFamilyNameKey, CNContactMiddleNameKey, CNContactNicknameKey,
            CNContactOrganizationNameKey, CNContactJobTitleKey, CNContactPhoneNumbersKey,
            CNContactEmailAddressesKey, CNContactIdentifierKey,
        ].map { $0 as CNKeyDescriptor } + [CNContactFormatter.descriptorForRequiredKeys(for: .fullName)]

        let found: [CNContact] = try await Task.detached(priority: .userInitiated) {
            switch kind(of: query) {
            case .email(let email):
                return try store.unifiedContacts(matching: CNContact.predicateForContacts(matchingEmailAddress: email), keysToFetch: keys)
            case .name(let name):
                return try store.unifiedContacts(matching: CNContact.predicateForContacts(matchingName: name), keysToFetch: keys)
            case .number(let digits):
                var matches: [CNContact] = []
                let request = CNContactFetchRequest(keysToFetch: keys)
                try store.enumerateContacts(with: request) { contact, stop in
                    if contact.phoneNumbers.contains(where: { sameNumber(digits, $0.value.stringValue) }) {
                        matches.append(contact)
                        if matches.count >= maxResults { stop.pointee = true }
                    }
                }
                return matches
            }
        }.value

        let people: [JSONValue] = found.prefix(maxResults).map { contact in
            let name = CNContactFormatter.string(from: contact, style: .fullName) ?? contact.organizationName
            var entry: [String: JSONValue] = [
                "name": .string(name.isEmpty ? "No name" : name),
                "phones": .array(contact.phoneNumbers.map {
                    ["label": .string(label($0.label)), "number": .string($0.value.stringValue)]
                }),
                "emails": .array(contact.emailAddresses.map {
                    ["label": .string(label($0.label)), "email": .string($0.value as String)]
                }),
            ]
            if !contact.organizationName.isEmpty { entry["organization"] = .string(contact.organizationName) }
            if !contact.jobTitle.isEmpty { entry["jobTitle"] = .string(contact.jobTitle) }
            if !contact.nickname.isEmpty { entry["nickname"] = .string(contact.nickname) }
            return .object(entry)
        }
        let summary: String
        switch people.count {
        case 0: summary = "No contact matches \(query)."
        case 1:
            let first = people[0]
            let number = first["phones"]?.arrayValue?.first?["number"]?.stringValue
            summary = "\(first["name"]?.stringValue ?? "One contact")" + (number.map { ", \($0)" } ?? "") + "."
        default:
            summary = "\(people.count) contacts match: "
                + people.prefix(5).compactMap { $0["name"]?.stringValue }.joined(separator: "; ") + "."
        }
        return ["contacts": .array(people), "count": .number(Double(people.count)), "summary": .string(summary)]
    }

    static func label(_ raw: String?) -> String {
        guard let raw else { return "" }
        return CNLabeledValue<NSString>.localizedString(forLabel: raw)
    }
}
