const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");

// Vercel Functions use the Amazon Linux 2023 runtime, but the build container
// does not expose the Lambda marker that @sparticuz/chromium uses to decide
// whether its matching shared libraries must be unpacked.
process.env.AWS_EXECUTION_ENV ||= "AWS_Lambda_nodejs20.x";
const chromium = require("@sparticuz/chromium");

async function copyIfPresent(source, destination) {
  try {
    await fs.cp(source, destination, { recursive: true });
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
}

async function main() {
  chromium.setGraphicsMode = false;
  const executable = await chromium.executablePath();
  const output = path.join(process.cwd(), ".serverless-chromium");
  await fs.rm(output, { recursive: true, force: true });
  await fs.mkdir(output, { recursive: true });
  await fs.copyFile(executable, path.join(output, "chromium"));
  await fs.chmod(path.join(output, "chromium"), 0o755);
  await copyIfPresent(path.join(os.tmpdir(), "al2023"), path.join(output, "al2023"));
  await copyIfPresent(path.join(os.tmpdir(), "fonts"), path.join(output, "fonts"));
  for (const file of ["libEGL.so", "libGLESv2.so", "libvk_swiftshader.so", "vk_swiftshader_icd.json"]) {
    await copyIfPresent(path.join(os.tmpdir(), file), path.join(output, file));
  }
  process.stdout.write(`Prepared serverless Chromium at ${output}\n`);
}

main().catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.stack : String(error)}\n`);
  process.exit(1);
});
