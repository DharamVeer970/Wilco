/** Wilco Logger — replaces all raw console.log/warn/error calls.
 *
 * In production builds this can be swapped for a no-op or sent to an analytics
 * endpoint. For now it mirrors console but with a consistent, grep-able prefix
 * so SonarQube's "Remove print statements from production code" rule can be
 * met by swapping this module out later without touching the call sites.
 */
let _enabled = !import.meta.env?.PROD;

export function setLoggerEnabled(enabled: boolean): void {
  _enabled = enabled;
}

function tag(category: string, message: string): string {
  return `[Wilco:${category}] ${message}`;
}

export function log(...args: unknown[]): void {
  if (_enabled) console.log(tag("LOG", args.map(String).join(" ")));
}

export function warn(...args: unknown[]): void {
  if (_enabled) console.warn(tag("WARN", args.map(String).join(" ")));
}

export function error(...args: unknown[]): void {
  if (_enabled) console.error(tag("ERROR", args.map(String).join(" ")));
}

export function debug(...args: unknown[]): void {
  if (_enabled && import.meta.env?.DEV) console.debug(tag("DEBUG", args.map(String).join(" ")));
}