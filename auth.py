"""Who is asking. The identity is a header a forward-auth proxy sets."""

from flask import request, abort, jsonify
import config


def current_user():
    if config.AUTH_MODE != "proxy":
        return config.SOLO_USER
    user = (request.headers.get("Remote-User") or "").strip()
    if not user:
        abort(401)
    return user


def user_groups():
    return [g.strip() for g in (request.headers.get("Remote-Groups") or "").split(",")
            if g.strip()]


def is_admin():
    if config.AUTH_MODE != "proxy":
        return True
    return config.ADMIN_GROUP in user_groups()


def require_admin():
    current_user()
    if is_admin():
        return
    # A bare 403 cannot tell "the group is missing from the provider" from
    # "the proxy is not copying the header", which are fixed in different
    # places. Showing the caller its own groups gives that away for free.
    groups = user_groups()
    if groups:
        detail = f"groups received: {', '.join(groups)}"
    else:
        detail = "no groups received at all, so the proxy is not copying Remote-Groups"
    abort(403, f"Admin needs the {config.ADMIN_GROUP} group. For {current_user()}, {detail}.")


def page_context():
    """What the header needs. Rendered server-side: the identity is known here,
    so asking for it from the browser only bought a flash of empty header."""
    return {"auth": config.AUTH_MODE, "user": current_user(),
            "admin": is_admin(), "logout_url": config.LOGOUT_URL,
            "feed": config.FEED_ENABLED, "shorts": config.SHORTS_ENABLED, "tiktok": config.TIKTOK_ENABLED,
            "share": config.SHARE_ENABLED,
            "following": config.FEED_ENABLED or config.SHORTS_ENABLED or config.TIKTOK_ENABLED}
