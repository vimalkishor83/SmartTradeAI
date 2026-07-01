from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_jwt_extended import JWTManager
from flask_socketio import SocketIO
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_caching import Cache
from flask_migrate import Migrate
from apscheduler.schedulers.background import BackgroundScheduler

db = SQLAlchemy()
bcrypt = Bcrypt()
jwt = JWTManager()
socketio = SocketIO()
limiter = Limiter(key_func=get_remote_address)
cache = Cache()
migrate = Migrate()
scheduler = BackgroundScheduler()
