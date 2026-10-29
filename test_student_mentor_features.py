"""
Automated Integration Tests for Student-Focused Collaboration, Teacher/Mentor Mode,
Streak Forest System, and Sandboxed Execution.
"""

import unittest
from fastapi.testclient import TestClient
from server import app
import database

client = TestClient(app)


class TestStudentMentorFeatures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Create test users
        cls.student = database.create_user("student_coder", "student@college.edu", "pass1234")
        cls.teammate = database.create_user("team_partner", "partner@college.edu", "pass1234")
        cls.mentor = database.create_user("prof_mentor", "mentor@university.edu", "pass1234")
        
        cls.student_token = database.create_session(cls.student["id"])
        cls.teammate_token = database.create_session(cls.teammate["id"])
        cls.mentor_token = database.create_session(cls.mentor["id"])

    def test_01_team_and_project_lifecycle(self):
        # 1. Student creates team
        headers = {"Authorization": f"Bearer {self.student_token}"}
        resp = client.post("/api/teams", json={
            "name": "Distributed Systems Squad",
            "description": "College Capstone Project Group"
        }, headers=headers)
        self.assertEqual(resp.status_code, 200)
        team_data = resp.json()["team"]
        team_id = team_data["id"]
        invite_code = team_data["invite_code"]

        # 2. Teammate joins team via invite code
        resp_join = client.post("/api/teams/join", json={"invite_code": invite_code},
                                headers={"Authorization": f"Bearer {self.teammate_token}"})
        self.assertEqual(resp_join.status_code, 200)

        # 3. Create Project under team
        resp_proj = client.post("/api/projects", json={
            "team_id": team_id,
            "name": "Raft Consensus Key-Value Store",
            "description": "Distributed log replication project",
            "language": "python"
        }, headers=headers)
        self.assertEqual(resp_proj.status_code, 200)
        proj_data = resp_proj.json()["project"]
        project_id = proj_data["id"]

        # 4. Assign Kanban Tasks
        resp_task = client.post(f"/api/projects/{project_id}/tasks", json={
            "title": "Implement Leader Election RPC",
            "description": "Handle heartbeat timeouts and term increments",
            "assigned_to": "team_partner",
            "priority": "high"
        }, headers=headers)
        self.assertEqual(resp_task.status_code, 200)
        task_id = resp_task.json()["task"]["id"]

        # 5. Move Task Status
        resp_update = client.put(f"/api/projects/tasks/{task_id}", json={
            "status": "in_progress"
        })
        self.assertEqual(resp_update.status_code, 200)
        self.assertEqual(resp_update.json()["task"]["status"], "in_progress")

        # 6. Submit Project
        resp_sub = client.post(f"/api/projects/{project_id}/submit", json={
            "submission_title": "Sprint 1 Final Submission",
            "repository_notes": "Implemented leader election and consensus heartbeats.",
            "files_snapshot_json": '{"main.py": "print(\'Raft Consensus\')"}'
        }, headers=headers)
        self.assertEqual(resp_sub.status_code, 200)
        sub_id = resp_sub.json()["submission"]["id"]

        # 7. Mentor grades submission and gives feedback
        mentor_headers = {"Authorization": f"Bearer {self.mentor_token}"}
        resp_grade = client.post(f"/api/projects/submissions/{sub_id}/grade", json={
            "grade_score": 96,
            "feedback": "Outstanding raft state transitions! Excellent edge case handling on split-votes."
        }, headers=mentor_headers)
        self.assertEqual(resp_grade.status_code, 200)
        graded = resp_grade.json()["submission"]
        self.assertEqual(graded["grade_score"], 96)
        self.assertEqual(graded["graded_by"], "prof_mentor")

    def test_02_streak_forest_system(self):
        # Initial streak query
        headers = {"Authorization": f"Bearer {self.student_token}"}
        resp_get = client.get("/api/streaks", headers=headers)
        self.assertEqual(resp_get.status_code, 200)
        streak = resp_get.json()["streak"]
        self.assertGreaterEqual(streak["trees_count"], 1)

        # Record activity
        resp_rec = client.post("/api/streaks/record", json={}, headers=headers)
        self.assertEqual(resp_rec.status_code, 200)
        updated_streak = resp_rec.json()["streak"]
        self.assertIn("trees_count", updated_streak)
        self.assertIn("current_streak", updated_streak)
        self.assertIn("total_sprints", updated_streak)

    def test_03_mentor_mode_password_and_annotations(self):
        # 1. Create protected room with password
        room_id = "capstone_group_07"
        resp_create = client.post("/api/rooms/create", json={
            "room_id": room_id,
            "name": "Distributed Storage Lab",
            "language": "python",
            "password": "MentorPasscode2026",
            "is_private": True
        })
        self.assertEqual(resp_create.status_code, 200)

        # 2. Verify wrong password rejected
        resp_fail = client.post(f"/api/rooms/{room_id}/verify-password", json={"password": "wrong"})
        self.assertEqual(resp_fail.status_code, 200)
        self.assertFalse(resp_fail.json()["valid"])

        # 3. Verify correct password accepted for mentor entry
        resp_ok = client.post(f"/api/rooms/{room_id}/verify-password", json={"password": "MentorPasscode2026"})
        self.assertEqual(resp_ok.status_code, 200)
        self.assertTrue(resp_ok.json()["valid"])

        # 4. Mentor adds problematic line annotation
        mentor_headers = {"Authorization": f"Bearer {self.mentor_token}"}
        resp_ann = client.post(f"/api/rooms/{room_id}/annotations", json={
            "filename": "main.py",
            "line_number": 34,
            "comment": "Potential race condition in shared state buffer.",
            "problematic_level": "error"
        }, headers=mentor_headers)
        self.assertEqual(resp_ann.status_code, 200)
        ann_id = resp_ann.json()["annotation"]["id"]

        # 5. Fetch annotations
        resp_list = client.get(f"/api/rooms/{room_id}/annotations")
        self.assertEqual(resp_list.status_code, 200)
        annotations = resp_list.json()["annotations"]
        self.assertTrue(any(a["id"] == ann_id for a in annotations))

    def test_04_execution_endpoint_python(self):
        resp = client.post("/api/execute", json={
            "code": "print('College Project Testing - Total:', 5 * 20)",
            "language": "python"
        })
        self.assertEqual(resp.status_code, 200)
        res = resp.json()["result"]
        self.assertEqual(res["status"], "success")
        self.assertIn("College Project Testing - Total: 100", res["stdout"])


if __name__ == "__main__":
    unittest.main()
