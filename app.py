import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from functools import wraps
import db_shared as _db

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "nf-web-secret-change-in-prod")

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = "Please login to continue."


class WebUser(UserMixin):
    def __init__(self, row):
        self.id       = row["id"]
        self.username = row["username"]
        self.role     = row["role"]

    def is_admin(self):
        return self.role == "admin"


@login_manager.user_loader
def load_user(user_id):
    row = _db.get_web_user_by_id(int(user_id))
    return WebUser(row) if row else None


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin():
            flash("Access denied. Admins only.", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated


# ── Login ─────────────────────────────────────────────
@app.route("/", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        row = _db.verify_web_user(username, password)
        if row:
            login_user(WebUser(row), remember=True)
            _db.update_last_login(row["id"])
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "danger")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


# ── Dashboard ─────────────────────────────────────────
@app.route("/dashboard")
@login_required
def dashboard():
    hits_count = _db.count_hits_db()
    return render_template("dashboard.html", hits_count=hits_count)


# ── Generate Cookie ───────────────────────────────────
@app.route("/generate", methods=["POST"])
@login_required
def generate():
    hit = _db.get_random_hit_full()
    if not hit:
        return jsonify({"success": False, "message": "No cookies available in stock right now. Try again later."})

    bundle = hit["bundle"]
    cookies_parts = []
    for key in ["nfvdid", "SecureNetflixId", "NetflixId", "flwssn", "gsid"]:
        if key in bundle:
            cookies_parts.append(f"{key}={bundle[key]}")
    cookie_str = "; ".join(cookies_parts)

    cookie_txt  = "# Netflix Cookie\n"
    cookie_txt += f"# Email   : {hit['email']}\n"
    cookie_txt += f"# Country : {hit['country']}\n"
    cookie_txt += f"# Quality : {hit['quality']}\n"
    cookie_txt += f"Cookies = {cookie_str}\n"

    return jsonify({
        "success": True,
        "email":   hit["email"],
        "country": hit["country"],
        "quality": hit["quality"],
        "cookie_str": cookie_str,
        "cookie_txt": cookie_txt,
        "hits_remaining": _db.count_hits_db(),
    })


# ── Admin Panel ───────────────────────────────────────
@app.route("/admin")
@login_required
@admin_required
def admin():
    return render_template("admin.html",
                           users=_db.get_all_web_users(),
                           hits_count=_db.count_hits_db())


@app.route("/admin/add-user", methods=["POST"])
@login_required
@admin_required
def admin_add_user():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    role     = request.form.get("role", "user")
    if not username or not password:
        flash("Username and password are required.", "danger")
        return redirect(url_for("admin"))
    if len(password) < 4:
        flash("Password must be at least 4 characters.", "danger")
        return redirect(url_for("admin"))
    ok, err = _db.add_web_user(username, password, role)
    flash(f"User '{username}' added!" if ok else f"Error: {err}",
          "success" if ok else "danger")
    return redirect(url_for("admin"))


@app.route("/admin/delete-user/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def admin_delete_user(user_id):
    if user_id == current_user.id:
        flash("You cannot delete yourself.", "danger")
        return redirect(url_for("admin"))
    _db.delete_web_user(user_id)
    flash("User deleted.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/change-password/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def admin_change_password(user_id):
    new_pass = request.form.get("new_password", "").strip()
    if len(new_pass) < 4:
        flash("Password must be at least 4 characters.", "danger")
        return redirect(url_for("admin"))
    _db.change_web_password(user_id, new_pass)
    flash("Password updated.", "success")
    return redirect(url_for("admin"))


# ── Startup ───────────────────────────────────────────
if __name__ == "__main__":
    _db.init_all()
    _db.init_web_admin(
        os.environ.get("ADMIN_USERNAME", "admin"),
        os.environ.get("ADMIN_PASSWORD", "admin123")
    )
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
