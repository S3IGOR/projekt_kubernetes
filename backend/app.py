import os
import time
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, jsonify, request, abort

app = Flask(__name__)

DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "postgres"),
    "port": int(os.environ.get("DB_PORT", 5432)),
    "dbname": os.environ.get("DB_NAME", "todos"),
    "user": os.environ.get("DB_USER", "postgres"),
    "password": os.environ.get("DB_PASSWORD", ""),
}


def get_conn():
    return psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)


def init_db():
    for attempt in range(10):
        try:
            conn = get_conn()
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS todos (
                        id SERIAL PRIMARY KEY,
                        title TEXT NOT NULL,
                        done BOOLEAN NOT NULL DEFAULT FALSE,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)
            conn.commit()
            conn.close()
            return
        except Exception as e:
            print(f"DB not ready (attempt {attempt+1}/10): {e}", flush=True)
            time.sleep(3)
    raise RuntimeError("Could not connect to database after 10 attempts")


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@app.route("/readyz")
def readyz():
    try:
        conn = get_conn()
        conn.close()
        return jsonify({"status": "ready"})
    except Exception as e:
        return jsonify({"status": "not ready", "error": str(e)}), 503


@app.route("/api/todos", methods=["GET"])
def list_todos():
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM todos ORDER BY created_at DESC")
        rows = cur.fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/todos", methods=["POST"])
def create_todo():
    data = request.get_json(silent=True) or {}
    title = data.get("title", "").strip()
    if not title:
        abort(400, "title required")
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO todos (title) VALUES (%s) RETURNING *", (title,)
        )
        row = cur.fetchone()
    conn.commit()
    conn.close()
    return jsonify(dict(row)), 201


@app.route("/api/todos/<int:todo_id>", methods=["PATCH"])
def update_todo(todo_id):
    data = request.get_json(silent=True) or {}
    done = data.get("done")
    if done is None:
        abort(400, "done required")
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE todos SET done=%s WHERE id=%s RETURNING *", (done, todo_id)
        )
        row = cur.fetchone()
    conn.commit()
    conn.close()
    if row is None:
        abort(404)
    return jsonify(dict(row))


@app.route("/api/todos/<int:todo_id>", methods=["DELETE"])
def delete_todo(todo_id):
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM todos WHERE id=%s RETURNING id", (todo_id,))
        row = cur.fetchone()
    conn.commit()
    conn.close()
    if row is None:
        abort(404)
    return "", 204


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=8080)
