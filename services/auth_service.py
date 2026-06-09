import jwt
import bcrypt
from datetime import datetime, timedelta
from functools import wraps
from flask import g, request, jsonify, current_app
from bson import ObjectId

def hash_password(plain_text: str) -> str:
    return bcrypt.hashpw(plain_text.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def check_password(plain_text: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain_text.encode('utf-8'), hashed.encode('utf-8'))
    except Exception:
        return False

def create_token(user_id: str, role: str, community_id: str) -> str:
    from app import db # import dynamically to avoid circular dependencies
    payload = {
        'user_id': str(user_id),
        'role': role,
        'community_id': str(community_id) if community_id else None,
        'exp': datetime.utcnow() + timedelta(hours=24),
        'iat': datetime.utcnow()
    }
    return jwt.encode(payload, current_app.config['JWT_SECRET'], algorithm='HS256')

def decode_token(token: str) -> dict:
    return jwt.decode(token, current_app.config['JWT_SECRET'], algorithms=['HS256'])

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        from app import db
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'success': False, 'message': 'Missing token', 'data': None}), 401
        
        token = auth_header.split(' ')[1]
        try:
            payload = decode_token(token)
        except jwt.ExpiredSignatureError:
            return jsonify({'success': False, 'message': 'Token expired', 'data': None}), 401
        except jwt.InvalidTokenError:
            return jsonify({'success': False, 'message': 'Invalid token', 'data': None}), 401
            
        user = db.users.find_one({'_id': ObjectId(payload['user_id'])})
        if not user:
            return jsonify({'success': False, 'message': 'User not found', 'data': None}), 401
            
        g.user = {
            'user_id': str(user['_id']),
            'name': user['name'],
            'email': user['email'],
            'role': user['role'],
            'community_id': str(user['community_id']) if user.get('community_id') else None,
            'is_verified': user.get('is_verified', False)
        }
        return f(*args, **kwargs)
    return decorated

def require_role(*roles):
    def decorator(f):
        @wraps(f)
        @require_auth
        def decorated(*args, **kwargs):
            if g.user['role'] not in roles:
                return jsonify({'success': False, 'message': 'Forbidden: Insufficient permissions', 'data': None}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator

def require_verified(f):
    @wraps(f)
    @require_auth
    def decorated(*args, **kwargs):
        if not g.user['is_verified']:
            return jsonify({'success': False, 'message': 'Account not yet verified', 'data': None}), 403
        return f(*args, **kwargs)
    return decorated

def rate_limit(max_per_minute: int = 30):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            ip = request.remote_addr
            now = datetime.utcnow().timestamp()
            
            # Fetch the global rate limit store from app
            store = current_app.rate_limit_store
            
            if ip not in store:
                store[ip] = []
                
            # Keep only timestamps in last 60 seconds
            store[ip] = [ts for ts in store[ip] if now - ts < 60]
            
            if len(store[ip]) >= max_per_minute:
                return jsonify({'success': False, 'message': 'Too Many Requests: Rate limit exceeded', 'data': None}), 429
                
            store[ip].append(now)
            return f(*args, **kwargs)
        return decorated
    return decorator
