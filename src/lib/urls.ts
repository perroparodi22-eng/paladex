/**
 * URL safety helpers shared by the admin (validation) and the affiliate
 * redirect. Only https (or same-origin relative paths for assets) are allowed;
 * javascript:, data:, file: and protocol-relative URLs are rejected.
 */
export const AFFILIATE_PLACEHOLDER = "AFFILIATE_URL_HERE";

export function isPlaceholderLink(url: string | null | undefined): boolean {
  return !url || url.trim() === "" || url.trim() === AFFILIATE_PLACEHOLDER;
}

/** Absolute https URL with a real hostname. */
export function isSafeHttpsUrl(value: string | null | undefined): boolean {
  if (!value) return false;
  try {
    const u = new URL(value);
    return u.protocol === "https:" && !!u.hostname && !u.username && !u.password;
  } catch {
    return false;
  }
}

/** Same-origin asset path like /models/x.glb (no traversal, no protocol-relative). */
export function isSafeLocalPath(value: string | null | undefined): boolean {
  if (!value) return false;
  return value.startsWith("/") && !value.startsWith("//") && !value.includes("..") && !value.includes("\\");
}

/** Asset URL (model, image, poster): local path or https on an allowed host. */
export function isSafeAssetUrl(value: string | null | undefined, allowedHosts: string[] = []): boolean {
  if (isSafeLocalPath(value)) return true;
  if (!isSafeHttpsUrl(value)) return false;
  if (!allowedHosts.length) return true;
  const host = new URL(value!).hostname;
  return allowedHosts.some((h) => host === h || host.endsWith(`.${h}`));
}

/** Does `url` point to one of the retailer's allowed domains? */
export function hostMatches(url: string, domains: string[]): boolean {
  try {
    const host = new URL(url).hostname.toLowerCase();
    return domains.some((d) => {
      const dd = d.toLowerCase().replace(/^\*\./, "");
      return host === dd || host.endsWith(`.${dd}`);
    });
  } catch {
    return false;
  }
}
