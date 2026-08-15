from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
from psycopg2.extras import RealDictCursor
import os
import uuid

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "sliqchat-development-secret-change-this")

DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("password")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}


def get_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL fehlt. Bitte die Render-PostgreSQL-URL als Environment Variable setzen.")
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def init_db():
    db = get_db()
    cur = db.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id SERIAL PRIMARY KEY,
            name TEXT,
            is_group INTEGER DEFAULT 0,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS conversation_members (
            conversation_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            UNIQUE(conversation_id, user_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY,
            conversation_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            text TEXT,
            image TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    db.commit()
    cur.close()
    db.close()


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def current_user():
    if "user_id" not in session:
        return None

    db = get_db()
    cur = db.cursor()

    cur.execute(
        "SELECT * FROM users WHERE id = %s",
        (session["user_id"],)
    )

    user = cur.fetchone()

    cur.close()
    db.close()

    return user


@app.route("/service-worker.js")
def service_worker():
    return send_from_directory(
        os.path.join(BASE_DIR, "static"),
        "service-worker.js",
        mimetype="application/javascript"
    )


@app.route("/manifest.json")
def manifest():
    return send_from_directory(
        os.path.join(BASE_DIR, "static"),
        "manifest.json",
        mimetype="application/manifest+json"
    )


@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


@app.route("/")
def index():
    if not current_user():
        return redirect(url_for("login"))
    return render_template("index.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("index"))

    error = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        db = get_db()
        cur = db.cursor()

        cur.execute(
            "SELECT * FROM users WHERE username = %s",
            (username,)
        )

        user = cur.fetchone()

        cur.close()
        db.close()

        if user and check_password_hash(user["password"], password):
            session.clear()
            session["user_id"] = user["id"]
            return redirect(url_for("index"))

        error = "Benutzername oder Passwort ist falsch."

    return render_template("login.html", error=error)


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user():
        return redirect(url_for("index"))

    error = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")

        if len(username) < 3:
            error = "Der Benutzername muss mindestens 3 Zeichen haben."

        elif len(username) > 24:
            error = "Der Benutzername darf maximal 24 Zeichen haben."

        elif not username.replace("_", "").isalnum():
            error = "Nur Buchstaben, Zahlen und _ sind erlaubt."

        elif len(password) < 8:
            error = "Das Passwort muss mindestens 8 Zeichen haben."

        elif password != password2:
            error = "Die Passwoerter stimmen nicht ueberein."

        else:
            db = get_db()
            cur = db.cursor()

            cur.execute(
                "SELECT id FROM users WHERE username = %s",
                (username,)
            )

            existing = cur.fetchone()

            if existing:
                error = "Dieser Benutzername ist bereits vergeben."
                cur.close()
                db.close()

            else:
                password_hash = generate_password_hash(password)

                cur.execute(
                    """
                    INSERT INTO users (username, password)
                    VALUES (%s, %s)
                    RETURNING id
                    """,
                    (username, password_hash)
                )

                user_id = cur.fetchone()["id"]

                db.commit()
                cur.close()
                db.close()

                session.clear()
                session["user_id"] = user_id

                return redirect(url_for("index"))

    return render_template("register.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/api/me")
def api_me():
    user = current_user()

    if not user:
        return jsonify({"error": "not_logged_in"}), 401

    return jsonify({
        "id": user["id"],
        "username": user["username"]
    })


@app.route("/api/users")
def users():
    user = current_user()

    if not user:
        return jsonify({"error": "not_logged_in"}), 401

    search = request.args.get("search", "").strip()

    db = get_db()
    cur = db.cursor()

    cur.execute(
        """
        SELECT id, username
        FROM users
        WHERE id != %s
        AND username ILIKE %s
        ORDER BY username
        LIMIT 30
        """,
        (user["id"], "%" + search + "%")
    )

    rows = cur.fetchall()

    cur.close()
    db.close()

    return jsonify(rows)


@app.route("/api/conversations")
def conversations():
    user = current_user()

    if not user:
        return jsonify({"error": "not_logged_in"}), 401

    db = get_db()
    cur = db.cursor()

    cur.execute(
        """
        SELECT
            c.id,
            c.name,
            c.is_group,
            (
                SELECT text
                FROM messages m
                WHERE m.conversation_id = c.id
                ORDER BY m.id DESC
                LIMIT 1
            ) AS last_message,
            (
                SELECT image
                FROM messages m
                WHERE m.conversation_id = c.id
                ORDER BY m.id DESC
                LIMIT 1
            ) AS last_image
        FROM conversations c
        JOIN conversation_members cm
            ON cm.conversation_id = c.id
        WHERE cm.user_id = %s
        ORDER BY c.id DESC
        """,
        (user["id"],)
    )

    rows = cur.fetchall()
    result = []

    for row in rows:
        title = row["name"]

        if not row["is_group"]:
            cur.execute(
                """
                SELECT u.username
                FROM users u
                JOIN conversation_members cm
                    ON cm.user_id = u.id
                WHERE cm.conversation_id = %s
                AND u.id != %s
                LIMIT 1
                """,
                (row["id"], user["id"])
            )

            other = cur.fetchone()

            if other:
                title = other["username"]

        result.append({
            "id": row["id"],
            "name": title or "Gruppe",
            "is_group": bool(row["is_group"]),
            "last_message": row["last_message"],
            "last_image": row["last_image"]
        })

    cur.close()
    db.close()

    return jsonify(result)


@app.route("/api/conversations/private", methods=["POST"])
def create_private():
    user = current_user()

    if not user:
        return jsonify({"error": "not_logged_in"}), 401

    data = request.get_json() or {}
    other_id = data.get("user_id")

    try:
        other_id = int(other_id)
    except:
        return jsonify({"error": "invalid_user"}), 400

    if other_id == user["id"]:
        return jsonify({"error": "cannot_chat_with_self"}), 400

    db = get_db()
    cur = db.cursor()

    cur.execute(
        "SELECT id FROM users WHERE id = %s",
        (other_id,)
    )

    if not cur.fetchone():
        cur.close()
        db.close()
        return jsonify({"error": "user_not_found"}), 404

    cur.execute(
        """
        SELECT c.id
        FROM conversations c
        JOIN conversation_members a
            ON a.conversation_id = c.id
        JOIN conversation_members b
            ON b.conversation_id = c.id
        WHERE c.is_group = 0
        AND a.user_id = %s
        AND b.user_id = %s
        LIMIT 1
        """,
        (user["id"], other_id)
    )

    existing = cur.fetchone()

    if existing:
        conversation_id = existing["id"]

    else:
        cur.execute(
            """
            INSERT INTO conversations
            (name, is_group, created_by)
            VALUES (%s, 0, %s)
            RETURNING id
            """,
            ("Private Chat", user["id"])
        )

        conversation_id = cur.fetchone()["id"]

        cur.execute(
            """
            INSERT INTO conversation_members
            (conversation_id, user_id)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
            """,
            (conversation_id, user["id"])
        )

        cur.execute(
            """
            INSERT INTO conversation_members
            (conversation_id, user_id)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
            """,
            (conversation_id, other_id)
        )

        db.commit()

    cur.close()
    db.close()

    return jsonify({"id": conversation_id})


@app.route("/api/groups", methods=["POST"])
def create_group():
    user = current_user()

    if not user:
        return jsonify({"error": "not_logged_in"}), 401

    data = request.get_json() or {}

    name = str(data.get("name", "")).strip()
    member_ids = data.get("members", [])

    if not name:
        return jsonify({"error": "group_name_required"}), 400

    if len(name) > 50:
        return jsonify({"error": "group_name_too_long"}), 400

    if not isinstance(member_ids, list):
        member_ids = []

    cleaned = []

    for member_id in member_ids:
        try:
            member_id = int(member_id)

            if member_id != user["id"] and member_id not in cleaned:
                cleaned.append(member_id)

        except:
            pass

    db = get_db()
    cur = db.cursor()

    cur.execute(
        """
        INSERT INTO conversations
        (name, is_group, created_by)
        VALUES (%s, 1, %s)
        RETURNING id
        """,
        (name, user["id"])
    )

    conversation_id = cur.fetchone()["id"]

    cur.execute(
        """
        INSERT INTO conversation_members
        (conversation_id, user_id)
        VALUES (%s, %s)
        ON CONFLICT DO NOTHING
        """,
        (conversation_id, user["id"])
    )

    for member_id in cleaned:
        cur.execute(
            "SELECT id FROM users WHERE id = %s",
            (member_id,)
        )

        if cur.fetchone():
            cur.execute(
                """
                INSERT INTO conversation_members
                (conversation_id, user_id)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
                """,
                (conversation_id, member_id)
            )

    db.commit()
    cur.close()
    db.close()

    return jsonify({"id": conversation_id})


@app.route("/api/conversations/<int:conversation_id>/messages")
def get_messages(conversation_id):
    user = current_user()

    if not user:
        return jsonify({"error": "not_logged_in"}), 401

    db = get_db()
    cur = db.cursor()

    cur.execute(
        """
        SELECT 1
        FROM conversation_members
        WHERE conversation_id = %s
        AND user_id = %s
        """,
        (conversation_id, user["id"])
    )

    if not cur.fetchone():
        cur.close()
        db.close()
        return jsonify({"error": "forbidden"}), 403

    cur.execute(
        """
        SELECT
            m.id,
            m.text,
            m.image,
            m.created_at,
            u.username,
            m.user_id
        FROM messages m
        JOIN users u
            ON u.id = m.user_id
        WHERE m.conversation_id = %s
        ORDER BY m.id ASC
        LIMIT 200
        """,
        (conversation_id,)
    )

    rows = cur.fetchall()

    cur.close()
    db.close()

    return jsonify([
        {
            "id": row["id"],
            "text": row["text"],
            "image": row["image"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "username": row["username"],
            "own": row["user_id"] == user["id"]
        }
        for row in rows
    ])


@app.route("/api/conversations/<int:conversation_id>/messages", methods=["POST"])
def send_message(conversation_id):
    user = current_user()

    if not user:
        return jsonify({"error": "not_logged_in"}), 401

    db = get_db()
    cur = db.cursor()

    cur.execute(
        """
        SELECT 1
        FROM conversation_members
        WHERE conversation_id = %s
        AND user_id = %s
        """,
        (conversation_id, user["id"])
    )

    if not cur.fetchone():
        cur.close()
        db.close()
        return jsonify({"error": "forbidden"}), 403

    text = request.form.get("text", "").strip()
    image_url = None

    image = request.files.get("image")

    if image and image.filename:
        if not allowed_file(image.filename):
            cur.close()
            db.close()
            return jsonify({"error": "unsupported_image"}), 400

        extension = image.filename.rsplit(".", 1)[1].lower()
        safe_name = uuid.uuid4().hex + "." + extension

        image.save(os.path.join(UPLOAD_FOLDER, safe_name))

        image_url = "/static/uploads/" + safe_name

    if not text and not image_url:
        cur.close()
        db.close()
        return jsonify({"error": "empty_message"}), 400

    cur.execute(
        """
        INSERT INTO messages
        (conversation_id, user_id, text, image)
        VALUES (%s, %s, %s, %s)
        """,
        (conversation_id, user["id"], text or None, image_url)
    )

    db.commit()
    cur.close()
    db.close()

    return jsonify({"success": True})


init_db()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000))
    )
