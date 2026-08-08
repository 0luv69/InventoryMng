# At the very bottom of settings.py

# Static & Media
STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'  # <--- ADD THIS LINE

MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Custom User Model
AUTH_USER_MODEL = 'accounts.User'

# Security
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['*']) # <--- ADD THIS LINE