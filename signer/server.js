"use strict";

const crypto = require("crypto");
const fs = require("fs");
const http = require("http");
const { spawn } = require("child_process");
const path = require("path");

const port = Number(process.env.PORT || 8787);
const bindHost = process.env.DOUYIN_SIGNER_BIND_HOST || "127.0.0.1";
const apiKeyFile = process.env.DOUYIN_SIGNER_API_KEY_FILE || "";
const inlineApiKey = (process.env.BACKEND_DOUYIN_SIGNER_API_KEY || "").trim();
let apiKey = "";
if (apiKeyFile && inlineApiKey) {
  console.error("Provide one signer key source.");
  process.exit(1);
}
try {
  apiKey = apiKeyFile ? fs.readFileSync(apiKeyFile, "utf8").trim() : inlineApiKey;
} catch (_error) {
  console.error("Signer key file is unavailable.");
  process.exit(1);
}
const warmPoolSize = parseBoundedInteger(
  process.env.DOUYIN_SIGNER_WARM_POOL_SIZE,
  2,
  0,
  8,
);
const queueTimeoutMs = parseBoundedInteger(
  process.env.DOUYIN_SIGNER_QUEUE_TIMEOUT_MS,
  15000,
  1000,
  30000,
);
const runtimeMetricsEnabled = process.env.SIGNER_RUNTIME_METRICS === "1";

if (!Number.isInteger(port) || port < 1 || port > 65535) {
  console.error("Douyin signer requires a valid PORT.");
  process.exit(1);
}
if (!/^[A-Za-z0-9_-]{32,256}$/.test(apiKey)) {
  console.error("Douyin signer requires a URL-safe key of 32 to 256 characters.");
  process.exit(1);
}
if (!["127.0.0.1", "0.0.0.0"].includes(bindHost)) {
  console.error("Douyin signer received an invalid bind address.");
  process.exit(1);
}

function parseBoundedInteger(value, fallback, minimum, maximum) {
  if (value === undefined || value === "") return fallback;
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < minimum || parsed > maximum) {
    console.error("Douyin signer received an invalid runtime pool setting.");
    process.exit(1);
  }
  return parsed;
}

function sendJson(res, statusCode, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(statusCode, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(body),
  });
  res.end(body);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let total = 0;
    req.on("data", (chunk) => {
      total += chunk.length;
      if (total > 1024 * 1024) {
        reject(new Error("request body too large"));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

function isAuthorized(req) {
  const provided = req.headers["x-api-key"];
  if (typeof provided !== "string") return false;
  const expectedBytes = Buffer.from(apiKey);
  const providedBytes = Buffer.from(provided);
  return (
    expectedBytes.length === providedBytes.length
    && crypto.timingSafeEqual(expectedBytes, providedBytes)
  );
}

async function handleSign(req, res) {
  if (!isAuthorized(req)) {
    sendJson(res, 401, { ok: false, error: "unauthorized" });
    return;
  }
  const started = Date.now();
  try {
    const raw = await readBody(req);
    const input = JSON.parse(raw || "{}");
    const result = await signPool.sign(input);
    const responsePayload = {
      ok: Boolean(result.a_bogus),
      a_bogus: result.a_bogus || null,
      msToken: result.msToken || "",
      duration_ms: Date.now() - started,
      version: "abogus-node-env-1",
      error: result.a_bogus ? undefined : "signing_failed",
      error_code: result.a_bogus ? undefined : "SIGNATURE_NOT_GENERATED",
    };
    if (runtimeMetricsEnabled && isSafeRuntimeMetrics(result.runtime_metrics)) {
      responsePayload.runtime_metrics = result.runtime_metrics;
    }
    sendJson(res, result.a_bogus ? 200 : 500, responsePayload);
  } catch (error) {
    sendJson(res, 500, {
      ok: false,
      a_bogus: null,
      duration_ms: Date.now() - started,
      error: "signing_failed",
      error_code: signErrorCode(error),
    });
  }
}

function isSafeRuntimeMetrics(value) {
  return value
    && Number.isInteger(value.cpu_ms)
    && value.cpu_ms >= 0
    && Number.isInteger(value.rss_bytes)
    && value.rss_bytes >= 0;
}

function childTimeout(input) {
  const timeout = Number(input && input.child_timeout_ms);
  return Number.isInteger(timeout) && timeout >= 1 && timeout <= 30000
    ? timeout
    : 10000;
}

function signErrorCode(error) {
  return error instanceof SignPoolError ? error.code : "SIGN_REQUEST_INVALID";
}

class SignPoolError extends Error {
  constructor(code) {
    super(code);
    this.code = code;
  }
}

class SingleUseSignPool {
  constructor(size, queueTimeout) {
    this.size = size;
    this.queueTimeout = queueTimeout;
    this.idleWorkers = [];
    this.pending = [];
    this.workers = new Set();
    this.closed = false;
    for (let index = 0; index < size; index += 1) this.spawnWorker();
  }

  sign(input) {
    if (this.closed) {
      return Promise.reject(new SignPoolError("SIGN_POOL_CLOSED"));
    }
    if (this.size === 0) return signInFreshChild(input);

    return new Promise((resolve, reject) => {
      const job = {
        input,
        resolve,
        reject,
        queueTimer: setTimeout(() => {
          if (!this.removePending(job)) return;
          reject(new SignPoolError("SIGN_POOL_QUEUE_TIMEOUT"));
        }, this.queueTimeout),
      };
      this.pending.push(job);
      this.dispatch();
    });
  }

  removePending(job) {
    const index = this.pending.indexOf(job);
    if (index === -1) return false;
    this.pending.splice(index, 1);
    clearTimeout(job.queueTimer);
    return true;
  }

  spawnWorker() {
    if (this.closed || this.workers.size >= this.size) return;
    const child = spawn(process.execPath, [path.join(__dirname, "sign_once.js"), "--warm"], {
      stdio: ["pipe", "pipe", "pipe"],
    });
    const worker = {
      child,
      state: "starting",
      startupOutput: "",
      resultOutput: "",
      currentJob: null,
      startupTimer: null,
      executionTimer: null,
      timedOut: false,
      closed: false,
    };
    this.workers.add(worker);
    worker.startupTimer = setTimeout(() => {
      worker.child.kill("SIGKILL");
    }, Math.min(this.queueTimeout, 5000));
    child.stdout.on("data", (chunk) => this.onStdout(worker, chunk));
    // stderr can contain a third-party stack with request context. Never
    // propagate it to an HTTP response or application log.
    child.stderr.on("data", () => {});
    child.on("error", () => {});
    child.on("close", (code) => this.onWorkerClosed(worker, code));
  }

  onStdout(worker, chunk) {
    if (worker.state === "starting") {
      worker.startupOutput += chunk.toString("utf8");
      const newline = worker.startupOutput.indexOf("\n");
      if (newline === -1) return;
      const readyLine = worker.startupOutput.slice(0, newline);
      const rest = worker.startupOutput.slice(newline + 1);
      worker.startupOutput = "";
      try {
        if (JSON.parse(readyLine).ready !== true) {
          throw new Error("worker did not become ready");
        }
      } catch (_error) {
        worker.child.kill("SIGKILL");
        return;
      }
      if (worker.startupTimer) clearTimeout(worker.startupTimer);
      worker.state = "idle";
      this.idleWorkers.push(worker);
      this.dispatch();
      if (rest) {
        if (worker.state === "busy") worker.resultOutput += rest;
        else worker.child.kill("SIGKILL");
      }
      return;
    }
    if (worker.state === "busy") worker.resultOutput += chunk.toString("utf8");
  }

  dispatch() {
    while (!this.closed && this.pending.length > 0 && this.idleWorkers.length > 0) {
      const worker = this.idleWorkers.shift();
      if (!worker || worker.state !== "idle") continue;
      const job = this.pending.shift();
      clearTimeout(job.queueTimer);
      worker.state = "busy";
      worker.currentJob = job;
      worker.executionTimer = setTimeout(() => {
        worker.timedOut = true;
        worker.child.kill("SIGKILL");
      }, childTimeout(job.input));
      try {
        worker.child.stdin.end(JSON.stringify(job.input));
      } catch (_error) {
        worker.timedOut = false;
        worker.child.kill("SIGKILL");
      }
    }
  }

  onWorkerClosed(worker, code) {
    if (worker.closed) return;
    worker.closed = true;
    this.workers.delete(worker);
    this.idleWorkers = this.idleWorkers.filter((item) => item !== worker);
    if (worker.startupTimer) clearTimeout(worker.startupTimer);
    if (worker.executionTimer) clearTimeout(worker.executionTimer);

    const job = worker.currentJob;
    if (job) {
      if (worker.timedOut) {
        job.reject(new SignPoolError("SIGN_CHILD_TIMEOUT"));
      } else if (code !== 0) {
        job.reject(new SignPoolError("SIGN_CHILD_EXIT"));
      } else {
        try {
          const result = JSON.parse(worker.resultOutput || "{}");
          job.resolve(result);
        } catch (_error) {
          job.reject(new SignPoolError("SIGN_CHILD_INVALID_OUTPUT"));
        }
      }
    }

    if (!this.closed) {
      this.spawnWorker();
      this.dispatch();
    }
  }

  close() {
    if (this.closed) return;
    this.closed = true;
    for (const job of this.pending.splice(0)) {
      clearTimeout(job.queueTimer);
      job.reject(new SignPoolError("SIGN_POOL_CLOSED"));
    }
    for (const worker of this.workers) {
      worker.child.kill("SIGTERM");
    }
  }
}

function signInFreshChild(input) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [path.join(__dirname, "sign_once.js")], {
      stdio: ["pipe", "pipe", "pipe"],
    });
    let stdout = "";
    const timeout = setTimeout(() => {
      child.kill("SIGKILL");
      reject(new SignPoolError("SIGN_CHILD_TIMEOUT"));
    }, childTimeout(input));
    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString("utf8");
    });
    child.stderr.on("data", () => {});
    child.on("error", () => {
      clearTimeout(timeout);
      reject(new SignPoolError("SIGN_CHILD_START_FAILED"));
    });
    child.on("close", (code) => {
      clearTimeout(timeout);
      try {
        const result = JSON.parse(stdout || "{}");
        if (code !== 0 && !result.error) result.error = "sign child failed";
        resolve(result);
      } catch (_error) {
        reject(new SignPoolError("SIGN_CHILD_INVALID_OUTPUT"));
      }
    });
    child.stdin.end(JSON.stringify(input));
  });
}

const signPool = new SingleUseSignPool(warmPoolSize, queueTimeoutMs);

const server = http.createServer(async (req, res) => {
  if (req.method === "GET" && req.url === "/health") {
    sendJson(res, 200, { ok: true, service: "abogus-signer" });
    return;
  }
  if (req.method === "GET" && req.url === "/version") {
    sendJson(res, 200, { ok: true, version: "abogus-node-env-1" });
    return;
  }
  if (req.method === "POST" && req.url === "/sign") {
    await handleSign(req, res);
    return;
  }
  sendJson(res, 404, { ok: false, error: "not found" });
});

server.listen(port, bindHost, () => {
  console.log(`Douyin signer listening on ${bindHost}:${port}`);
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.once(signal, () => {
    signPool.close();
    server.close(() => process.exit(0));
    setTimeout(() => process.exit(0), 1000).unref();
  });
}
