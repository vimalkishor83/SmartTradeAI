from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity
from app.extensions import db
from app.models.notification import Notification
from app.auth.decorators import login_required

notifications_bp = Blueprint("notifications", __name__)


@notifications_bp.route("/", methods=["GET"])
@login_required
def get_notifications():
    user_id = get_jwt_identity()
    page = int(request.args.get("page", 1))
    unread_only = request.args.get("unread") == "true"

    query = Notification.query.filter_by(user_id=user_id)
    if unread_only:
        query = query.filter_by(is_read=False)

    notifs = query.order_by(Notification.created_at.desc()) \
        .paginate(page=page, per_page=20, error_out=False)

    return jsonify({
        "notifications": [n.to_dict() for n in notifs.items],
        "unread_count": Notification.query.filter_by(user_id=user_id, is_read=False).count(),
        "total": notifs.total,
    }), 200


@notifications_bp.route("/<int:notif_id>/read", methods=["PUT"])
@login_required
def mark_read(notif_id):
    user_id = get_jwt_identity()
    notif = Notification.query.filter_by(id=notif_id, user_id=user_id).first_or_404()
    notif.is_read = True
    db.session.commit()
    return jsonify({"message": "Marked as read"}), 200


@notifications_bp.route("/read-all", methods=["PUT"])
@login_required
def mark_all_read():
    user_id = get_jwt_identity()
    Notification.query.filter_by(user_id=user_id, is_read=False).update({"is_read": True})
    db.session.commit()
    return jsonify({"message": "All notifications marked as read"}), 200
