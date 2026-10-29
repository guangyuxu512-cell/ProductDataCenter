import { parseProductListOptions, buildProductListQueries } from './collector/product-query-v1.mjs';
let input = '';
for await (const chunk of process.stdin) input += chunk;
const results = JSON.parse(input).map((params) => {
  try {
    const url = new URL('http://fixture.invalid/api/v1/products');
    for (const [key, value] of Object.entries(params)) url.searchParams.set(key, String(value));
    return { options: parseProductListOptions(url), queries: buildProductListQueries(parseProductListOptions(url)) };
  } catch (error) { return { error: error.message, status: error.status }; }
});
process.stdout.write(JSON.stringify(results));
