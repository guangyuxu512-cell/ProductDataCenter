"""Claim and finish automatic checks without modifying product packages."""
from copy import deepcopy
import json
from sqlalchemy import Engine, text


def present_result(result):
    """Hide obsolete app-generated rule hints without claiming validation passed."""
    if not isinstance(result, dict):
        return result
    value = deepcopy(result)
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

    def enqueue(self, product_ids: list[str]) -> list[dict]:
        """Queue saved packages through the collector-owned durable queue.

        Bumping the queue revision also invalidates an in-flight claim.  Its
        eventual completion update is then rejected by ``complete`` instead
        of replacing the result requested by the user most recently.
        """
        if not product_ids:
            return []
        with self.engine.begin() as conn:
            rows = conn.execute(text("""INSERT INTO product_prechecks (product_id)
                SELECT product_id FROM products
                WHERE product_id=ANY(CAST(:ids AS text[])) AND uu_json IS NOT NULL
                ON CONFLICT (product_id) DO UPDATE SET
                  revision=product_prechecks.revision+1, state='pending', attempts=0,
                  available_at=now(), lease_until=NULL, result=NULL, last_error=NULL, updated_at=now()
                RETURNING product_id, revision, state, updated_at"""),
                {"ids": product_ids}).mappings().all()
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

    def results(self, product_ids: list[str]) -> list[dict]:
        if not product_ids:
            return []
        with self.engine.connect() as conn:
            rows = conn.execute(text("""SELECT product_id, revision, state, result, last_error, updated_at
                FROM product_prechecks WHERE product_id=ANY(CAST(:ids AS text[]))"""),
                {"ids": product_ids}).mappings().all()
        return [{"productId": row["product_id"], "revision": row["revision"],
                 "state": row["state"], "result": present_result(row["result"]),
                 "error": row["last_error"], "updatedAt": row["updated_at"]} for row in rows]
