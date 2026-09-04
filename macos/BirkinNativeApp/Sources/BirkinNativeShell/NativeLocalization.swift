import Foundation

public enum NativeLocalization {
    public static var currentLocale: Locale {
        Locale(identifier: Bundle.main.preferredLocalizations.first ?? "en")
    }

    public static func language(for locale: Locale) -> String {
        let language = locale.identifier
            .split(whereSeparator: { $0 == "-" || $0 == "_" })
            .first?
            .lowercased()
        return language == "ko" ? "ko" : "en"
    }

    public static func string(
        _ key: String,
        locale: Locale = currentLocale,
        _ arguments: CVarArg...
    ) -> String {
        let language = language(for: locale)
        let bundle = localizedBundle(language: language)
        let template = bundle.localizedString(
            forKey: key,
            value: nil,
            table: nil
        )
        guard !arguments.isEmpty else { return template }
        return String(
            format: template,
            locale: locale,
            arguments: arguments
        )
    }

    public static func resourceURL(language: String) -> URL? {
        let supported = language == "ko" ? "ko" : "en"
        return resourceBundle.path(
            forResource: "Localizable",
            ofType: "strings",
            inDirectory: nil,
            forLocalization: supported
        ).map(URL.init(fileURLWithPath:))
    }

    private static func localizedBundle(language: String) -> Bundle {
        for candidate in [Bundle.main, resourceBundle] {
            if let path = candidate.path(
                forResource: language,
                ofType: "lproj"
            ),
               let bundle = Bundle(path: path) {
                return bundle
            }
        }
        return resourceBundle
    }

    private static var resourceBundle: Bundle { Bundle.module }
}
