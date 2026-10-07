/** 128 random bits as hex. crypto.randomUUID exists only in a secure context, which a plain
 * HTTP host other than localhost is not. */
export function randomKey(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}
