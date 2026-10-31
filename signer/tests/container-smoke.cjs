"use strict";

const assert = require("node:assert/strict");

(async () => {
  const root = "http://127.0.0.1:8787";
  const key = process.env.SIGNER_TEST_API_KEY;
  assert.ok(key, "missing synthetic test key");
  let healthy = false;
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try {
      const response = await fetch(`${root}/health`, { signal: AbortSignal.timeout(500) });
      if (response.status === 200) { healthy = true; break; }
    } catch (_error) { /* container is starting */ }
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  assert.equal(healthy, true);
  const post = (index, token) => fetch(`${root}/sign`, {
    method: "POST",
    headers: { "content-type": "application/json", ...(token ? { "x-api-key": token } : {}) },
    body: JSON.stringify({
      host: "fxg.jinritemai.com", url: "/product/tproduct/list", method: "GET",
      params: { page: 1 }, cookie: `synthetic_session=store${index % 5}`,
      aid: 6383, page_id: 6241,
    }),
    signal: AbortSignal.timeout(20000),
  });
  assert.equal((await post(0, "")).status, 401);
  const responses = await Promise.all(Array.from({ length: 25 }, (_, index) => post(index, key)));
  for (const response of responses) {
    assert.equal(response.status, 200);
    const result = await response.json();
    assert.equal(result.ok, true);
    assert.ok(result.a_bogus);
    assert.doesNotMatch(JSON.stringify(result), /synthetic_session/);
  }
  console.log("Container smoke passed: authenticated synthetic signing, 25 concurrent requests, no external network.");
})().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
