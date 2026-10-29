"""
Integration tests for FastAPI endpoints:
- User signup, login, get current user, profile update
- Email verification flow
- Password reset flow
- Code execution sandbox
- Code optimization analysis
"""

import unittest
from fastapi.testclient import TestClient
import database
from server import app

class TestServerEndpoints(unittest.TestCase):
    def setUp(self):
        # Reset DB tables
        with database.get_db_connection() as conn:
            conn.execute("DELETE FROM sessions")
            conn.execute("DELETE FROM email_verification_tokens")
            conn.execute("DELETE FROM password_reset_tokens")
            conn.execute("DELETE FROM dev_outbox")
            conn.execute("DELETE FROM users")
            conn.commit()
        self.client = TestClient(app)

    def test_signup_login_profile_flow(self):
        # 1. Signup
        signup_res = self.client.post("/api/auth/signup", json={
            "username": "supercoder",
            "email": "coder@example.com",
            "password": "Password123"
        })
        self.assertEqual(signup_res.status_code, 200)
        data = signup_res.json()
        self.assertTrue(data["success"])
        self.assertTrue(data["user"]["id"].startswith("usr_"))
        token = data["token"]
        verification_token = data["verification_token"]

        # 2. Get profile with Bearer token
        me_res = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(me_res.status_code, 200)
        self.assertEqual(me_res.json()["user"]["username"], "supercoder")

        # 3. Verify email
        verify_res = self.client.post("/api/auth/verify-email", json={"token": verification_token})
        self.assertEqual(verify_res.status_code, 200)
        self.assertTrue(verify_res.json()["success"])

        # 4. Check profile is now verified
        me_verified = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertTrue(me_verified.json()["user"]["is_verified"])

        # 5. Update profile
        update_res = self.client.put(
            "/api/auth/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={"bio": "Principal Fullstack Architect", "avatar_url": "https://example.com/avatar.png"}
        )
        self.assertEqual(update_res.status_code, 200)
        self.assertEqual(update_res.json()["user"]["bio"], "Principal Fullstack Architect")

    def test_forgot_and_reset_password_flow(self):
        # Create user
        self.client.post("/api/auth/signup", json={
            "username": "alex",
            "email": "alex@example.com",
            "password": "oldPassword123"
        })

        # Forgot password request
        forgot_res = self.client.post("/api/auth/forgot-password", json={"email": "alex@example.com"})
        self.assertEqual(forgot_res.status_code, 200)
        reset_token = forgot_res.json()["reset_token"]
        self.assertIsNotNone(reset_token)

        # Reset password
        reset_res = self.client.post("/api/auth/reset-password", json={
            "token": reset_token,
            "new_password": "brandNewPassword99"
        })
        self.assertEqual(reset_res.status_code, 200)

        # Login with old password fails
        bad_login = self.client.post("/api/auth/login", json={
            "identifier": "alex",
            "password": "oldPassword123"
        })
        self.assertEqual(bad_login.status_code, 401)

        # Login with new password succeeds
        good_login = self.client.post("/api/auth/login", json={
            "identifier": "alex",
            "password": "brandNewPassword99"
        })
        self.assertEqual(good_login.status_code, 200)
        self.assertTrue(good_login.json()["success"])

    def test_optimize_endpoint(self):
        code = "def fib(n):\n    if n <= 1: return n\n    return fib(n - 1) + fib(n - 2)\n"
        res = self.client.post("/api/optimize", json={"code": code, "language": "python"})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["success"])
        self.assertTrue(body["data"]["has_suggestions"])

    def test_execute_endpoint(self):
        code = "print('Hello Server Execution!')"
        res = self.client.post("/api/execute", json={"code": code, "language": "python"})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["result"]["status"], "success")
        self.assertIn("Hello Server Execution!", body["result"]["stdout"])

if __name__ == "__main__":
    unittest.main()
