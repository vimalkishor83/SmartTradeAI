"""WebSocket event handlers for live market updates and signal notifications."""
import logging
from flask import request
from flask_socketio import emit, join_room, leave_room
from flask_jwt_extended import decode_token
from app.extensions import socketio
from app.models.user import User
from app.services.data.fetcher import market_fetcher
from app.models.asset import Asset

logger = logging.getLogger(__name__)


@socketio.on("connect")
def on_connect():
    token = request.args.get("token")
    if not token:
        return False
    try:
        data = decode_token(token)
        user = User.query.get(data["sub"])
        if not user or not user.is_active:
            return False
        logger.info(f"WS connected: user {user.username}")
        emit("connected", {"status": "ok", "user": user.username})
    except Exception as e:
        logger.warning(f"WS auth failed: {e}")
        return False


@socketio.on("disconnect")
def on_disconnect():
    logger.debug(f"WS disconnected: {request.sid}")


@socketio.on("subscribe_ticker")
def subscribe_ticker(data):
    symbol = data.get("symbol")
    if symbol:
        join_room(f"ticker_{symbol}")
        emit("subscribed", {"symbol": symbol, "room": f"ticker_{symbol}"})


@socketio.on("unsubscribe_ticker")
def unsubscribe_ticker(data):
    symbol = data.get("symbol")
    if symbol:
        leave_room(f"ticker_{symbol}")


@socketio.on("subscribe_signals")
def subscribe_signals(data):
    market = data.get("market", "all")
    join_room(f"signals_{market}")
    emit("subscribed", {"market": market})


def broadcast_signal(signal_dict):
    market = signal_dict.get("market", "all")
    socketio.emit("new_signal", signal_dict, room=f"signals_{market}")
    socketio.emit("new_signal", signal_dict, room="signals_all")


def broadcast_ticker(symbol: str, ticker_data: dict):
    socketio.emit("ticker_update", ticker_data, room=f"ticker_{symbol}")
