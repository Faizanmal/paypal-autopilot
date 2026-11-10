import { cpSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { parseArgs } from "node:util";

const webRoot = fileURLToPath(new URL("../", import.meta.url));
const standalone = resolve(webRoot, ".next/standalone");
const server = resolve(standalone, "server.js");
const rootEnv = resolve(webRoot, "../../.env");

if (!existsSync(server) || !existsSync(resolve(webRoot, ".next/BUILD_ID"))) {
  console.error("Production build is missing. Run npm run build first.");
  process.exit(1);
}

if (existsSync(rootEnv)) process.loadEnvFile(rootEnv);

const { values } = parseArgs({
  options: {
    port: { type: "string", short: "p" },
    hostname: { type: "string", short: "H" },
  },
});
const port = values.port ?? process.env.PORT ?? "3000";
if (!/^\d+$/.test(port) || Number(port) < 1 || Number(port) > 65535) {
  console.error("PORT must be an integer between 1 and 65535.");
  process.exit(1);
}
process.env.PORT = port;
process.env.HOSTNAME = values.hostname ?? process.env.HOSTNAME ?? "0.0.0.0";

// Match the Docker runner layout. Copy assets, never the shared .env or credentials.
cpSync(resolve(webRoot, "public"), resolve(standalone, "public"), { recursive: true });
cpSync(resolve(webRoot, ".next/static"), resolve(standalone, ".next/static"), { recursive: true });

await import(pathToFileURL(server).href);
