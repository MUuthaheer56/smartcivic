import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'smartcivic-dev-2024')
    MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
    DB_NAME = os.getenv('DB_NAME', 'smartcivic')
    JWT_SECRET = os.getenv('JWT_SECRET', 'jwt-smartcivic-2024')
    JWT_EXPIRY_HOURS = 24
    UPLOAD_FOLDER = os.path.join('static', 'uploads')
    ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    MAIL_SERVER = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.getenv('MAIL_PORT', 587))
    MAIL_USE_TLS = os.getenv('MAIL_USE_TLS', 'True') == 'True'
    MAIL_USERNAME = os.getenv('MAIL_USERNAME', '')
    MAIL_PASSWORD = os.getenv('MAIL_PASSWORD', '')
    MAIL_DEFAULT_SENDER = os.getenv('MAIL_USERNAME', '')
    APP_BASE_URL = os.getenv('APP_BASE_URL', 'http://localhost:5000')
    OPENWEATHER_API_KEY = os.getenv('OPENWEATHER_API_KEY', '')
    AI_IMAGE_ANALYSIS_ENABLED = os.getenv('AI_IMAGE_ANALYSIS_ENABLED', 'True') == 'True'
