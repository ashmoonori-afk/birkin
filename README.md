# Birkin

![Birkin — a folded-paper workspace for careful knowledge work](./docs/assets/birkin-readme-hero.png)

<p align="center"><strong>A local workspace for research, Office documents, and approval-controlled work.</strong></p>

<p align="center">
  <a href="./README.ko.md">한국어</a> ·
  <a href="./docs/office-support.md">Office support</a> ·
  <a href="./docs/DESIGN.md">Architecture</a> ·
  <a href="./docs/config-reference.md">Configuration</a>
</p>

Birkin brings conversation, source-backed research, document work, and approvals into one local workspace. Python owns execution and policy; the Windows, macOS, terminal, and Web surfaces show the same work without becoming separate authorities.

It is built for work where the difference between “prepared” and “executed” matters. A document change can be inspected before it is written. A consequential action waits for approval. A completed action returns an artifact and receipt instead of a vague success message.

![Birkin workspace showing research, document review, and an approval request](./docs/assets/birkin-workspace-windows.png)

> The hero is a generated brand illustration. The workspace image is a generated product-direction render with representative data. Neither is a live Microsoft 365 session or packaged-release acceptance result.

## What you can do

- **Research with an audit trail.** Collect public sources, separate source-backed claims from inference and unresolved questions, and keep citations attached to the result.
- **Inspect and prepare Office work.** Read, extract, compare, validate, create, or make bounded copy-on-write changes to DOCX, XLSX, PPTX, PDF, and HWPX files.
- **Review before execution.** See the source, destination, exact change, overwrite decision, risk, and approval state before a consequential action runs.
- **Recover without guessing.** Durable jobs and receipts distinguish completed, partial, failed, and outcome-unknown states. Uncertain mail delivery is checked before any retry.
- **Keep internal state local by default.** Sessions, memory, approvals, and audit state stay under `BIRKIN_HOME`. A configured model provider may receive request content, and Microsoft 365 is contacted only when connected.
- **Choose your surface.** Start in the terminal or local Web workspace. Native Windows and macOS clients use the same Python authority.

## The primary journey

1. Ask Birkin to research a question or inspect a file.
2. Review the result, its sources, and unresolved claims.
3. Request a document change or external action.
4. Inspect the proposed change and approve or reject it.
5. Open the resulting artifact and verification receipt.

Before changing an existing Office file, import it into the dedicated `BIRKIN_HOME/office` jail. Writes are copy-on-write, destinations are bounded, and an approval request does not change the source or destination. Rollback is a separate approved action.

```text
Research or file import → result + evidence → proposed change
        → human approval → execution + artifact + receipt
```

## Quick start

Birkin requires Python 3.10 or newer. The repository currently identifies as Birkin `0.4.417`. This is the source version, not a claim that the same version is installed on your machine or available as a signed public app.

### Windows

From a source checkout:

```powershell
py -3 -m pip install .
birkin setup
birkin chat
```

Or install the current `main` branch, then verify what was installed:

```powershell
irm https://raw.githubusercontent.com/ashmoonori-afk/birkin/main/scripts/install.ps1 | iex
birkin --version
birkin setup
birkin chat
```

The WPF client is a development surface and requires .NET 8 plus a locally installed Birkin CLI:

```powershell
dotnet run --project .\windows\BirkinNativeApp\src\Birkin.Native.App\Birkin.Native.App.csproj -c Release
```

There is no confirmed signed Windows customer package in this checkout. See [Birkin for Windows](./windows/BirkinNativeApp/README.md) for build, connection, and package-verification details.

### macOS and Linux

```bash
python3 -m pip install .
birkin setup
birkin chat
```

The repository also provides an installer for the current `main` branch:

```bash
curl -fsSL https://raw.githubusercontent.com/ashmoonori-afk/birkin/main/scripts/install.sh | bash
birkin --version
```

The SwiftUI macOS app is built from source. Builds without release credentials are development artifacts; notarization, stapling, Gatekeeper assessment, and public distribution remain separate gates. See the [native app guide](./docs/native-app/README.md).

### Web workspace

The authenticated Web workspace is served locally by the same Python runtime:

```bash
birkin web
```

Use `birkin web --no-browser` when another client will open the private bootstrap URL. It listens on loopback by default and exchanges the one-time bootstrap capability for an `HttpOnly`, `SameSite=Strict` cookie.

## Add Office and research support

Install only the tier you need from the source checkout:

```bash
python -m pip install ".[office]"          # DOCX, XLSX, PPTX, HWPX
python -m pip install ".[office-advanced]" # PDF extraction and bounded page rendering
python -m pip install ".[research]"        # research schemas and canonical records
```

Office support is bounded document work, not arbitrary desktop-suite automation.

| Format | Current public path | Boundary |
| --- | --- | --- |
| DOCX | inspect, extract, create, bounded edits, structured preview | no layout or tracked-change proof |
| XLSX | inspect, extract, create, numeric edits, structured preview | formulas are preserved, not recalculated |
| PPTX | inspect, extract, create, placeholder edits, structured preview | no master, animation, overflow, or layout proof |
| PDF | inspect/create; optional extraction and one-page image | existing PDFs are read-only; no forms, signing, OCR, or redaction |
| HWPX | inspect, extract, create, template fields, one bounded field edit | no legacy HWP or Hancom automation |

Read the [versioned Office support contract](./docs/office-support.md) for the exact tool inventory, package provenance, limits, and refusal behavior.

## Providers and useful commands

`birkin setup` configures the provider and model. The default configuration uses the local `codex-cli` provider; API-backed and compatible endpoints require their own credentials.

```bash
birkin --version
birkin --help
birkin chat --dry-run "Summarize this request" # builds the prompt packet; sends nothing
birkin review                                  # inspect pending approvals
```

The generated tables live in [Configuration reference](./docs/config-reference.md). User-facing Korean and stable protocol/diagnostic English follow the [language policy](./docs/language-policy.md).

## Trust boundaries

- Document prose, URLs, formulas, macros, metadata, and embedded objects are untrusted input.
- Read-only inspection does not grant write authority. Office mutation enters through `office_job_request`; rollback enters through `office_rollback_request`.
- Approval binds the source hash, operation, destination, overwrite choice, and proposer. Changed inputs fail closed.
- Browser and Computer Use are optional and disabled until configured. They remain constrained by allowlists, action budgets, and approval policy.
- Provider completion, HTTP acceptance, a local receipt, and confirmed remote state are different evidence. Birkin preserves `unknown` or `needs_review` when it cannot observe the external outcome.

## Verification and current limits

Repository tests and focused local runs cover the Python authority, approval/recovery contracts, Web behavior, and native protocol projections. A representative DOCX flow completed from natural-language inspection through Native approval, saved output, and receipt, with no output before approval.

This does not establish a fully accepted public release:

- the source version does not establish which version is installed or publicly released;
- the newest research run left unresolved claims and did not pass whole-answer acceptance;
- rendered mock/offline and keyboard checks have passed, while live installed journeys, macOS CI follow-up, and human screen-reader acceptance remain open;
- Microsoft 365 live-account verification is intentionally last and remains incomplete;
- signed Windows packaging and notarized macOS public distribution are not established here.

Evidence and remaining gates are tracked in the [Office agent review](./docs/office-agent-review.md), [UI redesign specification](./docs/ui-redesign-spec.md), and [Windows first-report journey](./docs/windows-first-report-journey.md).

## Reference

| Need | Document |
| --- | --- |
| Exact Office capabilities | [Office Work OS v2](./docs/office-support.md) |
| UI and accessibility criteria | [UI redesign specification](./docs/ui-redesign-spec.md) |
| Current implementation and open gates | [Office agent review](./docs/office-agent-review.md) |
| Full configuration schema | [Configuration reference](./docs/config-reference.md) |
| Runtime architecture | [Design](./docs/DESIGN.md) |
| Memory system | [Mnemosyne design](./docs/mnemosyne-design.md) |
| Multi-agent workflows | [Moirai design](./docs/moirai-design.md) |
| Native protocol and security | [Native app documentation](./docs/native-app/README.md) |
| Engineering status | [Status](./docs/STATUS.md) |
| VS Code client | [Extension](./vscode-extension) |

## Development

```bash
python -m pip install -e ".[dev]"
pytest
```

Native and browser suites have additional platform requirements; use their linked guides rather than treating a focused local pass as cross-platform acceptance.

Birkin is released under the [MIT License](./LICENSE). Third-party attribution and terms are recorded in [NOTICE](./NOTICE), `LICENSES/`, and the Office [third-party notices](./birkin/office/adapters/THIRD_PARTY_NOTICES.md).
