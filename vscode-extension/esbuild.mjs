import { rmSync } from "node:fs";
import * as esbuild from "esbuild";

const watch = process.argv.includes("--watch");
const common = {
  bundle: true,
  external: ["vscode"],
  format: "cjs",
  platform: "node",
  target: "node20",
  sourcemap: true,
  logLevel: "info",
};
const builds = [
  { ...common, entryPoints: ["src/extension.ts"], outfile: "dist/extension.js" },
  { ...common, entryPoints: ["test/suite/index.ts"], outfile: ".test-dist/index.js" },
];

rmSync("dist/test", { recursive: true, force: true });
if (watch) {
  for (const options of builds) {
    const context = await esbuild.context(options);
    await context.watch();
  }
} else {
  await Promise.all(builds.map((options) => esbuild.build(options)));
}
