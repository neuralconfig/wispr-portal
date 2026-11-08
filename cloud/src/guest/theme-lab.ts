// The "lab" theme: templates/customer/*.html from the VM portal, ported 1:1. Same CSS and JS
// (served from ../static via Static Assets), same text and markup, plus the platform contract:
// one top-level #accept-button[data-testid=accept], #ok-title / #err-title, and the R7 support footer.

import { noticeText, termsText } from "./content";
import { escapeHtml as e } from "./security";

export interface Brand {
  facility: string;
  helpText: string;
  welcome: string;
  agreeLabel: string;
  /** R7: "Reference XXXX-XXXX · host · HH:MM UTC" on the terms and success pages. */
  supportFooter: boolean;
  host: string;
}

type Block = { type: "h" | "p"; text: string } | { type: "ul"; items: string[] };

/** wispr's _paragraphs(): '# ' heading, '- ' list item, blank line = new paragraph. */
export function paragraphs(text: string): Block[] {
  const blocks: Block[] = [];
  const para: string[] = [];
  const items: string[] = [];
  const flushPara = () => {
    if (para.length) blocks.push({ type: "p", text: para.splice(0).join(" ") });
  };
  const flush = () => {
    flushPara();
    if (items.length) blocks.push({ type: "ul", items: items.splice(0) });
  };
  for (const line of text.split(/\r?\n/)) {
    const s = line.trim();
    if (!s) flush();
    else if (s.startsWith("# ")) {
      flush();
      blocks.push({ type: "h", text: s.slice(2).trim() });
    } else if (s.startsWith("- ")) {
      flushPara();
      items.push(s.slice(2).trim());
    } else {
      if (items.length) flush();
      para.push(s);
    }
  }
  flush();
  return blocks;
}

const TERMS = paragraphs(termsText);
const NOTICE = paragraphs(noticeText);

function renderBlocks(blocks: Block[], level: number): string {
  return blocks
    .map((b) =>
      b.type === "h"
        ? `<h${level}>${e(b.text)}</h${level}>`
        : b.type === "ul"
          ? `<ul>${b.items.map((i) => `<li>${e(i)}</li>`).join("")}</ul>`
          : `<p>${e(b.text)}</p>`,
    )
    .join("");
}

const MARK = `<svg class="masthead__mark" viewBox="0 0 48 48" width="40" height="40" aria-hidden="true" focusable="false">
          <circle cx="24" cy="24" r="23" fill="#ffffff" fill-opacity="0.12"/>
          <path d="M10 20.5a20 20 0 0 1 28 0" fill="none" stroke="#ffffff" stroke-width="3.2" stroke-linecap="round"/>
          <path d="M15 26a13 13 0 0 1 18 0" fill="none" stroke="#ffffff" stroke-width="3.2" stroke-linecap="round"/>
          <path d="M20 31.4a6 6 0 0 1 8 0" fill="none" stroke="#ffffff" stroke-width="3.2" stroke-linecap="round"/>
          <circle cx="24" cy="36" r="2.6" fill="#ffffff"/>
        </svg>`;

function utcHhmm(d = new Date()): string {
  return `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")} UTC`;
}

function footerRef(b: Brand, ref: string): string {
  if (b.supportFooter) {
    return `<p class="ref">Reference <span>${e(ref)}</span> · ${e(b.host)} · ${utcHhmm()}</p>`;
  }
  return `<p class="ref">Reference: <span>${e(ref)}</span></p>`;
}

function layout(b: Brand, o: { title: string; head?: string; main: string; footerRef?: string; scripts?: string }): string {
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="referrer" content="no-referrer">
  <meta name="robots" content="noindex, nofollow">
  ${o.head ?? ""}
  <title>${e(o.title)} | ${e(b.facility)}</title>
  <link rel="stylesheet" href="/static/css/customer.css">
</head>
<body>
  <a class="skip" href="#main">Skip to main content</a>
  <header class="masthead">
    <div class="masthead__inner">
      ${MARK}
      <div class="masthead__text">
        <p class="masthead__facility">${e(b.facility)}</p>
        <p class="masthead__service">Guest Wi-Fi</p>
      </div>
    </div>
  </header>
  <main id="main" class="page" tabindex="-1">
    ${o.main}
  </main>
  <footer class="footer">
    <p>${e(b.helpText)}</p>
    ${o.footerRef ?? ""}
  </footer>
  ${o.scripts ?? ""}
</body>
</html>`;
}

const SCRIPT = `<script src="/static/js/customer.js" defer></script>`;

export function termsPage(b: Brand, ref: string, csrf: string): string {
  return layout(b, {
    title: "Connect to guest Wi-Fi",
    main: `<section class="card" aria-labelledby="welcome-title">
    <h1 id="welcome-title">Welcome to ${e(b.facility)} guest Wi-Fi</h1>
    <p class="lead">${e(b.welcome)}</p>

    <section class="terms" aria-labelledby="terms-title">
      <h2 id="terms-title" class="visually-hidden">Terms of use and acceptable use policy</h2>
      <div class="scrollbox" tabindex="0" role="region" aria-labelledby="terms-title">
        ${renderBlocks(TERMS, 3)}
      </div>
    </section>

    <section class="notice" aria-labelledby="notice-title">
      <h2 id="notice-title" class="visually-hidden">Notice and consent</h2>
      <div class="scrollbox scrollbox--notice" tabindex="0" role="region" aria-labelledby="notice-title">
        ${renderBlocks(NOTICE, 3)}
      </div>
    </section>

    <form id="accept-form" class="accept" method="post" action="/accept" novalidate>
      <input type="hidden" name="ref" value="${e(ref)}">
      <input type="hidden" name="csrf" value="${e(csrf)}">
      <p class="accept__consent" id="consent-text">
        By selecting <strong>${e(b.agreeLabel)}</strong> you confirm that you have read and accept the
        terms of use, the acceptable use policy and the notice above.
      </p>
      <button id="accept-button" data-testid="accept" class="button" type="submit" aria-describedby="consent-text">
        <span class="button__label">${e(b.agreeLabel)}</span>
        <span class="button__busy" aria-hidden="true"></span>
      </button>
      <p id="status" class="status" role="status" aria-live="polite"></p>
    </form>
  </section>`,
    footerRef: footerRef(b, ref),
    scripts: SCRIPT,
  });
}

export function successPage(b: Brand, ref: string, target: string | null, delay: number): string {
  const t = target ? e(target) : "";
  return layout(b, {
    title: "You are connected",
    head: target ? `<meta http-equiv="refresh" content="${delay};url=${t}">` : "",
    main: `<section class="card card--center" aria-labelledby="ok-title">
    <svg class="result-icon result-icon--ok" viewBox="0 0 48 48" width="64" height="64" aria-hidden="true" focusable="false">
      <circle cx="24" cy="24" r="22" fill="#e6f4ea" stroke="#1e7b34" stroke-width="2"/>
      <path d="M14 24.5l7 7 13-14" fill="none" stroke="#1e7b34" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>
    <h1 id="ok-title" tabindex="-1">You are connected</h1>
    <p class="lead">Your device is now online. Thank you for using ${e(b.facility)} guest Wi-Fi.</p>
    ${
      target
        ? `<p>We will take you to your page in <span id="countdown" data-seconds="${delay}">${delay} second${delay === 1 ? "" : "s"}</span>.</p>
      <p><a class="button button--link" href="${t}">Continue</a></p>`
        : `<p>You can close this window and start browsing.</p>`
    }
  </section>`,
    footerRef: footerRef(b, ref),
    scripts: target ? SCRIPT : "",
  });
}

export function errorPage(b: Brand, ref: string, title: string, body: string, retryUrl: string | null): string {
  return layout(b, {
    title,
    main: `<section class="card card--center" aria-labelledby="err-title">
    <svg class="result-icon" viewBox="0 0 48 48" width="64" height="64" aria-hidden="true" focusable="false">
      <circle cx="24" cy="24" r="22" fill="#fdf0e6" stroke="#9a4a00" stroke-width="2"/>
      <path d="M24 13v14" fill="none" stroke="#9a4a00" stroke-width="4" stroke-linecap="round"/>
      <circle cx="24" cy="34" r="2.6" fill="#9a4a00"/>
    </svg>
    <h1 id="err-title" tabindex="-1">${e(title)}</h1>
    <p class="lead">${e(body)}</p>
    ${retryUrl ? `<p><a class="button button--link" href="${e(retryUrl)}">Try again</a></p>` : ""}
    <p class="ref ref--box">If you ask for help, please give this reference: <strong>${e(ref)}</strong></p>
  </section>`,
  });
}

/** wispr.flow.FRIENDLY plus the hosted portal's connector states. */
export const FRIENDLY: Record<string, [string, string]> = {
  not_found: [
    "We could not find your device on the guest network",
    "Please check that you are still connected to the guest Wi-Fi network, then try again.",
  ],
  login_failed: [
    "We could not connect your device",
    "Please try again. If it keeps happening, disconnect from the guest Wi-Fi and reconnect.",
  ],
  portal_config: ["Guest Wi-Fi sign-in is temporarily unavailable", "Please try again in a few minutes."],
  controller: ["Guest Wi-Fi sign-in is temporarily unavailable", "Please try again in a few minutes."],
  transport: ["Guest Wi-Fi sign-in is temporarily unavailable", "Please try again in a few minutes."],
  not_allowed: ["Guest Wi-Fi sign-in is temporarily unavailable", "Please try again in a few minutes."],
  connector_down: ["Guest Wi-Fi sign-in is temporarily unavailable", "Please try again in a few minutes."],
  connector_lost: [
    "We could not confirm your connection",
    "You may already be connected. Please try again to check.",
  ],
  pending_timeout: ["Connecting is taking longer than expected", "Please wait a moment and try again."],
  expired: ["This page has expired", "Please reload the page or reconnect to the guest Wi-Fi to start again."],
  bad_params: [
    "This sign-in page is missing information from the Wi-Fi network",
    "Please disconnect from the guest Wi-Fi, reconnect, and open any web page.",
  ],
  rate_limited: ["Too many attempts", "Please wait a minute, then try again."],
  not_found_page: ["Page not found", "Please open any web page to get back to the guest Wi-Fi sign-in."],
  server_error: ["Something went wrong", "Please try again in a few minutes."],
};
