import sys
import os
from datetime import datetime
from bson import ObjectId

# Ensure workspace is in python path
sys.path.append(os.getcwd())

from app import create_app, db
from routes.auth import check_password, generate_tokens

def test_login():
    app = create_app()
    with app.app_context():
        email = "authority@smartcivic.com"
        print(f"Searching for {email}...")
        user = db.users.find_one({"email": email})
        print(f"User found: {user}")
        if not user:
            print("User not found!")
            return
            
        print("Checking password...")
        pw_ok = check_password("smartcivic123", user.get("password_hash", ""))
        print(f"Password match: {pw_ok}")
        
        print("Generating tokens...")
        try:
            access, refresh = generate_tokens(str(user["_id"]), user["role"], user.get("ward", ""))
            print(f"Token generation success! Access token length: {len(access)}")
        except Exception as token_err:
            print(f"Token generation failed: {token_err}")
            import traceback
            traceback.print_exc()

if __name__ == '__main__':
    test_login()
