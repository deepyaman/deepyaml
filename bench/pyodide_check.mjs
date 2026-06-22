// Headless WASM compatibility check: does OmegaConf (and its antlr4 dep) run in Pyodide?
//   node pyodide_check.mjs
import { loadPyodide } from "pyodide";

const CONFIG = `
db:
  host: localhost
  url: \${oc.env:DB_URL,sqlite:///local.db}
  features: [a, b, c]
ref: \${db.host}
`;

const PY = `
import sys, omegaconf, antlr4
from omegaconf import OmegaConf
cfg = OmegaConf.create(CONFIG)
resolved = OmegaConf.to_container(cfg, resolve=True)
import json
print("OMEGACONF_VERSION", omegaconf.__version__)
print("ANTLR4_LOADED", antlr4.__name__)
print("RESOLVED", json.dumps(resolved))
`;

async function main() {
  const t0 = performance.now();
  const pyodide = await loadPyodide();
  await pyodide.loadPackage("micropip");
  const micropip = pyodide.pyimport("micropip");
  try {
    await micropip.install("omegaconf");
  } catch (e) {
    console.log("MICROPIP_INSTALL_FAILED:", String(e).split("\n")[0]);
    process.exit(2);
  }
  pyodide.globals.set("CONFIG", CONFIG);
  try {
    pyodide.runPython(PY);
    console.log(`(pyodide cold boot + install + run: ${((performance.now() - t0) / 1000).toFixed(1)}s)`);
    console.log("RESULT: OmegaConf WORKS in Pyodide/WASM");
  } catch (e) {
    console.log("RUNTIME_FAILED:", String(e).split("\n").slice(0, 6).join("\n"));
    process.exit(3);
  }
}
main();
