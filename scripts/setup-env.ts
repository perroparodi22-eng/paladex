/**
 * Creates .env.local for local development if it does not exist yet:
 * copies .env.example and fills in a random admin password (hashed) and a
 * session secret. The plain password is written as a comment in .env.local
 * (git-ignored) so you can sign in to /admin. Change it before deploying.
 */
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { randomBytes } from "node:crypto";
import { hashPassword } from "../src/server/auth/password";

async function main() {
  if (existsSync(".env.local")) {
    console.log(".env.local already exists, leaving it untouched");
    return;
  }
  const password = randomBytes(15).toString("base64url");
  const secret = randomBytes(32).toString("base64url");
  const hash = await hashPassword(password);
  let env = readFileSync(".env.example", "utf8");
  env = env.replace(/^ADMIN_PASSWORD_HASH=.*$/m, `ADMIN_PASSWORD_HASH=${hash}`);
  env = env.replace(/^ADMIN_SESSION_SECRET=.*$/m, `ADMIN_SESSION_SECRET=${secret}`);
  env = `# Local development environment, created by \`npm run setup\`.\n# Local admin password (development only, change before deploying): ${password}\n\n${env}`;
  writeFileSync(".env.local", env);
  console.log("created .env.local with a local admin password (see the comment at the top of the file)");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
