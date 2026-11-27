// Catches common email typos ("gmial.com", "yaho.com", "hotmail.con") so the confirmation code
// doesn't go to an address that doesn't exist. Only suggests; the person decides.
const DOMAINS = [
  "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com", "aol.com", "live.com",
  "msn.com", "me.com", "comcast.net", "verizon.net", "att.net", "sbcglobal.net", "protonmail.com",
  "yahoo.co.uk", "hotmail.co.uk", "btinternet.com", "gmx.com", "gmx.de", "web.de", "orange.fr",
  // Real providers that look close to the ones above — listed so they're never "corrected".
  "mail.com", "ymail.com", "email.com", "live.co.uk", "aim.com", "mac.com", "gmx.net", "yahoo.ca",
];

function distance(a: string, b: string): number {
  const dp = Array.from({ length: a.length + 1 }, (_, i) => [i, ...Array(b.length).fill(0)]);
  for (let j = 1; j <= b.length; j++) dp[0][j] = j;
  for (let i = 1; i <= a.length; i++) {
    for (let j = 1; j <= b.length; j++) {
      dp[i][j] = Math.min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) dp[i][j] = Math.min(dp[i][j], dp[i - 2][j - 2] + 1);
    }
  }
  return dp[a.length][b.length];
}

/** A corrected address when the domain looks like a typo of a common one, else null. */
export function suggestEmail(email: string): string | null {
  const at = email.trim().lastIndexOf("@");
  if (at < 1) return null;
  const local = email.trim().slice(0, at);
  const domain = email.trim().slice(at + 1).toLowerCase();
  if (domain.length < 4 || DOMAINS.includes(domain)) return null;
  // Only domains that look like a typo of a big provider: "babybabel.com" isn't "hotmail.com".
  let best: string | null = null;
  let bestD = 3;
  for (const d of DOMAINS) {
    const dist = distance(domain, d);
    if (dist < bestD) { best = d; bestD = dist; }
  }
  // A missing ".com" ("gmail") counts too.
  if (!best && !domain.includes(".")) best = DOMAINS.find((d) => d.split(".")[0] === domain) || null;
  return best ? `${local}@${best}` : null;
}
