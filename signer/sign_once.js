"use strict";

const path = require("path");

function installGlobal(name, value) {
  Object.defineProperty(global, name, {
    value,
    writable: true,
    enumerable: true,
    configurable: true,
  });
}

function resetGeneratedValues() {
  global.__a_bogus = null;
  global.__msToken = null;
  global.a_bogus = null;
  global.msToken = null;
}

function installEnvironment(input) {
  const host = input.host || "fxg.jinritemai.com";
  const href = input.href || input.full_url || `https://${host}/`;
  const parsed = new URL(href, `https://${host}/`);
  const userAgent = input.user_agent || "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36";
  const cookie = input.cookie || "";

  global.self = global;
  global.top = global;
  global.parent = global;
  global.addEventListener = () => {};
  global.removeEventListener = () => {};
  global.dispatchEvent = () => true;
  global.location = {
    href: parsed.href,
    hostname: parsed.hostname || host,
    origin: parsed.origin || `https://${host}`,
    protocol: parsed.protocol || "https:",
    pathname: parsed.pathname || "/",
    search: parsed.search || "",
    hash: parsed.hash || "",
    port: parsed.port || "",
    host: parsed.host || host,
    toString() { return this.href; },
  };
  global.document = {
    referrer: input.referer || "",
    location: global.location,
    cookie,
    title: "",
    hidden: false,
    visibilityState: "visible",
    createElement: tag => ({ tagName: tag, getContext: () => null, style: {}, setAttribute: () => {}, getAttribute: () => null, appendChild: () => {} }),
    getElementById: () => null,
    getElementsByTagName: () => [],
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => true,
    createEvent: () => ({ initEvent: () => {} }),
    body: { appendChild: () => {}, style: {} },
    head: { appendChild: () => {} },
  };
  installGlobal("navigator", {
    userAgent,
    language: "zh-CN",
    languages: ["zh-CN", "zh"],
    platform: "Win32",
    cookieEnabled: true,
    hardwareConcurrency: 8,
    maxTouchPoints: 0,
    vendor: "Google Inc.",
    product: "Gecko",
    productSub: "20030107",
    onLine: true,
    plugins: { length: 0 },
    mimeTypes: { length: 0 },
  });
  global.screen = { width: 1440, height: 900, availWidth: 1440, availHeight: 860, colorDepth: 24, pixelDepth: 24 };
  global.outerWidth = 1440;
  global.outerHeight = 900;
  global.innerWidth = 1440;
  global.innerHeight = 900;
  global.devicePixelRatio = 1;
  installGlobal("localStorage", makeStorage());
  installGlobal("sessionStorage", makeStorage());
  installGlobal("performance", { now: () => Date.now(), getEntriesByType: () => [], getEntriesByName: () => [], mark: () => {}, measure: () => {} });
  global.atob = s => Buffer.from(s, "base64").toString("binary");
  global.btoa = s => Buffer.from(s, "binary").toString("base64");
  global.requestAnimationFrame = fn => setTimeout(fn, 16);
  global.cancelAnimationFrame = id => clearTimeout(id);
  global.matchMedia = () => ({ matches: false, addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {} });
  global.getComputedStyle = () => ({ getPropertyValue: () => "" });
  global.history = { pushState: () => {}, replaceState: () => {}, back: () => {}, go: () => {}, length: 1, state: null };
  global.MutationObserver = class { observe() {} disconnect() {} };
  global.Image = class { set src(v) {} addEventListener() {} };
  global.CustomEvent = class { constructor(type, options) { this.type = type; this.detail = options && options.detail; } };
  global.Event = class { constructor(type) { this.type = type; } };
  global.indexedDB = { open: () => ({ onupgradeneeded: null, onsuccess: null, onerror: null }) };
  try {
    const crypto = require("crypto");
    installGlobal("crypto", crypto.webcrypto || { getRandomValues: a => a, subtle: {} });
  } catch {
    installGlobal("crypto", { getRandomValues: a => a, subtle: {} });
  }

  const OriginalURLSearchParams = URLSearchParams;
  global.URLSearchParams = class extends OriginalURLSearchParams {
    append(key, value) {
      if (key === "a_bogus") global.__a_bogus = value;
      if (key === "msToken") global.__msToken = value;
      super.append(key, value);
    }
  };
  global.XMLHttpRequest = class {
    open(method, url) { this.method = method; this.url = url; }
    setRequestHeader() {}
    addEventListener() {}
    removeEventListener() {}
    send() {}
    abort() {}
  };
  installGlobal("window", new Proxy(global, {
    get(target, prop) { return target[prop]; },
    set(target, prop, value) { target[prop] = value; return true; },
  }));
}

function makeStorage() {
  const store = {};
  return {
    getItem: key => store[key] ?? null,
    setItem: (key, value) => { store[key] = String(value); },
    removeItem: key => { delete store[key]; },
    clear: () => Object.keys(store).forEach(key => delete store[key]),
    key: index => Object.keys(store)[index] || null,
    get length() { return Object.keys(store).length; },
  };
}

let bdmsLoaded = false;

function initializeBdms(input) {
  if (!bdmsLoaded) {
    require(path.join(__dirname, "vendor", "a_bogus.js"));
    bdmsLoaded = true;
  }
  const init = global.bdms && global.bdms.init;
  if (typeof init === "function") {
    init({
      aid: Number(input.aid || 6383),
      pageId: Number(input.page_id || 6241),
      paths: ["^/product/", "^/ffa/", "^/freight/", "^/ecom/", "^/api/", "^/compass_api/", "^/marketing/"],
      boe: false,
      ddrt: 8.5,
      ic: 8.5,
    });
  }
}


function normalizeSignInput(rawInput) {
  const input = rawInput || {};
  if (input.full_url || input.href || !input.url) return input;
  const host = input.host || "fxg.jinritemai.com";
  const apiPath = String(input.url || "/");
  const query = new URLSearchParams();
  const params = input.params && typeof input.params === "object" ? input.params : {};
  for (const [key, value] of Object.entries(params)) {
    if (key === "a_bogus") continue;
    if (value === undefined || value === null) continue;
    if (Array.isArray(value)) {
      for (const item of value) query.append(key, String(item));
    } else {
      query.append(key, String(value));
    }
  }
  const fullUrl = `https://${host}${apiPath}${query.toString() ? `?${query.toString()}` : ""}`;
  return {
    ...input,
    host,
    full_url: fullUrl,
    href: fullUrl,
    method: input.method || "GET",
    ms_token: input.ms_token || params.msToken || "",
  };
}

async function sign(input) {
  input = normalizeSignInput(input);
  installEnvironment(input);
  initializeBdms(input);
  resetGeneratedValues();

  const xhr = new XMLHttpRequest();
  xhr.open(input.method || "GET", input.full_url || input.href || `https://${input.host || "fxg.jinritemai.com"}/`);
  xhr.send(input.body || null);

  const started = Date.now();
  while (Date.now() - started < Number(input.timeout_ms || 3000)) {
    if (global.__a_bogus || global.a_bogus) break;
    await new Promise(resolve => setTimeout(resolve, 20));
  }

  return {
    a_bogus: global.__a_bogus || global.a_bogus || null,
    msToken: global.__msToken || input.ms_token || "",
  };
}

async function cliMain() {
  // A warm worker is still deliberately single-use.  The parent signer can
  // start this process before a request arrives, but every request receives
  // its own Node process and therefore its own vendor globals, timers and
  // browser-like environment.
  if (process.argv.includes("--warm")) {
    process.stdout.write(`${JSON.stringify({ ready: true })}\n`);
  }
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  const input = JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
  const result = await sign(input);
  if (process.env.SIGNER_RUNTIME_METRICS === "1") {
    const usage = process.resourceUsage();
    result.runtime_metrics = {
      cpu_ms: Math.round((usage.userCPUTime + usage.systemCPUTime) / 1000),
      rss_bytes: process.memoryUsage().rss,
    };
  }
  process.stdout.write(JSON.stringify(result));
  process.exit(0);
}

if (require.main === module) {
  cliMain().catch(error => {
    process.stdout.write(JSON.stringify({ a_bogus: null, error: error.message }));
    process.exitCode = 1;
    process.exit(1);
  });
}

module.exports = { sign };
