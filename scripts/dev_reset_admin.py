#!/usr/bin/env python
"""
SmartCivic — Development Admin Reset Utility
=============================================
Safely resets or creates an admin user in the development database.

Security Constraints:
1. Refuses to run unless APP_ENV=development (or FLASK_ENV=development).
2. Prompts for password interactively via getpass (never accepts password via CLI argument).
3. Uses the application's canonical hash_password function (Argon2id).
4. Sets verified=True, verification_status="approved", status="active".
5. Clears all failed login attempts and temporary lockouts.
"""
import os
import sys
import getpass
from datetime import datetime

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def check_dev_environment():
    """Refuses execution unless environment is explicitly development."""
    app_env = os.getenv("APP_ENV", os.getenv("FLASK_ENV", "")).strip().lower()
    if app_env != "development":
        print("\n[SECURITY ERROR] scripts/dev_reset_admin.py is strictly restricted to development environments.", file=sys.stderr)
        print(f"Current effective environment: APP_ENV='{os.getenv('APP_ENV')}', FLASK_ENV='{os.getenv('FLASK_ENV')}'", file=sys.stderr)
        print("To run this utility, set APP_ENV=development in your environment or .env file.\n", file=sys.stderr)
        sys.exit(1)


def main():
    check_dev_environment()

    # Import app singletons after dev check
    from app import create_app, db
    from routes.auth import hash_password, validate_password_strength

    # Bootstrap app context for DB access
    app = create_app()
    with app.app_context():
        print("==========================================================================")
        print("           SMARTCIVIC DEV ADMIN RESET / CREATION UTILITY                  ")
        print("==========================================================================")
        print(f"Target Database: {db.name}")

        default_email = "admin@smartcivic.com"
        email_prompt = input(f"Enter admin email [{default_email}]: ").strip()
        email = (email_prompt or default_email).lower()

        # Prompt for password securely (not via CLI argument)
        while True:
            password = getpass.getpass("Enter new admin password: ")
            if not password:
                print("Error: Password cannot be empty.")
                continue
            is_valid, msg = validate_password_strength(password)
            if not is_valid:
                print(f"Weak password: {msg}")
                continue
            confirm = getpass.getpass("Confirm new admin password: ")
            if password != confirm:
                print("Error: Passwords do not match. Please try again.")
                continue
            break

        print("\nHashing password using application's Argon2id hasher...")
        pwd_hash = hash_password(password)

        now = datetime.utcnow()
        update_data = {
            "name": "System Administrator",
            "email": email,
            "password_hash": pwd_hash,
            "role": "admin",
            "ward": "all",
            "ward_id": "all",
            "verified": True,
            "verification_status": "approved",
            "status": "active",
            "failed_logins": 0,
            "locked_until": None,
            "updated_at": now
        }

        # Check if user already exists
        existing = db.users.find_one({"email": email})
        if existing:
            db.users.update_one({"_id": existing["_id"]}, {"$set": update_data})
            action_str = "Reset existing"
            user_id = str(existing["_id"])
        else:
            update_data["created_at"] = now
            res = db.users.insert_one(update_data)
            action_str = "Created new"
            user_id = str(res.inserted_id)

        # Clear any lockouts in login_lockouts collection if present
        if "login_lockouts" in db.list_collection_names():
            db.login_lockouts.delete_many({"email": email})

        print(f"\n[SUCCESS] {action_str} admin user profile:")
        print(f"  * User ID:             {user_id}")
        print(f"  * Email:               {email}")
        print(f"  * Role:                admin")
        print(f"  * Verified:            True (verification_status='approved')")
        print(f"  * Status:              active")
        print(f"  * Lockout Cleared:     failed_logins=0, locked_until=None")
        print(f"  * Password Hasher:     Argon2id ({pwd_hash[:30]}...)")
        print("==========================================================================\n")


if __name__ == "__main__":
    main()

