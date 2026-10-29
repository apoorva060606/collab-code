"""
Automated unit tests for database and user management features:
- Signup & Unique user ID generation
- Duplicate user detection
- Login authentication
- Email verification flow
- Password reset flow
- Profile management
"""

import unittest
import os
import database

class TestAuthAndUserManagement(unittest.TestCase):
    def setUp(self):
        with database.get_db_connection() as conn:
            conn.execute("DELETE FROM sessions")
            conn.execute("DELETE FROM email_verification_tokens")
            conn.execute("DELETE FROM password_reset_tokens")
            conn.execute("DELETE FROM dev_outbox")
            conn.execute("DELETE FROM users")
            conn.commit()

    def test_signup_and_unique_id(self):
        user = database.create_user("alice_dev", "alice@test.com", "secure123")
        self.assertTrue(user["id"].startswith("usr_"))
        self.assertEqual(user["username"], "alice_dev")
        self.assertEqual(user["email"], "alice@test.com")
        self.assertFalse(user["is_verified"])
        self.assertTrue(bool(user["verification_token"]))

    def test_duplicate_user(self):
        database.create_user("bob_dev", "bob@test.com", "password123")
        with self.assertRaises(ValueError):
            database.create_user("bob_dev", "other@test.com", "password123")
        with self.assertRaises(ValueError):
            database.create_user("other_dev", "bob@test.com", "password123")

    def test_login_and_session(self):
        database.create_user("charlie", "charlie@test.com", "mySecretPass")
        
        # Test valid login
        user = database.authenticate_user("charlie", "mySecretPass")
        self.assertIsNotNone(user)
        self.assertEqual(user["username"], "charlie")
        
        # Test email login
        user_by_email = database.authenticate_user("charlie@test.com", "mySecretPass")
        self.assertIsNotNone(user_by_email)
        
        # Test invalid password
        invalid = database.authenticate_user("charlie", "wrongPass")
        self.assertIsNone(invalid)
        
        # Test session creation and retrieval
        session_token = database.create_session(user["id"])
        session_user = database.get_user_by_session(session_token)
        self.assertIsNotNone(session_user)
        self.assertEqual(session_user["id"], user["id"])
        
        # Test session deletion (logout)
        database.delete_session(session_token)
        self.assertIsNone(database.get_user_by_session(session_token))

    def test_email_verification(self):
        user = database.create_user("diana", "diana@test.com", "password123")
        self.assertFalse(user["is_verified"])
        
        # Verify with token
        token = user["verification_token"]
        success = database.verify_email_with_token(token)
        self.assertTrue(success)
        
        # Check user is now verified
        user_data = database.get_user_by_id(user["id"])
        self.assertTrue(user_data["is_verified"])
        
        # Re-using the same token fails
        self.assertFalse(database.verify_email_with_token(token))

    def test_password_reset(self):
        user = database.create_user("edward", "edward@test.com", "original123")
        
        # Request reset token
        reset_token = database.request_password_reset("edward@test.com")
        self.assertIsNotNone(reset_token)
        
        # Reset password
        reset_ok = database.reset_password_with_token(reset_token, "newPassword999")
        self.assertTrue(reset_ok)
        
        # Old password fails, new password succeeds
        self.assertIsNone(database.authenticate_user("edward", "original123"))
        new_auth = database.authenticate_user("edward", "newPassword999")
        self.assertIsNotNone(new_auth)

    def test_profile_update(self):
        user = database.create_user("fiona", "fiona@test.com", "pass123456")
        updated = database.update_user_profile(
            user["id"],
            bio="Full-stack AI developer",
            avatar_url="https://api.dicebear.com/7.x/bottts/svg?seed=fiona"
        )
        self.assertEqual(updated["bio"], "Full-stack AI developer")

if __name__ == "__main__":
    unittest.main()
