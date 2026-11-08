// The "dha" theme: the production look for the DHA demo (plan, "DHA theme"). A flat DHA-blue header with a
// text wordmark (logo slot empty until the logo is cleared), the U.S. Government notice up front, plain-language
// key terms, the full terms and the verbatim DoD notice in <details> (no inner scroll box: T-199), one Accept
// button, the emergency line, and footer links to Privacy / Accessibility / Help on our own host.
// The platform contract is unchanged: one top-level #accept-button[data-testid=accept], #ok-title / #err-title,
// the R7 support footer, and the same form/JS hooks as the lab theme (static/js/customer.js).

import { dhaAccessibilityText, dhaHelpText, dhaPrivacyText, dhaTermsText, noticeText } from "./content";
import { escapeHtml as e } from "./security";
import { paragraphs } from "./theme-lab";

export interface DhaBrand {
  organization: string; // "Defense Health Agency"
  facility: string; // fictional MTF line
  network: string; // shown in the header, e.g. "Guest Wi-Fi"
  agreeLabel: string; // "Accept"
  /** The verbatim DoD Notice and Consent banner. Off: a plain-language monitoring notice (ISSM's call). */
  dodNotice: boolean;
  /** /static/dha/... path of an approved logo, or null for the text wordmark. */
  logo: string | null;
  helpText: string;
  supportFooter: boolean;
  host: string;
}

export const DHA_ASSETS = [
  "/static/dha/dha.css",
  "/static/dha/fonts/public-sans-400.woff2",
  "/static/dha/fonts/public-sans-700.woff2",
  "/static/js/customer.js",
];

export type InfoPage = "privacy" | "accessibility" | "help";

const INFO: Record<InfoPage, { title: string; text: string }> = {
  privacy: { title: "Privacy", text: dhaPrivacyText },
  accessibility: { title: "Accessibility", text: dhaAccessibilityText },
  help: { title: "Help", text: dhaHelpText },
};

function blocks(text: string, level: number, dropFirstHeading = false): string {
  const bs = paragraphs(text);
  if (dropFirstHeading && bs[0]?.type === "h") bs.shift();
  return bs
    .map((b) =>
      b.type === "h"
        ? `<h${level}>${e(b.text)}</h${level}>`
        : b.type === "ul"
          ? `<ul>${b.items.map((i) => `<li>${e(i)}</li>`).join("")}</ul>`
          : `<p>${e(b.text)}</p>`,
    )
    .join("");
}

const TERMS_HTML = blocks(dhaTermsText, 3);
const NOTICE_HTML = blocks(noticeText, 3, true);

function utcHhmm(d = new Date()): string {
  return `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")} UTC`;
}

/** The info pages' "back to sign-in" link: the original redirect query on "/", nothing else. */
function backHref(back: string | null | undefined): string | null {
  if (!back) return null;
  const q = back.startsWith("?") ? back.slice(1) : back;
  if (!q || q.length > 2000) return null;
  return `/?${q}`;
}

function infoLinks(back: string | null | undefined): string {
  const r = back && backHref(back) ? `?return=${encodeURIComponent(back.replace(/^\?/, ""))}` : "";
  return `<nav class="links" aria-label="About guest Wi-Fi">
      <a href="/privacy${e(r)}">Privacy</a><a href="/accessibility${e(r)}">Accessibility</a><a href="/help${e(r)}">Help</a>
    </nav>`;
}

function layout(
  b: DhaBrand,
  o: { title: string; head?: string; main: string; ref?: string; back?: string | null; scripts?: string },
): string {
  const mark = b.logo
    ? `<img class="hdr__logo" src="${e(b.logo)}" alt="${e(b.organization)}" width="160" height="48">`
    : `<p class="hdr__org">${e(b.organization)}</p>`;
  const ref = o.ref
    ? b.supportFooter
      ? `<p class="ref">Reference <span>${e(o.ref)}</span> · ${e(b.host)} · ${utcHhmm()}</p>`
      : `<p class="ref">Reference <span>${e(o.ref)}</span></p>`
    : "";
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="referrer" content="no-referrer">
  <meta name="robots" content="noindex, nofollow">
  <meta name="theme-color" content="#1B365D">
  ${o.head ?? ""}
  <title>${e(o.title)} | ${e(b.network)}</title>
  <link rel="preload" href="/static/dha/fonts/public-sans-400.woff2" as="font" type="font/woff2" crossorigin>
  <link rel="stylesheet" href="/static/dha/dha.css">
</head>
<body>
  <a class="skip" href="#main">Skip to main content</a>
  <header class="hdr">
    <div class="hdr__inner">
      ${mark}
      <p class="hdr__network">${e(b.network)}</p>
      <p class="hdr__facility">${e(b.facility)}</p>
    </div>
  </header>
  <main id="main" class="page" tabindex="-1">
    ${o.main}
  </main>
  <footer class="ftr">
    <p>${e(b.helpText)}</p>
    ${infoLinks(o.back)}
    ${ref}
  </footer>
  ${o.scripts ?? ""}
</body>
</html>`;
}

const SCRIPT = `<script src="/static/js/customer.js" defer></script>`;

const EMERGENCY = `<p class="emergency"><strong>Emergency? Call 911 or tell any staff member.</strong>
      In crisis? Call or text 988 (Veterans and service members: press 1).</p>`;

function notice(b: DhaBrand): string {
  if (!b.dodNotice) {
    return `<section class="notice" aria-labelledby="notice-title">
      <h2 id="notice-title">This network is monitored</h2>
      <p>Guest Wi-Fi is a U.S. Government system. Use is monitored and recorded, and you have no expectation of privacy on it.</p>
    </section>`;
  }
  return `<section class="notice" aria-labelledby="notice-title">
      <h2 id="notice-title">U.S. Government information system</h2>
      <p>This system is for authorized use only. Use is monitored and recorded, and you have no expectation of
        privacy on it. By selecting ${e(b.agreeLabel)}, you consent to these conditions.</p>
      <details class="more more--notice">
        <summary>Read the full notice and consent</summary>
        <div class="more__body">${NOTICE_HTML}</div>
      </details>
    </section>`;
}

export function termsPage(b: DhaBrand, ref: string, csrf: string, back: string | null): string {
  return layout(b, {
    title: "Connect to guest Wi-Fi",
    ref,
    back,
    main: `<h1 id="welcome-title">Welcome to guest Wi-Fi</h1>
    <p class="lead">Free Wi-Fi for patients, visitors and families. Please review and accept to connect.</p>

    ${notice(b)}

    <section class="terms" aria-labelledby="terms-title">
      <h2 id="terms-title">Before you connect</h2>
      <ul class="keys">
        <li>This is a public network and it is not encrypted end to end. Only send health, password or payment
          information on secure (https) sites.</li>
        <li>Use it lawfully. Content is filtered, and access can be limited or ended at any time.</li>
        <li>Sessions end after 30 minutes without use and after about 8 hours. Then accept again to reconnect.</li>
      </ul>
      <details class="more">
        <summary>Read the full terms of use</summary>
        <div class="more__body">${TERMS_HTML}</div>
      </details>
    </section>

    <form id="accept-form" class="accept" method="post" action="/accept" novalidate>
      <input type="hidden" name="ref" value="${e(ref)}">
      <input type="hidden" name="csrf" value="${e(csrf)}">
      <p class="accept__consent" id="consent-text">By selecting ${e(b.agreeLabel)}, you agree to the terms of use and
        the notice above.</p>
      <button id="accept-button" data-testid="accept" class="button" type="submit" aria-describedby="consent-text">
        <span class="button__label">${e(b.agreeLabel)}</span>
        <span class="button__busy" aria-hidden="true"></span>
      </button>
      <p id="status" class="status" role="status" aria-live="polite"></p>
    </form>

    ${EMERGENCY}`,
    scripts: SCRIPT,
  });
}

const OK_ICON = `<svg class="icon" viewBox="0 0 48 48" width="56" height="56" aria-hidden="true" focusable="false">
      <circle cx="24" cy="24" r="22" fill="#E7F2EA" stroke="#1E6B34" stroke-width="2"/>
      <path d="M14 24.5l7 7 13-14" fill="none" stroke="#1E6B34" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>`;

const ERR_ICON = `<svg class="icon" viewBox="0 0 48 48" width="56" height="56" aria-hidden="true" focusable="false">
      <circle cx="24" cy="24" r="22" fill="#FBEAEC" stroke="#A3172B" stroke-width="2"/>
      <path d="M24 13v14" fill="none" stroke="#A3172B" stroke-width="4" stroke-linecap="round"/>
      <circle cx="24" cy="34" r="2.6" fill="#A3172B"/>
    </svg>`;

export function successPage(b: DhaBrand, ref: string, target: string | null, delay: number): string {
  const t = target ? e(target) : "";
  return layout(b, {
    title: "You are connected",
    head: target ? `<meta http-equiv="refresh" content="${delay};url=${t}">` : "",
    ref,
    main: `<section class="result result--ok" aria-labelledby="ok-title">
    ${OK_ICON}
    <h1 id="ok-title" tabindex="-1">You are connected</h1>
    <p class="lead">Your device is online. Thank you for using guest Wi-Fi at ${e(b.facility)}.</p>
    <p class="hint">Your session ends after 30 minutes without use and after about 8 hours. Then open any web page
      to accept again.</p>
    ${
      target
        ? `<p>We will take you to your page in <span id="countdown" data-seconds="${delay}">${delay} second${delay === 1 ? "" : "s"}</span>.</p>
    <p><a class="button button--link" href="${t}">Continue</a></p>`
        : `<p>You can close this window and start browsing.</p>`
    }
  </section>
  ${EMERGENCY}`,
    scripts: target ? SCRIPT : "",
  });
}

export function errorPage(b: DhaBrand, ref: string, title: string, body: string, retryUrl: string | null): string {
  return layout(b, {
    title,
    back: retryUrl && retryUrl.startsWith("/?") ? retryUrl.slice(2) : null,
    main: `<section class="result result--err" aria-labelledby="err-title">
    ${ERR_ICON}
    <h1 id="err-title" tabindex="-1">${e(title)}</h1>
    <p class="lead">${e(body)}</p>
    ${retryUrl ? `<p><a class="button button--link" href="${e(retryUrl)}">Try again</a></p>` : ""}
    <p class="refbox">If you ask for help, please give this reference: <strong>${e(ref)}</strong></p>
  </section>
  ${EMERGENCY}`,
  });
}

/** Privacy, Accessibility, Help. `back` is the original redirect query (from ?return=), if any. */
export function infoPage(b: DhaBrand, page: InfoPage, back: string | null): string {
  const p = INFO[page];
  const href = backHref(back);
  return layout(b, {
    title: p.title,
    back,
    main: `<p class="crumb">${
      href ? `<a href="${e(href)}">Back to sign-in</a>` : "To sign in, open any web page."
    }</p>
    <h1 id="info-title">${e(p.title)}</h1>
    <div class="info">${blocks(p.text, 2)}</div>`,
  });
}
