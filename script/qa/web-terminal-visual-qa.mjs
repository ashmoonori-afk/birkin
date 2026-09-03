#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

function argumentsOf(argv) {
  const result = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key?.startsWith("--") || value === undefined) {
      throw new Error(`invalid argument near ${key || "<end>"}`);
    }
    result[key.slice(2)] = value;
  }
  return result;
}

function commandParts(command) {
  return command.match(/(?:[^\s"]+|"[^"]*")+/g)
    ?.map((part) => part.replaceAll('"', "")) || [];
}

function run(command, args, options = {}) {
  const completed = spawnSync(command, args, {
    cwd: process.cwd(),
    encoding: "utf8",
    ...options,
  });
  if (completed.status !== 0) {
    throw new Error(
      `${command} ${args.join(" ")} failed\n`
      + `${completed.stdout || ""}${completed.stderr || ""}`,
    );
  }
  return completed.stdout;
}

const args = argumentsOf(process.argv.slice(2));
if (!args.title || !args.command || !args["evidence-dir"]) {
  throw new Error("--title, --command, and --evidence-dir are required");
}
const parts = commandParts(args.command);
if (!parts.length) throw new Error("command is empty");
const evidence = resolve(args["evidence-dir"]);
const executable = resolve(parts[0]);
const python = process.platform === "win32"
  ? resolve(dirname(executable), "python.exe")
  : "python";

run(executable, [...parts.slice(1), "--help"]);
run(python, [
  "-m",
  "script.qa.workspace_terminal_e2e",
  "--evidence-dir",
  evidence,
]);

const transcript = readFileSync(
  resolve(evidence, "terminal-pty.raw.txt"),
  "utf8",
);
const xtermScript = fileURLToPath(import.meta.resolve("@xterm/xterm"));
const xtermCss = resolve(dirname(xtermScript), "..", "css", "xterm.css");
const screenshot = resolve(evidence, "terminal.png");
const browser = await chromium.launch({headless: true});
try {
  const page = await browser.newPage({viewport: {width: 1200, height: 720}});
  await page.setContent(`
    <!doctype html>
    <html lang="ko"><head><meta charset="utf-8"><title>${args.title}</title></head>
    <body style="margin:0;padding:24px;background:#11100f">
      <main id="terminal" aria-label="Birkin terminal"></main>
    </body></html>
  `);
  await page.addStyleTag({path: xtermCss});
  await page.addScriptTag({path: xtermScript});
  await page.evaluate((raw) => new Promise((resolveWrite) => {
    const terminal = new globalThis.Terminal({
      cols: 120,
      rows: 36,
      convertEol: false,
      fontFamily: "Cascadia Mono, Consolas, monospace",
      fontSize: 15,
      theme: {background: "#11100f", foreground: "#f4eadf"},
    });
    terminal.open(document.querySelector("#terminal"));
    terminal.write(raw, resolveWrite);
  }), transcript);
  await page.locator("#terminal .xterm-screen").screenshot({path: screenshot});
} finally {
  await browser.close();
}

run(python, [
  "-c",
  "from pathlib import Path; "
    + "from script.qa.workspace_terminal_evidence import "
    + "register_browser_screenshot, verify_evidence; "
    + "e=Path(__import__('sys').argv[1]); p=Path(__import__('sys').argv[2]); "
    + "register_browser_screenshot(e, p); verify_evidence(e, require_browser=True)",
  evidence,
  screenshot,
]);
console.log("Terminal visual QA passed: real ConPTY transcript rendered by xterm.js");
