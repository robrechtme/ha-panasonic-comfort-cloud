"""Constants for the Panasonic Comfort Cloud client (HA-agnostic)."""

# Auth (Auth0 / Panasonic ID)
AUTH_BASE = "https://authglb.digital.panasonic.com"
CLIENT_ID = "Xmy6xIYIitMxngjB2rHvlm6HSDNnaMJx"
AUTH0_CLIENT = (
    "eyJuYW1lIjoiQXV0aDAuQW5kcm9pZCIsImVudiI6eyJhbmRyb2lkIjoiMzAifSwidmVyc2lvbiI6IjIuOS4zIn0="
)
REDIRECT_URI = (
    "panasonic-iot-cfc://authglb.digital.panasonic.com/android/com.panasonic.ACCsmart/callback"
)
SCOPE = "openid offline_access comfortcloud.control a2w.control"

# Comfort Cloud API
API_BASE = "https://accsmart.panasonic.com"
FIXED_KEY = "521325fb2dd486bf4831b47644317fca"
APP_VERSION_FALLBACK = "4.3.0"
PLAY_STORE_URL = (
    "https://play.google.com/store/apps/details?id=com.panasonic.ACCsmart&hl=en"
)

AQUAREA_DEVICE_TYPE = "2"  # deviceType for air-to-water (Aquarea) units
