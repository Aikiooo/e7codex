// shared.js — tiny shared runtime helpers for index.html + viewer.html.
// No build step: a plain classic script that exposes one global `E7` object.
// Loaded via <script src="shared.js"> BEFORE each page's inline script.
"use strict";
const E7 = (() => {
  // Local-dev hostnames use relative asset paths (python -m http.server from
  // site/, file://, or LAN IPs so the viewer works across a local network
  // without hitting CDN CORS); everything else — production e7codex.com,
  // Pages preview URLs — uses the R2-backed CDN. Single source of truth:
  // index.html keys voice clips off this, viewer.html keys spine rigs off it.
  const h = location.hostname;
  const isLocal = h === "localhost" || h === "127.0.0.1" || h === "" ||
    /^192\.168\.|^10\.|^172\.(1[6-9]|2\d|3[01])\./.test(h);
  const CDN = "https://assets.e7codex.com";
  const escapeHtml = (s) => String(s ?? "").replace(/[&<>"']/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ── i18n ─────────────────────────────────────────────────────────────────
  // Localization for both pages. English is inline (units.json names + the maps
  // below) so the default path costs ZERO extra fetch; every other language pulls
  // ONE overlay data/lang/<lang>.json = {names, artifacts, events, elements,
  // classes, ui} lazily on first use. Selection: ?lang= wins and persists to
  // localStorage, else the stored value, else navigator.language, else en.
  // 10 game-sourced languages + Vietnamese (vi) — unofficial, hand-translated UI,
  // game names fall back to English (no in-game Vietnamese text exists).
  const LANGS = ["en", "ko", "ja", "zhs", "zht", "th", "de", "fr", "es", "pt", "vi"];
  const LANG_NAMES = {
    en: "English", ko: "한국어", ja: "日本語", zhs: "简体中文", zht: "繁體中文",
    th: "ไทย", de: "Deutsch", fr: "Français", es: "Español", pt: "Português",
    vi: "Tiếng Việt*",   // * = unofficial (community translation, not in-game)
  };
  // Game-accurate English display terms (the site used to show the raw 'wind'
  // token; the game calls that element "Earth", manauser "Soul Weaver", assassin
  // "Thief"). gameTerm() routes English through these too so every language is
  // consistent with the game.
  const EN_TERMS = {
    element: { fire: "Fire", ice: "Ice", wind: "Earth", light: "Light", dark: "Dark" },
    class: { warrior: "Warrior", knight: "Knight", ranger: "Ranger", mage: "Mage",
             manauser: "Soul Weaver", assassin: "Thief" },
  };
  // English UI chrome — the source of truth for every hand-translated string.
  // Non-English overrides live in the overlay's `ui` block. {n} is interpolated
  // by t(key,{n}). Populated during the chrome-keying pass; nav seeded here.
  const CHROME_EN = {
    // nav
    nav_hub: "Units", nav_artifacts: "Artifacts", nav_updates: "Updates",
    nav_emotes: "Emotes", nav_wallpapers: "Wallpapers", nav_about: "About",
    nav_story: "Story",
    // hub bar / filters
    hub_search_ph: "search name or id  ·  iseria, c1019, ravi…",
    hub_sort: "sort", sort_timeline: "timeline", sort_az: "A→Z",
    sort_timeline_t: "newest releases first", sort_az_t: "alphabetical by name",
    hub_sort_aria: "sort order", hub_empty: "no match.",
    kbd_toggle_t: "toggle text / numeric keyboard",
    kind_all: "ALL", kind_unit: "Heroes", kind_npc: "NPCs", kind_monster: "Monsters",
    kind_pet: "Pets", kind_artifact: "Artifacts", kind_special: "Special", kind_other: "Other",
    filt_element: "element", filt_class: "class", filt_rarity: "rarity", filt_clear: "clear",
    // badges
    badge_new: "NEW", badge_updated: "UPDATED", badge_unrel: "UNRELEASED",
    badge_unrel_local: "UNRELEASED · LOCAL ONLY",
    badge_unrel_t: "held back from the public site — visible locally only",
    forms_n: "{n} forms",
    // card meta
    meta_rig: "rig", meta_art: "{n} art", meta_skill: "skill",
    // detail
    btn_back: "‹ back",
    btn_live_viewer: "▶ live viewer", btn_live_viewer_combat: "▶ live viewer (combat)",
    btn_live_viewer_combat_t: "skill animations (skill1/skill2/skill3/run/…)",
    btn_texture: "⊡ texture", detail_base_id: "base {id}",
    render_switch: "render:", render_base: "Base", render_thumb: "Thumb",
    pose_switch: "pose:",
    hdr_voice: "Voice", hdr_artwork: "Bundled artwork", hdr_skill_anim: "Skill animation",
    hdr_intimacy: "Intimacy illustration", render_spine: "static render · spine {ver}",
    voice_hint: "click a line to play",
    vcat_battle: "Battle", vcat_skill: "Skill", vcat_camping: "Camping", vcat_misc: "Other",
    vgrp_skills: "Skills", vgrp_combat: "Combat", vgrp_status: "Status", vgrp_other: "Idle & misc",
    // artifacts view
    arti_search_ph: "search artifacts by name or art####",
    arti_count: "{n} of {total} artifacts · click any for full art",
    arti_cb_t: "open on ceciliabot",
    // updates view
    upd_count: "{n} update codenames discovered · per-unit tagging requires the encrypted output/db",
    patch_hdr: "Patch diff · last {n} data pack(s) · previews hosted temporarily",
    patch_note: "Unannounced content is intentionally omitted — E7 Codex archives released Epic Seven assets and avoids surfacing anything Smilegate hasn't revealed yet.",
    // emotes view
    emote_count: "{n} character groups · {files} emote files · {linked} linked to a unit page",
    emote_open: "open detail →", emote_nolink: "no unit page",
    // wallpapers view
    wp_count: "{n} wallpapers · click any to open full-size",
    wp_lobby: "Lobby BG", wp_event: "Event splash", wp_episode: "Episode art", wp_story: "Story bg",
    // errors / empty
    loading: "loading…",
    err_load: "couldn’t load the codex data — check your connection.",
    btn_retry: "↻ retry",
    empty_updates: "No updates indexed — run build_index.py.",
    empty_emotes: "No emotes indexed — run build_index.py.",
    empty_wallpapers: "No wallpapers indexed — run build_index.py.",
    empty_artifacts: "No artifacts indexed — run build_index.py.",
    unknown_id: "unknown id: {id}",
    // lightbox
    lb_close: "close", lb_download: "download",
    // viewer
    viewer_subtitle: "live spine viewer", viewer_back: "‹ back to codex",
    viewer_anim: "Animation", viewer_skin: "Skin", viewer_char: "Character", viewer_quality: "Quality",
    viewer_stage: "Stage", viewer_skillfx: "Skill FX", viewer_hidefx: "Hide FX/BG", viewer_assets: "Assets",
    vz_in: "zoom in", vz_out: "zoom out", vz_fit: "fit / reset",
    vz_shot: "download current frame as transparent PNG",
    vexp_title: "Export animation",
    // 404
    nf_title: "404 · not found", nf_sub: "nothing here",
    nf_body: "This path doesn’t lead anywhere in the codex. Maybe a stale link, or a unit slug that doesn’t exist.",
    nf_back: "‹ back to codex",
  };

  let _lang = "en";
  let _overlay = null;              // data/lang/<lang>.json for the active non-en lang
  const _overlayCache = {};         // lang -> overlay (memoized, like ensureVoices)

  function getLang() {
    try {
      const q = new URLSearchParams(location.search).get("lang");
      if (q && LANGS.includes(q)) localStorage.setItem("e7_lang", q);
      const s = localStorage.getItem("e7_lang");
      if (s && LANGS.includes(s)) return s;
    } catch (e) {}
    const n = (navigator.language || "en").toLowerCase();
    if (n.startsWith("zh")) return (n.includes("tw") || n.includes("hant") || n.includes("hk")) ? "zht" : "zhs";
    const two = n.slice(0, 2);
    return LANGS.includes(two) ? two : "en";
  }

  // Load (and memoize) the overlay for a language. English resolves instantly with
  // no fetch. A fetch failure degrades silently to English (null overlay).
  function loadLang(l) {
    _lang = LANGS.includes(l) ? l : "en";
    if (_lang === "en") { _overlay = null; return Promise.resolve(); }
    if (_overlayCache[_lang]) { _overlay = _overlayCache[_lang]; return Promise.resolve(); }
    return fetch(`data/lang/${_lang}.json`, { cache: "no-cache" })
      .then(r => r.ok ? r.json() : null)
      .then(o => { _overlay = o; if (o) _overlayCache[_lang] = o; })
      .catch(() => { _overlay = null; });
  }
  function setLang(l) {
    try { localStorage.setItem("e7_lang", l); } catch (e) {}
    return loadLang(l);
  }

  // Chrome/UI string. Overlay override → inline English → the key itself.
  // params interpolates {name} placeholders, e.g. t("hub_count",{n:12}).
  function t(key, params, fallback) {
    let s = (_overlay && _overlay.ui && _overlay.ui[key]) || CHROME_EN[key] || fallback || key;
    if (params) for (const k in params) s = s.split("{" + k + "}").join(params[k]);
    return s;
  }
  // Hero / artifact display name for a record. English (and any missing overlay
  // entry) falls back to the inline value already in units.json/artifacts.json.
  function gameName(rec, field) {
    field = field || "name";
    if (_lang === "en" || !_overlay || !_overlay.names) return rec[field];
    const nm = _overlay.names;
    if (field === "hero_name") return nm[rec.base_id] || nm[rec.id] || rec[field];
    return nm[rec.id] || rec[field];
  }
  // Artifact name by id (artifacts carry no per-record overlay hook otherwise).
  function artifactName(rec) {
    if (_lang === "en" || !_overlay || !_overlay.artifacts) return rec.name;
    return _overlay.artifacts[rec.id] || rec.name;
  }
  // Localized event/update title by codename (updates.json is keyed by en title).
  function eventTitle(codename, enTitle) {
    if (_lang !== "en" && _overlay && _overlay.events && _overlay.events[codename]) return _overlay.events[codename];
    return enTitle;
  }
  // Element / class display term. kind = "element" | "class", token = the internal
  // slug (fire/…, warrior/…). Localized from the overlay, else the game English term.
  // The site aliases the game's internal role tokens for display (assassin→thief,
  // manauser→soul-weaver); accept either form so pills (raw u.role) and filter
  // chips (aliased) both resolve.
  const CLASS_ALIAS = { "soul-weaver": "manauser", "thief": "assassin", "theif": "assassin" };
  function gameTerm(kind, token) {
    if (!token) return token;
    if (kind === "class") token = CLASS_ALIAS[token] || token;
    if (_lang !== "en" && _overlay) {
      const m = kind === "element" ? _overlay.elements : kind === "class" ? _overlay.classes : null;
      if (m && m[token]) return m[token];
    }
    return (EN_TERMS[kind] && EN_TERMS[kind][token]) || token;
  }
  // Sweep static HTML chrome: any element with data-i18n="key" gets its
  // textContent localized; data-i18n-attr="title:key,placeholder:key2" localizes
  // attributes. Missing translations (t returns the key) leave the markup's
  // English untouched. Call on boot + after each language switch. Dynamic
  // template-literal strings use E7.t() inline instead of this sweep.
  function applyI18n(root) {
    root = root || document;
    root.querySelectorAll("[data-i18n]").forEach(el => {
      const k = el.getAttribute("data-i18n"), v = t(k);
      if (v && v !== k) el.textContent = v;
    });
    root.querySelectorAll("[data-i18n-attr]").forEach(el => {
      el.getAttribute("data-i18n-attr").split(",").forEach(pair => {
        const idx = pair.indexOf(":");
        if (idx < 0) return;
        const attr = pair.slice(0, idx).trim(), k = pair.slice(idx + 1).trim(), v = t(k);
        if (v && v !== k) el.setAttribute(attr, v);
      });
    });
  }
  // <select> switcher markup for a page header. id lets each page wire its own onchange.
  function langSelectHtml(id) {
    const opts = LANGS.map(l =>
      `<option value="${l}"${l === _lang ? " selected" : ""}>${escapeHtml(LANG_NAMES[l])}</option>`).join("");
    return `<select id="${id}" class="lang-sel" aria-label="Language" title="Language / 언어 / 言語">${opts}</select>`;
  }

  return {
    isLocal,
    spineBase: isLocal ? "assets" : CDN,
    voiceBase: isLocal ? "voice" : CDN + "/voice",
    escapeHtml,
    // i18n
    LANGS, LANG_NAMES,
    getLang, setLang, loadLang,
    t, gameName, artifactName, eventTitle, gameTerm, applyI18n, langSelectHtml,
    lang: { get: () => _lang },
  };
})();
