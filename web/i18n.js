"use strict";
/* MOLGANG chrome i18n (#117) — lightweight, no framework.
 *
 *   I18N.ready              resolves once the active locale (+ EN fallback) is loaded
 *   I18N.t(key, vars?)      translated string; missing keys fall back EN → key
 *   I18N.apply(root?)       translate static DOM: [data-i18n] (text or HTML via
 *                           data-i18n-html), [data-i18n-title], [data-i18n-placeholder]
 *   I18N.setLocale(lang)    persist + set <html lang> + re-apply the static scan
 *   I18N.locale()           the active locale ("en" | "nl")
 *
 * Canonical protocol vocabulary (Web, Knitweb, Knit, Pulse, Fiber, silk, spiders,
 * PLS) is NEVER translated — locale files translate the copy around it only.
 * Locale JSONs are fetched relative to the page → path-prefix-safe (/molgang/…).
 */
window.I18N = (() => {
  const SUPPORTED = ["en", "nl"];
  let lang = "en";
  let dict = {};
  let en = {};

  // Initial-locale detection cascade (explicit choice always wins):
  //   1. device data — navigator.languages (OS/browser setting) and, as a
  //      device-location hint, the Intl timezone (Europe/Amsterdam → nl);
  //   2. ISP location — one bounded (1.5s, fail-silent, session-cached) geo
  //      lookup of the connection's country, only consulted when the device
  //      signal is generic English;
  //   3. referring website — a .nl/.be referrer nudges Dutch;
  //   default: en.
  const NL_TZ = ["Europe/Amsterdam", "Europe/Brussels"];
  const NL_CC = ["NL", "BE"];

  function deviceLocale() {
    const langs = (navigator.languages && navigator.languages.length)
      ? navigator.languages : [navigator.language || "en"];
    for (const raw of langs) {
      const l = String(raw).toLowerCase();
      const hit = SUPPORTED.find((s) => s !== "en" && l.startsWith(s));
      if (hit) return hit;                       // any explicit non-EN device language wins
    }
    try {
      const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
      if (NL_TZ.includes(tz)) return "nl";       // device clock region as location hint
    } catch (e) { /* older engines */ }
    return null;                                 // only generic English — inconclusive
  }

  async function ispLocale() {
    const cached = sessionStorage.getItem("molgang_geo_cc");
    if (cached) return NL_CC.includes(cached) ? "nl" : null;
    try {
      const ctl = new AbortController();
      const timer = setTimeout(() => ctl.abort(), 1500);
      const r = await fetch("https://ipapi.co/json/", { signal: ctl.signal });
      clearTimeout(timer);
      if (!r.ok) return null;
      const cc = String((await r.json()).country_code || "").toUpperCase();
      if (cc) sessionStorage.setItem("molgang_geo_cc", cc);
      return NL_CC.includes(cc) ? "nl" : null;
    } catch (e) {
      return null;                               // offline/blocked/slow: never the boot's problem
    }
  }

  function referrerLocale() {
    try {
      const host = new URL(document.referrer).hostname.toLowerCase();
      if (host.endsWith(".nl") || host.endsWith(".be")) return "nl";
    } catch (e) { /* no or opaque referrer */ }
    return null;
  }

  async function pick() {
    const saved = (localStorage.getItem("molgang_locale") || "").toLowerCase();
    if (SUPPORTED.includes(saved)) return saved; // 0. the player's explicit choice
    return deviceLocale()                        // 1. device settings + clock region
      || (await ispLocale())                     // 2. connection country
      || referrerLocale()                        // 3. linking site
      || "en";
  }

  async function load(l) {
    try {
      const r = await fetch("locales/" + l + ".json");
      return r.ok ? await r.json() : {};
    } catch (e) {
      return {};                                 // offline first-load: keys fall back
    }
  }

  function t(key, vars) {
    let s = dict[key] ?? en[key] ?? key;         // missing key → EN → the key itself
    if (vars) for (const k of Object.keys(vars)) s = s.replaceAll("{" + k + "}", vars[k]);
    return s;
  }

  function apply(root) {
    const r = root || document;
    r.querySelectorAll("[data-i18n]").forEach((el) => {
      const v = t(el.getAttribute("data-i18n"));
      if (el.hasAttribute("data-i18n-html")) el.innerHTML = v;
      else el.textContent = v;
    });
    r.querySelectorAll("[data-i18n-title]").forEach((el) => {
      el.title = t(el.getAttribute("data-i18n-title"));
    });
    r.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
      el.placeholder = t(el.getAttribute("data-i18n-placeholder"));
    });
    const sw = document.getElementById("lang-switch");
    if (sw) sw.value = lang;
  }

  async function setLocale(l) {
    if (!SUPPORTED.includes(l)) l = "en";
    lang = l;
    localStorage.setItem("molgang_locale", l);
    document.documentElement.lang = l;
    dict = l === "en" ? en : await load(l);
    apply();
    document.dispatchEvent(new CustomEvent("i18n:changed", { detail: { lang: l } }));
  }

  const ready = (async () => {
    en = await load("en");
    lang = await pick();
    dict = lang === "en" ? en : await load(lang);
    document.documentElement.lang = lang;
  })();

  return { t, apply, setLocale, ready, locale: () => lang };
})();
