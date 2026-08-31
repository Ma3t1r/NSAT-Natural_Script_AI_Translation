// 用 esbuild 把 CodeMirror 打包成浏览器可直接加载的 app.js
import * as esbuild from "esbuild";
import { copyFileSync, mkdirSync } from "node:fs";

const watch = process.argv.includes("--watch");

mkdirSync("../static/vendor", { recursive: true });

const options = {
  entryPoints: ["src/editor.js"],
  outfile: "../static/vendor/editor.js",
  bundle: true,
  format: "iife",
  sourcemap: true,
  target: ["es2020"],
  logLevel: "info",
};

if (watch) {
  const ctx = await esbuild.context(options);
  await ctx.watch();
  console.log("watching...");
} else {
  await esbuild.build(options);
  copyFileSync("src/editor.js", "../static/vendor/editor.src.js");
  console.log("build done");
}
