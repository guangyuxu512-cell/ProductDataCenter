"""Claim and finish automatic checks without modifying product packages."""
from copy import deepcopy
import json
from sqlalchemy import Engine, text
from app.modules.products.queries import group_scope_sql


_WAITING_WORKER_RESULT = "worker_result_pending"
SESSION_READ_INCOMPLETE_MESSAGE = "读取本机店铺会话未完成"


def present_result(result):
    """Hide obsolete app-generated rule hints without claiming validation passed."""
    if not isinstance(result, dict):
        return result
    value = deepcopy(result)
    value.pop("_worker_receipt", None)
    issues = value.get("issues")
    details = value.get("issueDetails")
    def obsolete(message):
        return isinstance(message, str) and message.endswith("规则待核对")
    filtered_issues = [message for message in issues if not obsolete(message)] if isinstance(issues, list) else issues
    filtered_details = [item for item in details if not (isinstance(item, dict) and obsolete(item.get("message")))] \
        if isinstance(details, list) else details
    if filtered_issues != issues or filtered_details != details:
        value["issues"] = filtered_issues if isinstance(filtered_issues, list) else []
        if isinstance(filtered_details, list):
            value["issueDetails"] = filtered_details
        value["status"] = "failed"
    if value.get("status") == "failed" and isinstance(value.get("issues"), list):
        value["issues"] = [SESSION_READ_INCOMPLETE_MESSAGE if issue == "本机店铺登录状态不可用" else issue
                           for issue in value["issues"]]
    return value


class PrecheckQueue:
    def __init__(self, engine: Engine):
        self.engine = engine

    def claim(self, limit: int) -> list[dict]:
        with self.engine.begin() as conn:
            rows = conn.execute(text("""WITH next AS (
                SELECT product_id FROM product_prechecks
                WHERE (state='pending' AND available_at <= now())
                   OR (state='running' AND lease_until < now())
                ORDER BY available_at, product_id FOR UPDATE SKIP LOCKED LIMIT :limit
              ) UPDATE product_prechecks q SET state='running', attempts=q.attempts+1,
                lease_until=now()+interval '3 minutes', updated_at=now()
                FROM next WHERE q.product_id=next.product_id
                RETURNING q.product_id, q.revision, q.attempts"""), {"limit": limit}).mappings().all()
        return [dict(row) for row in rows]

    def enqueue(self, product_ids: list[str], allowed_groups=None) -> list[dict]:
        """Queue saved packages through the collector-owned durable queue.

        Bumping the queue revision also invalidates an in-flight claim.  Its
        eventual completion update is then rejected by ``complete`` instead
        of replacing the result requested by the user most recently.
        """
        if not product_ids:
            return []
        with self.engine.begin() as conn:
            scope, params = group_scope_sql(allowed_groups)
            permitted = ("WITH permitted AS (SELECT product_id FROM products WHERE product_id=ANY(CAST(:ids AS text[])) "
                         "AND uu_json IS NOT NULL" + scope + " FOR SHARE) "
                         "INSERT INTO product_prechecks (product_id) SELECT product_id FROM permitted"
                         if allowed_groups is not None else
                         "INSERT INTO product_prechecks (product_id) SELECT product_id FROM products "
                         "WHERE product_id=ANY(CAST(:ids AS text[])) AND uu_json IS NOT NULL")
            rows = conn.execute(text(permitted + """
                ON CONFLICT (product_id) DO UPDATE SET
                  revision=product_prechecks.revision+1, state='pending', attempts=0,
                  available_at=now(), lease_until=NULL, result=NULL, last_error=NULL, updated_at=now()
                RETURNING product_id, revision, state, updated_at"""),
                {"ids": product_ids, **params}).mappings().all()
        return [{"productId": row["product_id"], "revision": row["revision"],
                 "state": row["state"], "result": None, "error": None,
                 "updatedAt": row["updated_at"]} for row in rows]

    def complete(self, claim: dict, result: dict) -> bool:
        with self.engine.begin() as conn:
            done = conn.execute(text("""UPDATE product_prechecks SET state='done', result=CAST(:result AS jsonb),
                lease_until=NULL, last_error=NULL, updated_at=now()
                WHERE product_id=:product_id AND revision=:revision AND attempts=:attempts AND state='running'"""),
                {**claim, "result": json.dumps(result, ensure_ascii=False)}).rowcount
        return bool(done)

    def wait_for_worker(self, claim: dict) -> bool:
        """Wait for a pushed result; reclaim only if it has not arrived."""
        with self.engine.begin() as conn:
            changed = conn.execute(text("""UPDATE product_prechecks SET state='running',
                lease_until=now()+interval '3 minutes', last_error=:waiting, updated_at=now()
                WHERE product_id=:product_id AND revision=:revision AND attempts=:attempts AND state='running'"""),
                {**claim, "waiting": _WAITING_WORKER_RESULT}).rowcount
        return bool(changed)

    def claim_worker_result(self, product_id: str, revision: int, receipt: dict) -> tuple[str, dict | None]:
        """Fence stale or duplicate Worker deliveries using the existing queue row."""
        with self.engine.begin() as conn:
            row = conn.execute(text("""SELECT revision, state, result FROM product_prechecks
                WHERE product_id=:product_id FOR UPDATE"""), {"product_id": product_id}).mappings().first()
            if row is None or row["revision"] != revision:
                return "stale", None
            if row["state"] == "done":
                current = row["result"] if isinstance(row["result"], dict) else {}
                return ("duplicate" if current.get("_worker_receipt") == receipt else "conflict"), None
            if row["state"] not in ("pending", "running"):
                return "conflict", None
            claim = conn.execute(text("""UPDATE product_prechecks SET state='running', attempts=attempts+1,
                lease_until=now()+interval '3 minutes', last_error=:waiting, updated_at=now()
                WHERE product_id=:product_id AND revision=:revision
                RETURNING product_id, revision, attempts"""),
                {"product_id": product_id, "revision": revision, "waiting": _WAITING_WORKER_RESULT}).mappings().one()
        return "claimed", dict(claim)

    def defer_worker(self, claim: dict, *, running: bool = False, waiting_result: bool = False) -> bool:
        """Release a claim while awaiting its idempotently keyed central task."""
        if waiting_result and not running:
            raise ValueError("A pending Worker result must remain running")
        with self.engine.begin() as conn:
            updated = conn.execute(text("""UPDATE product_prechecks SET
                state=CASE WHEN :running THEN 'running' ELSE 'pending' END,
                available_at=now()+(:delay * interval '1 second'),
                lease_until=CASE WHEN :running THEN now()+(:delay * interval '1 second') ELSE NULL END, result=NULL,
                last_error=:waiting, updated_at=now()
                WHERE product_id=:product_id AND revision=:revision AND attempts=:attempts
                  AND state='running'"""), {**claim, "running": running, "delay": 30 if waiting_result else 5,
                                             "waiting": _WAITING_WORKER_RESULT if waiting_result else None}).rowcount
        return bool(updated)

    def retry(self, claim: dict) -> None:
        # Keep platform/session errors out of logs and persisted data. Attempts are
        # retried with backoff so a temporarily unavailable shop does not lose a package.
        delay = min(1800, 30 * (2 ** min(claim["attempts"] - 1, 6)))
        with self.engine.begin() as conn:
            conn.execute(text("""UPDATE product_prechecks SET state='pending', result=NULL,
                available_at=now()+(:delay * interval '1 second'), lease_until=NULL,
                last_error='预检暂不可用，将自动重试', updated_at=now()
                WHERE product_id=:product_id AND revision=:revision AND attempts=:attempts AND state='running'"""),
                {**claim, "delay": delay})

    def results(self, product_ids: list[str], allowed_groups=None) -> list[dict]:
        if not product_ids:
            return []
        with self.engine.connect() as conn:
            scope, params = group_scope_sql(allowed_groups, "p")
            statement = ("""SELECT q.product_id, q.revision, q.state, q.result, q.last_error, q.updated_at
                FROM product_prechecks q JOIN products p ON p.product_id=q.product_id
                WHERE q.product_id=ANY(CAST(:ids AS text[]))""" + scope if allowed_groups is not None else
                """SELECT product_id, revision, state, result, last_error, updated_at FROM product_prechecks
                   WHERE product_id=ANY(CAST(:ids AS text[]))""")
            rows = conn.execute(text(statement),
                {"ids": product_ids, **params}).mappings().all()
        records = []
        for row in rows:
            waiting = row["state"] == "running" and row["last_error"] == _WAITING_WORKER_RESULT
            record = {"productId": row["product_id"], "revision": row["revision"],
                      "state": row["state"], "result": present_result(row["result"]),
                      "error": None if waiting else row["last_error"], "updatedAt": row["updated_at"]}
            if waiting:
                record["waitingForWorker"] = True
            records.append(record)
        return records
