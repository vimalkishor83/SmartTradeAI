from datetime import datetime
from app.extensions import db


def parse_device_label(user_agent: str) -> str:
    """Short, human-readable summary of a user_agent string — full
    user-agent strings are long and mostly noise. Shared by UserSession's
    own support view and the new-IP-login security alert, which both
    want the same "Chrome · Windows"-style summary."""
    ua = user_agent or ""
    browser = next((b for b in ("Edg", "Chrome", "Firefox", "Safari", "OPR") if b in ua), None)
    os_name = next((o for o in ("Windows", "Mac OS X", "Android", "iPhone", "iPad", "Linux") if o in ua), None)
    label = " · ".join(x for x in (browser, os_name) if x)
    return label or (ua[:40] if ua else "Unknown device")


class UserSession(db.Model):
    """One row per login — not per access token. A refresh token rotation
    reuses the same row (see the "sid" custom JWT claim embedded in both
    the access and refresh token at login, and re-attached on every
    /auth/refresh) rather than minting a new row every time the access
    token is renewed, so "session timeout" means total time since login,
    not an endlessly-extendable idle window.

    Also the enforcement point for admin-configurable session timeout and
    server-side logout: flask-jwt-extended tokens are otherwise stateless
    JWTs that stay valid until their own expiry no matter what /logout
    does client-side. The token_in_blocklist_loader (app/__init__.py)
    checks this table on every authenticated request via the token's
    "sid" claim, so revoking a row here (logout, or an admin force-logout)
    takes effect immediately instead of waiting out the token's natural
    lifetime."""
    __tablename__ = "user_sessions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    ip_address = db.Column(db.String(50))
    user_agent = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    last_seen_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    revoked_at = db.Column(db.DateTime)
    revoked_reason = db.Column(db.String(50))  # "logout", "admin_revoked", "expired"

    user = db.relationship("User")

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None and self.expires_at > datetime.utcnow()

    def device_label(self) -> str:
        return parse_device_label(self.user_agent)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "username": self.user.username if self.user else "—",
            "ip_address": self.ip_address or "—",
            "device": self.device_label(),
            "user_agent": self.user_agent or "",
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_seen_at": self.last_seen_at.isoformat() if self.last_seen_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "revoked_reason": self.revoked_reason,
            "is_active": self.is_active,
        }
