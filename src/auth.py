"""Authentication module."""

class AuthService:
    def __init__(self):
        self.session_store = {}

    def authenticate_user(self, username: str, token: str) -> bool:
        """Verify user credentials."""
        if not username or not token:
            return False
        return token == f"secret-{username}"

    def get_user_role(self, username: str) -> str:
        """Return the role for a user."""
        return "admin" if username == "admin" else "user"
