/**
 * Prints an ADMIN_PASSWORD_HASH line for your environment.
 *   npm run admin:hash -- "a-long-unique-password"
 */
import { hashPassword } from "../src/server/auth/password";

async function main() {
  const password = process.argv[2];
  if (!password) {
    console.error('usage: npm run admin:hash -- "a-long-unique-password"');
    process.exit(1);
  }
  console.log(`ADMIN_PASSWORD_HASH=${await hashPassword(password)}`);
}

main().catch((e) => {
  console.error(e.message ?? e);
  process.exit(1);
});
