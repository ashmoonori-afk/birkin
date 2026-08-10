const { chromium } = require("playwright");
const { pathToFileURL } = require("node:url");
const path = require("node:path");

async function main() {
  const root = path.resolve(__dirname, "../..");
  const url = pathToFileURL(
    path.join(root, "docs/ironman-voice-agent-workflow-design.html"),
  ).href;
  const evidence = path.join(
    root,
    ".omo/evidence/active-voice-control",
  );
  const browser = await chromium.launch({ headless: true });
  const errors = [];

  try {
    for (const scenario of [
      { name: "desktop", width: 1440, height: 1000 },
      { name: "mobile", width: 390, height: 844 },
    ]) {
      const page = await browser.newPage({
        viewport: { width: scenario.width, height: scenario.height },
      });
      page.on("console", (message) => {
        if (message.type() === "error") {
          errors.push(`${scenario.name}:console:${message.text()}`);
        }
      });
      page.on("pageerror", (error) => {
        errors.push(`${scenario.name}:page:${error.message}`);
      });
      await page.goto(url, { waitUntil: "load" });
      const facts = await page.evaluate(() => ({
        title: document.title,
        h1: document.querySelector("h1")?.textContent?.trim() || "",
        text: document.body.innerText,
        overflow:
          document.documentElement.scrollWidth >
          document.documentElement.clientWidth + 1,
        offenders: [...document.querySelectorAll("*")]
          .filter((element) => {
            const scroller = element.closest(".table-wrap, .flow, pre");
            return !scroller || scroller === element;
          })
          .map((element) => {
            const rect = element.getBoundingClientRect();
            return {
              tag: element.tagName.toLowerCase(),
              className: element.className || "",
              right: Math.round(rect.right),
              width: Math.round(rect.width),
              scrollWidth: element.scrollWidth,
              clientWidth: element.clientWidth,
            };
          })
          .filter(
            (item) =>
              item.right > document.documentElement.clientWidth + 1,
          )
          .slice(0, 12),
        sections: document.querySelectorAll("main section").length,
      }));
      const required = [
        "openai-python",
        "Gateway.handle",
        "gpt-transcribe",
        "gpt-4o-mini-tts",
        "implementation ledger",
      ];
      const missing = required.filter(
        (value) =>
          !facts.text.toLowerCase().includes(value.toLowerCase()),
      );
      const contentPass = missing.length === 0;
      const pass =
        facts.title.includes("Active Voice Control") &&
        facts.h1.includes("Daddy is home") &&
        facts.sections >= 8 &&
        contentPass &&
        !facts.overflow;
      console.log(
        `VIEWPORT=${scenario.name} ${scenario.width}x${scenario.height}`,
      );
      console.log(`TITLE=${facts.title}`);
      console.log(`SECTIONS=${facts.sections}`);
      console.log(`CONTENT=${contentPass ? "PASS" : "FAIL"}`);
      if (missing.length) {
        console.log(`MISSING_CONTENT=${JSON.stringify(missing)}`);
      }
      console.log(`HORIZONTAL_OVERFLOW=${facts.overflow ? "FAIL" : "PASS"}`);
      if (facts.overflow) {
        console.log(`OVERFLOW_OFFENDERS=${JSON.stringify(facts.offenders)}`);
      }
      console.log(`LAYOUT=${pass ? "PASS" : "FAIL"}`);
      if (!pass) process.exitCode = 1;
      await page.screenshot({
        path: path.join(evidence, `design-${scenario.name}.png`),
        fullPage: true,
      });
      await page.close();
    }
    console.log(`CONSOLE_PAGE_ERRORS=${errors.length}`);
    if (errors.length) {
      for (const error of errors) console.error(error);
      process.exitCode = 1;
    }
  } finally {
    await browser.close();
    console.log("CLEANUP=PASS");
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
