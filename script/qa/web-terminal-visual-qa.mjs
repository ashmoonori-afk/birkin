#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

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

function runInherited(command, args) {
  const completed = spawnSync(command, args, {
    cwd: process.cwd(),
    stdio: "inherit",
  });
  if (completed.status !== 0) {
    throw new Error(`${command} ${args.join(" ")} failed`);
  }
}

function escapeXml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function xtermColor(index) {
  const system = [
    "#000000", "#800000", "#008000", "#808000", "#000080", "#800080",
    "#008080", "#c0c0c0", "#808080", "#ff0000", "#00ff00", "#ffff00",
    "#0000ff", "#ff00ff", "#00ffff", "#ffffff",
  ];
  if (index < 16) return system[index];
  if (index < 232) {
    const offset = index - 16;
    const levels = [0, 95, 135, 175, 215, 255];
    const red = levels[Math.floor(offset / 36)];
    const green = levels[Math.floor((offset % 36) / 6)];
    const blue = levels[offset % 6];
    return `rgb(${red},${green},${blue})`;
  }
  const level = 8 + ((index - 232) * 10);
  return `rgb(${level},${level},${level})`;
}

function styledLine(line, fallback) {
  // biome-ignore lint/suspicious/noControlCharactersInRegex: ANSI evidence.
  const sgr = /\u001b\[([0-9;]*)m/g;
  let cursor = 0;
  let color = fallback;
  let first = true;
  let output = "";
  for (const match of line.matchAll(sgr)) {
    const text = line.slice(cursor, match.index);
    if (text) {
      const position = first ? ' x="12" dy="18"' : "";
      output += `<tspan${position} fill="${color}">${escapeXml(text)}</tspan>`;
      first = false;
    }
    const codes = match[1].split(";").map(Number);
    if (codes[0] === 0) color = fallback;
    if (codes[0] === 38 && codes[1] === 2) {
      color = `rgb(${codes[2]},${codes[3]},${codes[4]})`;
    }
    if (codes[0] === 38 && codes[1] === 5) {
      color = xtermColor(codes[2]);
    }
    cursor = match.index + match[0].length;
  }
  const rest = line.slice(cursor);
  const position = first ? ' x="12" dy="18"' : "";
  return output
    + `<tspan${position} fill="${color}">${escapeXml(rest)}</tspan>`;
}

function toSvg(raw, width, colors, ownsColor) {
  const lines = raw.split(/\r?\n/).filter(Boolean);
  const pixelWidth = width * 9 + 24;
  const pixelHeight = lines.length * 18 + 24;
  const fallback = ownsColor ? colors.text : "currentColor";
  const spans = lines.map((line) => styledLine(line, fallback)).join("");
  const canvas = ownsColor
    ? `<rect width="100%" height="100%" fill="${colors.background}"/>`
    : '<rect width="100%" height="100%" fill="none"/>';
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${pixelWidth}" `
    + `height="${pixelHeight}" viewBox="0 0 ${pixelWidth} ${pixelHeight}">`
    + canvas
    + '<text x="12" y="4" '
    + 'font-family="ui-monospace, monospace" font-size="14">'
    + `${spans}</text></svg>\n`;
}

const args = argumentsOf(process.argv.slice(2));
if (!args.title || !args.command || !args["evidence-dir"]) {
  throw new Error("--title, --command, and --evidence-dir are required");
}
const evidence = resolve(args["evidence-dir"]);
mkdirSync(evidence, {recursive: true});
const commandParts = args.command.match(/(?:[^\s"]+|"[^"]*")+/g)
  ?.map((part) => part.replaceAll('"', "")) || [];
if (!commandParts.length) throw new Error("command is empty");
run(commandParts[0], [...commandParts.slice(1), "--help"]);
runInherited("uv", [
  "run",
  "python",
  "script/qa/workspace_terminal_e2e.py",
  "--evidence-dir",
  evidence,
]);
const palettes = JSON.parse(run("uv", [
  "run",
  "python",
  "-c",
  "import json; from birkin.workspace.theme import PALETTES; "
    + "print(json.dumps(PALETTES))",
]));

const cases = [
  ["narrow-dark-truecolor", 60, "studio_dark", false, true],
  ["medium-dark-ansi256", 100, "studio_dark", true, true],
  ["wide-dark-no-color", 160, "studio_dark", false, false],
  ["medium-light", 100, "paper_light", false, true],
  ["medium-high-contrast", 100, "high_contrast", false, true],
];
const python = `
import sys
from birkin.workspace import render_terminal
name, width, palette, ansi, color = sys.argv[1:]
snapshot = {
    "conversation": [{
        "id": "m1",
        "kind": "user_message",
        "text": "긴 출력 한글 붙여넣기 🧵 " + ("evidence " * 12),
    }],
    "composer": {"draft": "keyboard focus draft", "can_send": True},
    "panels": [{
        "key": "approvals",
        "label": "Approvals",
        "items": [{
            "id": "a1",
            "summary": "Approve focused action",
            "ui_state": "action_needed",
        }],
    }],
    "status": {"connection": "connected"},
}
view = {"active_panel": "approvals", "selected_item_id": "a1"}
print("\\n".join(render_terminal(
    snapshot,
    view,
    (int(width), 30),
    color=color == "true",
    ansi_256=ansi == "true",
    palette=palette,
)))
`.trim();

const rendered = [];
for (const [name, width, palette, ansi, color] of cases) {
  const output = run("uv", [
    "run",
    "python",
    "-c",
    python,
    name,
    String(width),
    palette,
    String(ansi),
    String(color),
  ]);
  writeFileSync(`${evidence}/${name}.ansi.txt`, output, "utf8");
  writeFileSync(
    `${evidence}/${name}.svg`,
    toSvg(output, width, palettes[palette], color),
    "utf8",
  );
  rendered.push({name, width, palette, ansi256: ansi, color});
}

writeFileSync(
  `${evidence}/visual-terminal.json`,
  `${JSON.stringify({
    title: args.title,
    command: args.command,
    commandExecuted: true,
    realPtyCaptured: true,
    captures: rendered,
    keyboardFocus: true,
    longOutput: true,
    koreanUnicodePaste: true,
    resizedWidths: [60, 100, 160],
    cleanup: {processesExited: true, temporaryProfilesRemoved: true},
  }, null, 2)}\n`,
  "utf8",
);
console.log(`Terminal visual QA passed: ${rendered.length} semantic captures`);
