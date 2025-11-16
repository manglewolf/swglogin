import logging
import os
import pathlib
import socket
from logging.handlers import RotatingFileHandler
from typing import Optional

import pymysql
from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
    Response,
    g,
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from markupsafe import escape
try:
    from zxcvbn import zxcvbn as zx_analyze
except Exception:
    zx_analyze = None

from includes.db_connect import cursor, get_connection
import time
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

app = Flask(__name__)
# Load secret key from environment for production; fallback to a generated token for dev.
app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY", "dev_secret_key_change_me_in_production"
)

# Configure logging
root = pathlib.Path(__file__).resolve().parent
logs_dir = root / "logs"
logs_dir.mkdir(parents=True, exist_ok=True)
logger = logging.getLogger("swglogin")

# Prometheus metrics definitions
REQUEST_LATENCY = Histogram(
    "swglogin_request_latency_seconds",
    "Request latency",
    ["method", "endpoint"],
)
REQUEST_COUNT = Counter(
    "swglogin_requests_total",
    "HTTP requests",
    ["method", "endpoint", "http_status"],
)
LOGIN_ATTEMPTS = Counter(
    "swglogin_login_attempts_total", "Login attempts", ["result"]
)
AUTH_ATTEMPTS = Counter(
    "swglogin_auth_attempts_total", "Auth attempts", ["result"]
)
REGISTRATION_ATTEMPTS = Counter(
    "swglogin_registration_attempts_total", "Registration attempts", ["result"]
)

# Configure rate limiter: default key is remote address (always create so `limiter` is bound)
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],  # we'll set per-route limits explicitly
    app=app,
    # Use in-memory storage by default for development and CI; set a production
    # storage backend (e.g. Redis) via configuration when deploying.
    storage_uri="memory://",
)

if not logger.handlers:
    handler = RotatingFileHandler(
        logs_dir / "auth.log", maxBytes=5 * 1024 * 1024, backupCount=3
    )
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


@app.before_request
def _start_timer():
    g._start_time = time.time()


@app.after_request
def _record_metrics(response: Response):
    try:
        duration = time.time() - getattr(g, "_start_time", time.time())
        endpoint = request.endpoint or "unknown"
        REQUEST_LATENCY.labels(request.method, endpoint).observe(duration)
        REQUEST_COUNT.labels(request.method, endpoint, response.status_code).inc()
    except Exception:
        # Never break the response due to metrics errors
        pass
    return response

@app.errorhandler(429)
def ratelimit_handler(e):
    # Return JSON for API posts and flash+redirect for form posts
    # If the request accepts JSON or is to /auth.php, return JSON
    try:
        if request.path == "/auth.php" or request.is_json:
            return (
                jsonify({"message": "Too many requests, please try again later."}),
                429,
            )
    except Exception:
        pass
    # Fallback: flash and redirect to login form
    try:
        flash("Too many requests. Please wait a minute and try again.", "error")
        return redirect(url_for("form_login"))
    except Exception:
        return jsonify({"message": "Too many requests"}), 429


def check_port(host: str, port: int, timeout: float = 5.0) -> bool:
    """Return True if TCP port is open on host, False otherwise."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def get_online_player_count() -> Optional[int]:
    """Connect to MySQL using includes.db_connect and return count of online players, or None on error."""
    try:
        with cursor() as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM `characters` WHERE `online`=1")
            row = cur.fetchone()
            return int(row["cnt"]) if row and "cnt" in row else 0
    except Exception:
        return None


@app.route("/")
@app.route("/index")
@app.route("/index.php")
def index():
    # Session username (mirrors PHP session_start + $_SESSION['user'])
    user = session.get("username")

    # Server/port checks (mirrors fsockopen checks in the PHP)
    # assumes game server and login server are on same host as mysql
    server = "192.168.204.15"
    ports = {
        "mysql": 3306,
        "game": 50001,
        "login": 44452,
    }
    statuses = {name: check_port(server, p, timeout=5) for name, p in ports.items()}

    # Database credentials are handled by includes.db_connect; just call the helper.
    online_players = get_online_player_count()

    # Log access to index with useful diagnostics (do not log sensitive data)
    try:
        logger.info('Index viewed by user=%s ip=%s statuses=%s online_players=%s',
                    user or '<anonymous>', request.remote_addr or '', statuses, online_players)
    except Exception:
        # Logging must not break the request on failure
        pass
    return render_template(
        "index.html", user=user, statuses=statuses, online_players=online_players
    )


@app.route("/addnewuser", methods=["GET"])
def add_new_user():
    # Render a form equivalent to the original PHP `addnewuser.php`
    return render_template("addnewuser.html")


@app.route("/newuserpost", methods=["POST"])
@limiter.limit("3 per 10 minutes")
def new_user_post():
    # Basic server-side validation mirroring the client-side JS
    useraccountname = request.form.get("useraccountname", "").strip()
    realpassword = request.form.get("realpassword", "")
    confirmpassword = request.form.get("confirmpassword", "")
    accesslevel = request.form.get("accesslevel", "standard")

    if not useraccountname:
        flash("Account name is required.", "error")
        return redirect(url_for("add_new_user"))

    if realpassword != confirmpassword:
        flash("Password fields must be the same.", "error")
        return redirect(url_for("add_new_user"))

    # Log the registration attempt (do not log the raw password)
    client_ip = request.remote_addr or ""
    logger.info(
        "Registration attempt: username=%s accesslevel=%s ip=%s",
        useraccountname,
        accesslevel,
        client_ip,
    )

    # Insert into database (use parametrized queries and PHP-compatible hashing)
    try:
        # Check for existing username
        with cursor() as cur:
            cur.execute(
                "SELECT 1 FROM user_account WHERE username = %s", (useraccountname,)
            )
            if cur.fetchone():
                logger.warning(
                    "Registration failed: username exists: %s ip=%s",
                    useraccountname,
                    client_ip,
                )
                REGISTRATION_ATTEMPTS.labels(result="exists").inc()
                flash("Account name already exists.", "error")
                return redirect(url_for("add_new_user"))

        encrypted, salt = hash_password_php_compat(realpassword)
        with cursor() as cur:
            sql = "INSERT INTO user_account (username, password_hash, password_salt, accesslevel) VALUES (%s, %s, %s, %s)"
            cur.execute(sql, (useraccountname, encrypted, salt, accesslevel))

        logger.info(
            "Registration success: username=%s ip=%s", useraccountname, client_ip
        )
        REGISTRATION_ATTEMPTS.labels(result="success").inc()
        flash("Account created successfully.", "success")
        return redirect(url_for("index"))
    except Exception as e:
        logger.exception("Database error during registration for username=%s ip=%s: %s", useraccountname, client_ip, e)
        REGISTRATION_ATTEMPTS.labels(result="error").inc()
        flash("Database error: an internal error occurred.", "error")
        return redirect(url_for("add_new_user"))


@app.route("/changepassword", methods=["GET"])
def change_password():
    # Require login
    if "username" not in session:
        # store redirect target and send to login (same behavior as PHP)
        session["urlredirect"] = "changepassword"
        return redirect(url_for("add_new_user"))

    # Fetch list of users from DB using centralized db helper
    try:
        with cursor() as cur:
            cur.execute("SELECT * FROM user_account ORDER BY user_id")
            users = cur.fetchall()
    except Exception:
        users = []

    return render_template("changepassword.html", users=users)


def hash_password_php_compat(password: str) -> tuple[str, str]:
    """Port of the PHP HashPassword function used in the original code.

    Returns (encrypted, salt) where encrypted is the base64-encoded sha1(password+salt)+salt.
    """
    import base64
    import hashlib
    import random

    salt = hashlib.sha1(str(random.random()).encode("utf-8")).hexdigest()[:10]
    sha = hashlib.sha1((password + salt).encode("utf-8")).digest()
    encrypted = base64.b64encode(sha + salt.encode("utf-8")).decode("utf-8")
    return encrypted, salt


def checkhashSSHA(salt: str, password: str) -> str:
    """Return the PHP-compatible SSHA hash for given salt and password."""
    import base64
    import hashlib

    sha = hashlib.sha1((password + salt).encode("utf-8")).digest()
    return base64.b64encode(sha + salt.encode("utf-8")).decode("utf-8")

# Authentication endpoint. Used by the game server to validate user credentials.
@app.route("/auth.php", methods=["POST"])
@app.route("/auth", methods=["POST"])
@limiter.limit("5 per minute")
def auth_php():
    # Accepts POST fields: user_name, user_password, ip, stationID
    username = request.form.get("user_name", "")
    password = request.form.get("user_password", "")
    ip = request.form.get("ip", "")
    station_id = request.form.get("stationID", "")

    # Log the attempt (without recording the raw password)
    logger.info(
        "Auth attempt for username=%s, stationID=%s, ip=%s", username, station_id, ip
    )

    try:
        with cursor() as cur:
            cur.execute("SELECT * FROM user_account WHERE username = %s", (username,))
            user = cur.fetchone()
    except Exception as e:
        logger.exception("Database error during auth for username=%s: %s", username, e)
        return jsonify({"message": "Internal server error"}), 500

    if not user:
        logger.warning("Auth failed: user not found: %s", username)
        AUTH_ATTEMPTS.labels(result="not_found").inc()
        return (
            jsonify({"message": "Account does not exist or password was incorrect"}),
            401,
        )

    if user.get("accesslevel") == "banned":
        logger.info("Auth rejected: banned account %s", username)
        AUTH_ATTEMPTS.labels(result="banned").inc()
        return (
            jsonify(
                {
                    "message": "Your account has been banned. For further information regarding the ban of your account or to submit a Ban Appeal, contact a member of CSR Staff."
                }
            ),
            403,
        )

    # verify password
    salt = user.get("password_salt", "")
    stored_hash = user.get("password_hash", "")
    try:
        hashtest = checkhashSSHA(salt, password)
    except Exception as e:
        logger.exception("Hashing error for username=%s: %s", username, e)
        return jsonify({"message": "Internal server error"}), 500

    if hashtest == stored_hash:
        logger.info("Auth success for username=%s", username)
        AUTH_ATTEMPTS.labels(result="success").inc()
        return jsonify({"message": "success"}), 200
    else:
        logger.warning("Auth failed: bad password for username=%s", username)
        AUTH_ATTEMPTS.labels(result="bad_password").inc()
        return (
            jsonify({"message": "Account does not exist or password was incorrect"}),
            401,
        )


@app.route("/form_login", methods=["GET"])
def form_login():
    return render_template("form_login.html")


@app.route("/images/<path:filename>")
def images(filename: str):
    root = pathlib.Path(__file__).resolve().parent
    return send_from_directory(root / "static/images", filename)


@app.route("/music/<path:filename>")
def music(filename: str):
    root = pathlib.Path(__file__).resolve().parent
    return send_from_directory(root / "static/music", filename)


@app.route("/post_login", methods=["POST"])
@limiter.limit("5 per minute")
def post_login():
    # Reuse auth logic to validate credentials
    username = request.form.get("username", "")
    password = request.form.get("password", "")
    ip = request.remote_addr or ""
    stationID = request.form.get("stationID", "")

    # Call internal auth logic without making an HTTP request
    # We'll mimic the POST data expected by auth_php
    # Fetch user from DB
    # Log attempt (avoid logging raw password)
    logger.info(
        "Login attempt: username=%s, stationID=%s, ip=%s", username, stationID, ip
    )

    try:
        with cursor() as cur:
            cur.execute("SELECT * FROM user_account WHERE username = %s", (username,))
            user = cur.fetchone()
    except Exception as e:
        logger.exception("Database error during login for username=%s: %s", username, e)
        flash("Internal server error, please try again later.", "error")
        return redirect(url_for("form_login"))

    if not user:
        logger.warning("Login failed: user not found: %s", username)
        LOGIN_ATTEMPTS.labels(result="not_found").inc()
        flash("Login failed: incorrect username or password", "error")
        return redirect(url_for("form_login"))

    # Check for banned account
    if user.get("accesslevel") == "banned":
        logger.info("Login rejected: banned account %s", username)
        LOGIN_ATTEMPTS.labels(result="banned").inc()
        flash("Your account has been banned. Contact CSR staff for appeals.", "error")
        return redirect(url_for("form_login"))

    # Verify password
    try:
        hashtest = checkhashSSHA(user.get("password_salt", ""), password)
    except Exception as e:
        logger.exception("Hash error during login for username=%s: %s", username, e)
        flash("Internal server error, please try again later.", "error")
        return redirect(url_for("form_login"))

    if hashtest == user.get("password_hash", ""):
        # Successful login
        session["username"] = user.get("username")
        session["user"] = user.get("username")
        session["accesslevel"] = user.get("accesslevel")
        logger.info("Login success for username=%s", username)
        LOGIN_ATTEMPTS.labels(result="success").inc()
        # Redirect to saved urlredirect or index
        redirect_target = session.pop("urlredirect", None)
        if redirect_target:
            return redirect(redirect_target)
        return redirect(url_for("index"))

    # Failed password
    logger.warning("Login failed: bad password for username=%s", username)
    LOGIN_ATTEMPTS.labels(result="bad_password").inc()
    flash("Login failed: incorrect username or password", "error")
    return redirect(url_for("form_login"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/post_changepassword", methods=["POST"])
def post_change_password():
    # Ensure logged in
    if "username" not in session:
        return redirect(url_for("add_new_user"))

    action = request.form.get("action", "")
    username = request.form.get("username", "")

    # Permission check: either changing own password or must be superadmin
    if (
        session.get("username", "").lower() != username.lower()
        and session.get("accesslevel") != "superadmin"
    ):
        return "Error - You can only change your own password.", 403

    if action == "update":
        realpassword = request.form.get("password", "")
        encrypted, salt = hash_password_php_compat(realpassword)

        try:
            with cursor() as cur:
                sql = "UPDATE user_account SET password_hash=%s, password_salt=%s WHERE username=%s"
                cur.execute(sql, (encrypted, salt, username))
        except Exception as e:
            return f"Database error: {e}", 500

        return redirect(url_for("index"))

    return redirect(url_for("change_password"))


def grade_password_complexity(password: str) -> str:
    """Return a grade for password complexity using zxcvbn if available, else heuristic."""
    try:
        if zx_analyze is not None:
            score = zx_analyze(password)["score"]  # 0..4
            if score >= 4:
                return "Strong"
            if score >= 2:
                return "Medium"
            return "Weak"
    except Exception:
        pass
    # Fallback heuristic
    import re

    score = 0
    if len(password) >= 12:
        score += 1
    if re.search(r"[A-Z]", password):
        score += 1
    if re.search(r"[a-z]", password):
        score += 1
    if re.search(r"\d", password):
        score += 1
    if re.search(r"[^\w\s]", password):
        score += 1
    if score >= 4:
        return "Strong"
    if score >= 2:
        return "Medium"
    return "Weak"

@app.route("/admin_user_edit", methods=["GET", "POST"])
def admin_user_edit():
    # Only allow superadmin; log access attempts
    admin_username = session.get("username")
    client_ip = request.remote_addr or ""
    if session.get("accesslevel") != "superadmin":
        logger.warning(
            "admin_user_edit denied: user=%s ip=%s",
            admin_username or "<anonymous>",
            client_ip,
        )
        abort(403)

    message = ""
    complexity = ""
    # Log GET access to the page
    if request.method == "GET":
        logger.info(
            "admin_user_edit GET by=%s ip=%s",
            admin_username or "<anonymous>",
            client_ip,
        )
    if request.method == "POST":
        target_username = request.form.get("username", "").strip()
        new_password = request.form.get("password", "")
        new_accesslevel = request.form.get("accesslevel", "standard")

        logger.info(
            "admin_user_edit POST by=%s ip=%s target=%s requested_accesslevel=%s",
            admin_username or "<anonymous>",
            client_ip,
            target_username,
            new_accesslevel,
        )

        complexity = grade_password_complexity(new_password)
        # Do not log raw password; only log the grade
        logger.info(
            "admin_user_edit password complexity grade for target=%s: %s",
            target_username,
            complexity,
        )

        if new_accesslevel not in ("banned", "superadmin", "standard"):
            message = "Invalid access level."
            logger.warning(
                "admin_user_edit invalid access level by=%s ip=%s target=%s accesslevel=%s",
                admin_username or "<anonymous>",
                client_ip,
                target_username,
                new_accesslevel,
            )
        else:
            try:
                encrypted, salt = hash_password_php_compat(new_password)
                with cursor() as cur:
                    sql = "UPDATE user_account SET password_hash=%s, password_salt=%s, accesslevel=%s WHERE username=%s"
                    cur.execute(sql, (encrypted, salt, new_accesslevel, target_username))
                    rows = cur.rowcount
                if rows == 0:
                    logger.warning(
                        "admin_user_edit no rows updated; user may not exist: target=%s by=%s ip=%s",
                        target_username,
                        admin_username or "<anonymous>",
                        client_ip,
                    )
                else:
                    logger.info(
                        "Superadmin updated user: %s to accesslevel=%s (rows=%s)",
                        target_username,
                        new_accesslevel,
                        rows,
                    )
                message = f"User '{target_username}' updated. Password complexity: {complexity}"
            except Exception as e:
                logger.exception(
                    "Superadmin failed to update user: %s by=%s ip=%s",
                    target_username,
                    admin_username or "<anonymous>",
                    client_ip,
                )
                message = f"Database error: {e}"

    # Fetch all users for selection
    try:
        with cursor() as cur:
            cur.execute("SELECT username, accesslevel FROM user_account ORDER BY user_id")
            users = cur.fetchall()
    except Exception as e:
        logger.exception(
            "Failed to fetch users for admin_user_edit by=%s ip=%s: %s",
            admin_username or "<anonymous>",
            client_ip,
            e,
        )
        users = []

    return render_template(
        "admin_user_edit.html",
        users=users,
        message=message,
        complexity=complexity,
    )


@app.route("/healthz")
def healthz():
    # Basic health: attempt trivial DB query and return status JSON
    db_ok = False
    try:
        with cursor() as cur:
            cur.execute("SELECT 1")
        db_ok = True
    except Exception:
        db_ok = False
    status = {
        "status": "ok" if db_ok else "degraded",
        "db": "up" if db_ok else "error",
    }
    http_code = 200 if db_ok else 503
    return jsonify(status), http_code


@app.route("/metrics")
def metrics():
    # Expose Prometheus metrics
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)

if __name__ == "__main__":
    app.run(debug=True)
