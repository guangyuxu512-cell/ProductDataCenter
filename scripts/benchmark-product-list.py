"""Synthetic HTTP/PG16 benchmark. Refuse to touch any non-empty or non-local database."""
from __future__ import annotations

import asyncio
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
DATABASE_URL = os.environ['BACKEND_DATABASE_URL']
EDIT_DRAFTS = os.environ.get('BENCHMARK_PRODUCT_EDITS', '0') == '1'
url = make_url(DATABASE_URL)
if url.host not in {'127.0.0.1', 'localhost', 'postgres'} or url.database != 'product_workbench_perf':
    raise SystemExit('Only an empty isolated local product_workbench_perf database is allowed')

engine = create_engine(DATABASE_URL)
group_id = '00000000-0000-4000-8000-000000000001'
fixtures = ROOT / 'backend/tests/fixtures/collector'
started = time.perf_counter()
with engine.begin() as conn:
    if conn.execute(text("SELECT count(*) FROM pg_tables WHERE schemaname='public'")).scalar_one() != 0:
        raise SystemExit('Refusing a database with existing public tables')
    for path in sorted(fixtures.glob('000[1-7]_*.sql')):
        conn.exec_driver_sql(path.read_text(encoding='utf-8'))
    conn.exec_driver_sql("INSERT INTO product_groups(group_id, group_name) VALUES (%s, %s)", (group_id, '隔离基准分组'))
    # Only this isolated bulk-load transaction disables triggers. All generated
    # foreign keys are valid, and the original trigger definitions are kept.
    conn.exec_driver_sql("SET LOCAL session_replication_role = 'replica'")
    conn.exec_driver_sql("""
        INSERT INTO products(product_id, source_platform, source_product_id, title, shop_name,
          category_path, group_id, captured_at, sku_count, main_image_count,
          detail_image_count, sku_image_count, current_price_min, current_price_max, uu_json)
        SELECT CASE WHEN mod(n, 10) = 0 THEN 'pdd:' ELSE '' END || (3800000000000000000::bigint+n)::text,
          CASE WHEN mod(n, 10) = 0 THEN 'pinduoduo' ELSE 'douyin' END,
          (3800000000000000000::bigint+n)::text,
          CASE WHEN mod(n, 50) = 0 THEN '厨房收纳套装' WHEN mod(n, 2) = 0 THEN '厨房商品' ELSE '家居商品' END || n::text,
          '隔离测试店铺', '家居/测试类目', CASE WHEN mod(n, 4) = 0 THEN %s::uuid END,
          now() - n * interval '1 second', 4, 1, 1, 2, 19.99, 29.99,
          jsonb_build_object('goodsInfo', jsonb_build_object('productId', (3800000000000000000::bigint+n)::text))
        FROM generate_series(1, 300000) n
    """, (group_id,))
    conn.exec_driver_sql("""
        INSERT INTO product_skus(product_id, sku_id, sku_name, current_price, sort_order)
        SELECT p.product_id, 'sku-' || n::text, '测试规格', 19.99, n
        FROM products p CROSS JOIN generate_series(1, 4) n
    """)
    conn.exec_driver_sql("""
        INSERT INTO product_images(product_id, image_type, sort_order, rel_path, source_url)
        SELECT p.product_id, v.kind, v.position, '',
          'https://fixture.invalid/' || p.product_id || '/' || v.kind || '/' || v.position::text || '.webp'
        FROM products p CROSS JOIN (VALUES ('main',0),('detail',0),('sku',0),('sku',1)) AS v(kind,position)
    """)
    conn.exec_driver_sql("SET LOCAL session_replication_role = 'origin'")
    conn.exec_driver_sql((fixtures / '0008_product_query_performance.sql').read_text(encoding='utf-8'))
    if EDIT_DRAFTS:
        # Apply only to this disposable benchmark database; no application startup DDL.
        conn.exec_driver_sql((ROOT / 'docs/migrations/product-edit-v1-proposal.sql').read_text(encoding='utf-8'))
        conn.exec_driver_sql("""
            INSERT INTO product_workbench_edits(product_id,revision,source_fingerprint,draft)
            SELECT product_id, 1, repeat('a',64), jsonb_build_object(
              'title', '人工编辑' || title,
              'mainImages', jsonb_build_array(jsonb_build_object('id','main-1','url','https://fixture.invalid/a.webp')),
              'detailImages', '[]'::jsonb,
              'dimensions', '[]'::jsonb,
              'imageDimensionId', NULL,
              'skus', jsonb_build_array(jsonb_build_object('id','sku-1','price','19.99')))
            FROM products WHERE mod(source_product_id::bigint,10)=0
        """)
with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as conn:
    for table in ('products', 'product_images', 'product_skus', 'product_groups', *(['product_workbench_edits'] if EDIT_DRAFTS else [])):
        conn.exec_driver_sql(f'ANALYZE {table}')
    counts = {table: conn.execute(text(f'SELECT count(*) FROM {table}')).scalar_one()
              for table in ('products', 'product_images', 'product_skus')}
    pg_version = conn.exec_driver_sql('SHOW server_version').scalar_one()
assert counts == {'products': 300000, 'product_images': 1200000, 'product_skus': 1200000}, counts
engine.dispose()
setup_seconds = round(time.perf_counter() - started, 2)

environment = dict(os.environ, BACKEND_API_TOKEN='isolated-admin-token', BACKEND_RPA_API_TOKEN='isolated-rpa-token',
                   BACKEND_ENABLE_PRODUCT_EDITS='true' if EDIT_DRAFTS else 'false')
server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1',
                           '--port', '18761', '--no-access-log', '--log-level', 'warning'],
                          cwd=ROOT / 'backend', env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def percentile(values: list[float], fraction: float) -> float:
    return round(sorted(values)[math.ceil(len(values) * fraction) - 1], 2)


async def measure() -> dict:
    async with httpx.AsyncClient(base_url='http://127.0.0.1:18761', timeout=30, trust_env=False,
                                 headers={'Authorization': 'Bearer isolated-admin-token'}) as client:
        for _ in range(100):
            try:
                if (await client.get('/health')).status_code == 200:
                    break
            except httpx.TransportError:
                await asyncio.sleep(0.1)
        else:
            raise RuntimeError('Isolated backend did not become healthy')
        capabilities = await client.get('/api/v1/capabilities')
        capabilities.raise_for_status()
        assert capabilities.json()['productEdit'] is EDIT_DRAFTS
        cases = [
            ('default_with_total', {'limit': '20'}, 300000),
            ('page_without_total', {'limit': '20', 'offset': '20', 'includeTotal': 'false'}, None),
            ('exact_id', {'productId': '3800000000000000001'}, 1),
            ('platform_pdd', {'platform': 'pinduoduo'}, 30000),
            ('group', {'groupId': group_id}, 75000),
            ('keyword_four_chars', {'q': '厨房收纳'}, 6000),
            ('keyword_two_chars', {'q': '厨房'}, 150000),
            ('deep_offset_299800', {'offset': '299800', 'includeTotal': 'false'}, None),
        ]
        if EDIT_DRAFTS:
            cases.append(('edited_title_four_chars', {'q': '人工编辑'}, 30000))
        results = {}
        async def request(params, expected):
            start = time.perf_counter()
            response = await client.get('/api/v1/products', params={'limit': '20', **params})
            elapsed = (time.perf_counter() - start) * 1000
            response.raise_for_status()
            page = response.json()
            assert page['total'] == expected, (params, page['total'], expected)
            assert len(page['items']) <= 20 and all('uu_json' not in item for item in page['items'])
            return elapsed, len(response.content)
        for name, params, expected in cases:
            for _ in range(2):
                await request(params, expected)
            samples = [await request(params, expected) for _ in range(30)]
            elapsed = [sample[0] for sample in samples]
            results[name] = {'samples': len(elapsed), 'failed': 0, 'p50_ms': percentile(elapsed, 0.5),
                             'p95_ms': percentile(elapsed, 0.95), 'max_ms': round(max(elapsed), 2),
                             'response_bytes': samples[0][1]}
        params = {'limit': '20', 'includeTotal': 'false'}
        await request(params, None)
        samples = []
        for _ in range(6):
            samples.extend(await asyncio.gather(*(request(params, None) for _ in range(5))))
        elapsed = [sample[0] for sample in samples]
        results['five_concurrent_no_total'] = {'samples': len(elapsed), 'concurrency': 5, 'failed': 0,
            'p50_ms': percentile(elapsed, 0.5), 'p95_ms': percentile(elapsed, 0.95), 'max_ms': round(max(elapsed), 2)}
        groups = await client.get('/rpa/v1/product-groups', headers={'Authorization': 'Bearer isolated-rpa-token'})
        unauth = await client.get('/rpa/v1/product-groups', headers={'Authorization': ''})
        uu = await client.get('/rpa/v1/products/3800000000000000001/uu', headers={'Authorization': 'Bearer isolated-rpa-token'})
        assert groups.status_code == 200 and unauth.status_code == 401 and uu.status_code == 200
        assert uu.json()['goodsInfo']['productId'] == '3800000000000000001'
        return results


try:
    measurements = asyncio.run(measure())
finally:
    server.terminate()
    try:
        server.wait(timeout=10)
    except subprocess.TimeoutExpired:
        server.kill()
        server.wait()

report = {'environment': 'GitHub Actions isolated PostgreSQL, synthetic data, warm cache, loopback HTTP',
          'postgresql': pg_version, 'counts': counts, 'setup_seconds': setup_seconds,
          'product_edit_enabled': EDIT_DRAFTS, 'synthetic_drafts': 30000 if EDIT_DRAFTS else 0,
          'notes': 'HTTP API only; no frontend render, image download, real NAS or production data.', 'cases': measurements,
          'rpa_readonly_auth_and_uu': 'pass'}
destination = ROOT / 'benchmark-results.json'
destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=2))
