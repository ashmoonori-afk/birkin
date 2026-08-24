import Testing
@testable import BirkinNativeShell

@Suite("Advertised command palette")
struct CommandPaletteTests {
    @Test("every and only advertised command becomes a palette row")
    func derivesRowsFromAdvertisement() {
        // Given: commands from one authenticated ready frame.
        let advertised: Set<String> = [
            "browser.start", "chat.send", "file.import", "session.create",
        ]

        // When: the native palette derives its rows.
        let model = CommandPaletteModel(advertisedCommands: advertised)

        // Then: no absent handler is invented or advertised handler omitted.
        #expect(Set(model.items.map(\.commandType)) == advertised)
        #expect(model.items.map(\.commandType) == advertised.sorted())
    }

    @Test("fuzzy filtering retains the machine command identity")
    func fuzzyFiltersCommandIdentity() {
        // Given: multiple advertised command families.
        let model = CommandPaletteModel(advertisedCommands: [
            "browser.navigate", "browser.start", "session.create",
        ])

        // When: a keyboard operator enters a subsequence query.
        let matches = model.filtered(by: "brsta")

        // Then: the matching advertised command remains the selected identity.
        #expect(matches.map(\.commandType) == ["browser.start"])
    }

    @Test("no advertisement produces an empty palette")
    func staysEmptyWithoutAdvertisement() {
        // Given: a connection with no command handlers.
        let model = CommandPaletteModel(advertisedCommands: [])

        // When / Then: the palette contains no speculative actions.
        #expect(model.filtered(by: "") == [])
    }
}
