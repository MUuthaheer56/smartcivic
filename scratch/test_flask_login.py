import sys
import os
import json

# Ensure workspace is in python path
sys.path.append(os.getcwd())

from app import create_app

def test_flask_login():
    app = create_app()
    client = app.test_client()
    
    # We temporarily unregister the exception handler so we see the raw traceback!
    app.error_handler_spec[None][500] = {}
    
    payload = {
        "email": "authority@smartcivic.com",
        "password": "smartcivic123"
    }
    
    print("Posting to /auth/login...")
    try:
        response = client.post(
            '/auth/login',
            data=json.dumps(payload),
            content_type='application/json'
        )
        print(f"Status Code: {response.status_code}")
        print(f"Response Data: {response.data.decode('utf-8')}")
    except Exception as e:
        print("Exception raised during post:")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    test_flask_login()
