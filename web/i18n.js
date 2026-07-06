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

  function pick() {
    const saved = (localStorage.getItem("molgang_locale") || "").toLowerCase();
    const wanted = saved || (navigator.language || "en").toLowerCase();
    return SUPPORTED.find((l) => wanted.startsWith(l)) || "en";
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
    lang = pick();
    dict = lang === "en" ? en : await load(lang);
    document.documentElement.lang = lang;
  })();

  return { t, apply, setLocale, ready, locale: () => lang };
})();
