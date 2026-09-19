const chromium = require("@sparticuz/chromium");

async function main() {
  chromium.setGraphicsMode = false;
  const executablePath = await chromium.executablePath();
  process.stdout.write(JSON.stringify({ executablePath, args: chromium.args }));
}

main().catch((error) => {
  process.stderr.write(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
