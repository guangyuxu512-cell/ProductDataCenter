"use strict";

const assert = require("node:assert/strict");
const { spawn, spawnSync } = require("node:child_process");
const fs = require("node:fs");
const net = require("node:net");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const serverPath = path.join(root, "server.js");
const key = "synthetic-key-for-local-tests-only-123456";

async function unusedPort() {
  const socket = net.createServer();
  await new Promise((resolve, reject) => socket.once("error", reject).listen(0, "127.0.0.1", resolve));
  const port = socket.address().port;
  await new Promise((resolve, reject) => socket.close((error) => error ? reject(error) : resolve()));
  return port;
}

test("isolated signer requires authentication and serves synthetic concurrent requests", { timeout: 30000 }, async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "pdc-signer-test-"));
  const keyFile = path.join(directory, "key");
  fs.writeFileSync(keyFile, key, { mode: 0o600 });
  const port = await unusedPort();
  const child = spawn(process.execPath, [serverPath], {
    cwd: root,
    env: {
      ...process.env,
      PORT: String(port),
      DOUYIN_SIGNER_API_KEY_FILE: keyFile,
      BACKEND_DOUYIN_SIGNER_API_KEY: "",
      DOUYIN_SIGNER_WARM_POOL_SIZE: "5",
      NODE_OPTIONS: `--require ${path.join(__dirname, "no-network.cjs")}`,
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let logs = "";
  child.stdout.on("data", (chunk) => { logs += chunk; });
  child.stderr.on("data", (chunk) => { logs += chunk; });
  try {
    const rootUrl = `http://127.0.0.1:${port}`;
    let ready = false;
    for (let attempt = 0; attempt < 100; attempt += 1) {
      try {
        const response = await fetch(`${rootUrl}/health`, { signal: AbortSignal.timeout(500) });
        if (response.status === 200) { ready = true; break; }
      } catch (_error) { /* process is still starting */ }
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    assert.equal(ready, true, "signer did not become ready");
    const body = (store) => JSON.stringify({
      host: "fxg.jinritemai.com", url: "/product/tproduct/list",
      params: { page: 1 }, method: "GET", cookie: `synthetic_session=store${store}`,
      aid: 6383, page_id: 6241,
    });
    const post = (store, apiKey) => fetch(`${rootUrl}/sign`, {
      method: "POST", headers: { "content-type": "application/json", ...(apiKey ? { "x-api-key": apiKey } : {}) },
      body: body(store), signal: AbortSignal.timeout(20000),
    });
    assert.equal((await post(0, "")).status, 401);
    assert.equal((await post(0, "incorrect-key")).status, 401);
    const responses = await Promise.all(Array.from({ length: 25 }, (_, index) => post(index % 5, key)));
    const results = await Promise.all(responses.map(async (response) => {
      assert.equal(response.status, 200);
      return response.json();
    }));
    assert.equal(results.length, 25);
    for (const result of results) {
      assert.equal(result.ok, true);
      assert.ok(typeof result.a_bogus === "string" && result.a_bogus.length > 0);
      assert.doesNotMatch(JSON.stringify(result), /synthetic_session/);
    }
    assert.doesNotMatch(logs, /synthetic_session|synthetic-key-for-local-tests/);
  } finally {
    child.kill("SIGTERM");
    await new Promise((resolve) => {
      if (child.exitCode !== null || child.signalCode !== null) return resolve();
      child.once("close", resolve);
      setTimeout(() => { child.kill("SIGKILL"); resolve(); }, 5000).unref();
    });
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test("signer fails closed when the key is absent or ambiguous", () => {
  const common = { ...process.env, PORT: "18787", BACKEND_DOUYIN_SIGNER_API_KEY: "", DOUYIN_SIGNER_API_KEY_FILE: "" };
  const missing = spawnSync(process.execPath, [serverPath], { cwd: root, env: common, encoding: "utf8", timeout: 5000 });
  assert.notEqual(missing.status, 0);
  const weak = spawnSync(process.execPath, [serverPath], {
    cwd: root, encoding: "utf8", timeout: 5000,
    env: { ...common, BACKEND_DOUYIN_SIGNER_API_KEY: "short" },
  });
  assert.notEqual(weak.status, 0);
  const conflicting = spawnSync(process.execPath, [serverPath], {
    cwd: root, encoding: "utf8", timeout: 5000,
    env: { ...common, BACKEND_DOUYIN_SIGNER_API_KEY: key, DOUYIN_SIGNER_API_KEY_FILE: "/nonexistent" },
  });
  assert.notEqual(conflicting.status, 0);
  assert.doesNotMatch(`${conflicting.stdout}${conflicting.stderr}`, /synthetic-key-for-local-tests/);
});
