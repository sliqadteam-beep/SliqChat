import os
import sqlite3
import uuid

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    abort,
    send_from_directory
)

from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename


app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "CHANGE-THIS-SECRET-KEY"
)

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

if os.environ.get("RENDER"):
    app.config["SESSION_COOKIE_SECURE"] = True


DATABASE = "sliqchat.db"

UPLOAD_FOLDER = "uploads"

ALLOWED_EXTENSIONS = {
    "png",
    "jpg",
    "jpeg",
    "gif",
    "webp"
}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def get_db():

    db = sqlite3.connect(DATABASE)

    db.row_factory = sqlite3.Row

    return db


def init_database():

    db = get_db()

    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS friend_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS friendships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user1_id INTEGER NOT NULL,
            user2_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user1_id, user2_id)
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS private_chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user1_id INTEGER NOT NULL,
            user2_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user1_id, user2_id)
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            owner_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS group_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            UNIQUE(group_id, user_id)
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_type TEXT NOT NULL,
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            message TEXT,
            image_filename TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    db.commit()

    db.close()


init_database()


def current_user():

    user_id = session.get("user_id")

    if not user_id:
        return None

    db = get_db()

    user = db.execute(
        "SELECT * FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()

    db.close()

    return user


def allowed_file(filename):

    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower()
        in ALLOWED_EXTENSIONS
    )


def are_friends(db, user1, user2):

    a = min(user1, user2)
    b = max(user1, user2)

    friendship = db.execute("""
        SELECT id
        FROM friendships
        WHERE user1_id = ?
        AND user2_id = ?
    """, (a, b)).fetchone()

    return friendship is not None


@app.route("/")
def home():

    user = current_user()

    if not user:
        return redirect(url_for("login"))

    db = get_db()

    friends = db.execute("""
        SELECT users.id, users.username
        FROM friendships
        JOIN users
        ON users.id =
            CASE
                WHEN friendships.user1_id = ?
                THEN friendships.user2_id
                ELSE friendships.user1_id
            END
        WHERE friendships.user1_id = ?
        OR friendships.user2_id = ?
        ORDER BY users.username
    """, (
        user["id"],
        user["id"],
        user["id"]
    )).fetchall()

    requests = db.execute("""
        SELECT
            friend_requests.id,
            users.username
        FROM friend_requests
        JOIN users
        ON users.id = friend_requests.sender_id
        WHERE friend_requests.receiver_id = ?
        AND friend_requests.status = 'pending'
        ORDER BY friend_requests.id DESC
    """, (user["id"],)).fetchall()

    groups = db.execute("""
        SELECT groups.id, groups.name
        FROM groups
        JOIN group_members
        ON group_members.group_id = groups.id
        WHERE group_members.user_id = ?
        ORDER BY groups.name
    """, (user["id"],)).fetchall()

    db.close()

    return render_template(
        "index.html",
        user=user,
        friends=friends,
        requests=requests,
        groups=groups,
        active_chat=None,
        messages=[]
    )


@app.route("/register", methods=["GET", "POST"])
def register():

    if current_user():
        return redirect(url_for("home"))

    if request.method == "POST":

        username = request.form.get(
            "username",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        if len(username) < 3 or len(username) > 20:

            return render_template(
                "register.html",
                error="Benutzername muss 3–20 Zeichen lang sein."
            )

        if not username.replace("_", "").isalnum():

            return render_template(
                "register.html",
                error="Nur Buchstaben, Zahlen und _ sind erlaubt."
            )

        if len(password) < 8:

            return render_template(
                "register.html",
                error="Passwort muss mindestens 8 Zeichen haben."
            )

        password_hash = generate_password_hash(
            password,
            method="scrypt"
        )

        db = get_db()

        try:

            cursor = db.execute("""
                INSERT INTO users
                (username, password_hash)
                VALUES (?, ?)
            """, (
                username,
                password_hash
            ))

            db.commit()

            user_id = cursor.lastrowid

            db.close()

            session.clear()

            session["user_id"] = user_id

            return redirect(url_for("home"))

        except sqlite3.IntegrityError:

            db.close()

            return render_template(
                "register.html",
                error="Dieser Benutzername existiert bereits."
            )

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():

    if current_user():
        return redirect(url_for("home"))

    if request.method == "POST":

        username = request.form.get(
            "username",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        db = get_db()

        user = db.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,)
        ).fetchone()

        db.close()

        if not user or not check_password_hash(
            user["password_hash"],
            password
        ):

            return render_template(
                "login.html",
                error="Benutzername oder Passwort falsch."
            )

        session.clear()

        session["user_id"] = user["id"]

        return redirect(url_for("home"))

    return render_template("login.html")


@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("login"))


@app.route("/add_friend", methods=["POST"])
def add_friend():

    user = current_user()

    if not user:
        return redirect(url_for("login"))

    username = request.form.get(
        "username",
        ""
    ).strip()

    db = get_db()

    target = db.execute(
        "SELECT * FROM users WHERE username = ?",
        (username,)
    ).fetchone()

    if not target:

        db.close()

        return redirect(
            url_for(
                "home",
                error="notfound"
            )
        )

    if target["id"] == user["id"]:

        db.close()

        return redirect(
            url_for(
                "home",
                error="self"
            )
        )

    if are_friends(
        db,
        user["id"],
        target["id"]
    ):

        db.close()

        return redirect(url_for("home"))

    existing = db.execute("""
        SELECT id
        FROM friend_requests
        WHERE sender_id = ?
        AND receiver_id = ?
        AND status = 'pending'
    """, (
        user["id"],
        target["id"]
    )).fetchone()

    reverse = db.execute("""
        SELECT id
        FROM friend_requests
        WHERE sender_id = ?
        AND receiver_id = ?
        AND status = 'pending'
    """, (
        target["id"],
        user["id"]
    )).fetchone()

    if not existing and not reverse:

        db.execute("""
            INSERT INTO friend_requests
            (sender_id, receiver_id)
            VALUES (?, ?)
        """, (
            user["id"],
            target["id"]
        ))

        db.commit()

    db.close()

    return redirect(url_for("home"))


@app.route("/accept_friend/<int:request_id>")
def accept_friend(request_id):

    user = current_user()

    if not user:
        return redirect(url_for("login"))

    db = get_db()

    friend_request = db.execute("""
        SELECT *
        FROM friend_requests
        WHERE id = ?
        AND receiver_id = ?
        AND status = 'pending'
    """, (
        request_id,
        user["id"]
    )).fetchone()

    if friend_request:

        user1 = min(
            friend_request["sender_id"],
            friend_request["receiver_id"]
        )

        user2 = max(
            friend_request["sender_id"],
            friend_request["receiver_id"]
        )

        db.execute("""
            UPDATE friend_requests
            SET status = 'accepted'
            WHERE id = ?
        """, (request_id,))

        db.execute("""
            INSERT OR IGNORE INTO friendships
            (user1_id, user2_id)
            VALUES (?, ?)
        """, (
            user1,
            user2
        ))

        db.commit()

    db.close()

    return redirect(url_for("home"))


@app.route("/decline_friend/<int:request_id>")
def decline_friend(request_id):

    user = current_user()

    if not user:
        return redirect(url_for("login"))

    db = get_db()

    db.execute("""
        UPDATE friend_requests
        SET status = 'declined'
        WHERE id = ?
        AND receiver_id = ?
        AND status = 'pending'
    """, (
        request_id,
        user["id"]
    ))

    db.commit()

    db.close()

    return redirect(url_for("home"))


@app.route("/chat/<int:friend_id>")
def private_chat(friend_id):

    user = current_user()

    if not user:
        return redirect(url_for("login"))

    db = get_db()

    friend = db.execute(
        "SELECT * FROM users WHERE id = ?",
        (friend_id,)
    ).fetchone()

    if not friend:

        db.close()

        abort(404)

    if not are_friends(
        db,
        user["id"],
        friend_id
    ):

        db.close()

        abort(403)

    user1 = min(
        user["id"],
        friend_id
    )

    user2 = max(
        user["id"],
        friend_id
    )

    chat = db.execute("""
        SELECT *
        FROM private_chats
        WHERE user1_id = ?
        AND user2_id = ?
    """, (
        user1,
        user2
    )).fetchone()

    if not chat:

        cursor = db.execute("""
            INSERT INTO private_chats
            (user1_id, user2_id)
            VALUES (?, ?)
        """, (
            user1,
            user2
        ))

        db.commit()

        chat_id = cursor.lastrowid

    else:

        chat_id = chat["id"]

    messages = db.execute("""
        SELECT
            messages.*,
            users.username
        FROM messages
        JOIN users
        ON users.id = messages.user_id
        WHERE messages.chat_type = 'private'
        AND messages.chat_id = ?
        ORDER BY messages.id ASC
    """, (chat_id,)).fetchall()

    friends = db.execute("""
        SELECT users.id, users.username
        FROM friendships
        JOIN users
        ON users.id =
            CASE
                WHEN friendships.user1_id = ?
                THEN friendships.user2_id
                ELSE friendships.user1_id
            END
        WHERE friendships.user1_id = ?
        OR friendships.user2_id = ?
        ORDER BY users.username
    """, (
        user["id"],
        user["id"],
        user["id"]
    )).fetchall()

    groups = db.execute("""
        SELECT groups.id, groups.name
        FROM groups
        JOIN group_members
        ON group_members.group_id = groups.id
        WHERE group_members.user_id = ?
    """, (user["id"],)).fetchall()

    requests = db.execute("""
        SELECT
            friend_requests.id,
            users.username
        FROM friend_requests
        JOIN users
        ON users.id = friend_requests.sender_id
        WHERE friend_requests.receiver_id = ?
        AND friend_requests.status = 'pending'
    """, (user["id"],)).fetchall()

    db.close()

    return render_template(
        "index.html",
        user=user,
        friends=friends,
        groups=groups,
        requests=requests,
        active_chat={
            "type": "private",
            "id": chat_id,
            "name": friend["username"]
        },
        messages=messages
    )


@app.route("/group/create", methods=["POST"])
def create_group():

    user = current_user()

    if not user:
        return redirect(url_for("login"))

    name = request.form.get(
        "name",
        ""
    ).strip()

    if not name or len(name) > 50:

        return redirect(url_for("home"))

    db = get_db()

    cursor = db.execute("""
        INSERT INTO groups
        (name, owner_id)
        VALUES (?, ?)
    """, (
        name,
        user["id"]
    ))

    group_id = cursor.lastrowid

    db.execute("""
        INSERT INTO group_members
        (group_id, user_id)
        VALUES (?, ?)
    """, (
        group_id,
        user["id"]
    ))

    db.commit()

    db.close()

    return redirect(
        url_for(
            "group_chat",
            group_id=group_id
        )
    )


@app.route("/group/<int:group_id>")
def group_chat(group_id):

    user = current_user()

    if not user:
        return redirect(url_for("login"))

    db = get_db()

    group = db.execute("""
        SELECT *
        FROM groups
        WHERE id = ?
    """, (group_id,)).fetchone()

    if not group:

        db.close()

        abort(404)

    member = db.execute("""
        SELECT id
        FROM group_members
        WHERE group_id = ?
        AND user_id = ?
    """, (
        group_id,
        user["id"]
    )).fetchone()

    if not member:

        db.close()

        abort(403)

    messages = db.execute("""
        SELECT
            messages.*,
            users.username
        FROM messages
        JOIN users
        ON users.id = messages.user_id
        WHERE messages.chat_type = 'group'
        AND messages.chat_id = ?
        ORDER BY messages.id ASC
    """, (group_id,)).fetchall()

    friends = db.execute("""
        SELECT users.id, users.username
        FROM friendships
        JOIN users
        ON users.id =
            CASE
                WHEN friendships.user1_id = ?
                THEN friendships.user2_id
                ELSE friendships.user1_id
            END
        WHERE friendships.user1_id = ?
        OR friendships.user2_id = ?
    """, (
        user["id"],
        user["id"],
        user["id"]
    )).fetchall()

    groups = db.execute("""
        SELECT groups.id, groups.name
        FROM groups
        JOIN group_members
        ON group_members.group_id = groups.id
        WHERE group_members.user_id = ?
    """, (user["id"],)).fetchall()

    requests = db.execute("""
        SELECT
            friend_requests.id,
            users.username
        FROM friend_requests
        JOIN users
        ON users.id = friend_requests.sender_id
        WHERE friend_requests.receiver_id = ?
        AND friend_requests.status = 'pending'
    """, (user["id"],)).fetchall()

    db.close()

    return render_template(
        "index.html",
        user=user,
        friends=friends,
        groups=groups,
        requests=requests,
        active_chat={
            "type": "group",
            "id": group_id,
            "name": group["name"]
        },
        messages=messages
    )


@app.route("/message/<chat_type>/<int:chat_id>", methods=["POST"])
def send_message(chat_type, chat_id):

    user = current_user()

    if not user:
        return redirect(url_for("login"))

    message = request.form.get(
        "message",
        ""
    ).strip()

    image = request.files.get("image")

    if not message and not image:
        return redirect(url_for("home"))

    db = get_db()

    valid = False

    if chat_type == "private":

        chat = db.execute("""
            SELECT *
            FROM private_chats
            WHERE id = ?
            AND (user1_id = ? OR user2_id = ?)
        """, (
            chat_id,
            user["id"],
            user["id"]
        )).fetchone()

        valid = chat is not None

    elif chat_type == "group":

        member = db.execute("""
            SELECT id
            FROM group_members
            WHERE group_id = ?
            AND user_id = ?
        """, (
            chat_id,
            user["id"]
        )).fetchone()

        valid = member is not None

    if not valid:

        db.close()

        abort(403)

    image_filename = None

    if image and image.filename:

        if not allowed_file(image.filename):

            db.close()

            abort(400)

        original = secure_filename(
            image.filename
        )

        extension = original.rsplit(
            ".",
            1
        )[1].lower()

        image_filename = (
            str(uuid.uuid4())
            + "."
            + extension
        )

        image.save(
            os.path.join(
                app.config["UPLOAD_FOLDER"],
                image_filename
            )
        )

    if len(message) > 2000:

        db.close()

        abort(400)

    db.execute("""
        INSERT INTO messages
        (
            chat_type,
            chat_id,
            user_id,
            message,
            image_filename
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        chat_type,
        chat_id,
        user["id"],
        message,
        image_filename
    ))

    db.commit()

    db.close()

    if chat_type == "private":

        return redirect(
            url_for(
                "private_chat",
                friend_id=(
                    chat["user2_id"]
                    if chat["user1_id"] == user["id"]
                    else chat["user1_id"]
                )
            )
        )

    return redirect(
        url_for(
            "group_chat",
            group_id=chat_id
        )
    )


@app.route("/uploads/<filename>")
def uploaded_file(filename):

    return send_from_directory(
        app.config["UPLOAD_FOLDER"],
        filename
    )


if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000
    )