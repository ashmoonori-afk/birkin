const path = require("node:path");
const { runTests } = require("@vscode/test-electron");

async function main() {
  const extensionDevelopmentPath = path.resolve(__dirname, "..");
  const extensionTestsPath = path.resolve(extensionDevelopmentPath, ".test-dist", "index.js");
  await runTests({
    extensionDevelopmentPath,
    extensionTestsPath,
    launchArgs: [extensionDevelopmentPath, "--disable-workspace-trust", "--skip-welcome"],
  });
}

main().catch((error) => {
  console.error("VS Code integration QA failed", error);
  process.exitCode = 1;
});
