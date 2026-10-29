"""
Main Server Application for Collaborative Coding Platform.
Provides REST APIs for:
- Student-Focused Collaboration (Create Team, Projects, Tasks, Submissions, Progress)
- Teacher / Mentor Mode (Room password access, real-time code watch, problematic line highlights, feedback, task assignments, live coding broadcast)
- Maintaining Streak Forest Feature (Interactive Tree Forest, Single & Group Streaks)
- Monaco Editor code execution sandbox (Python, C, C++, Java, JavaScript)
- Real-time Multi-Room WebSocket Hub with cursors, chat, and file operations.
"""

import os
import json
import secrets
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Header, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, EmailStr, Field

import database
import optimizer
import executor
from collab_hub import hub

app = FastAPI(title="CollabCode Platform API - Student & Mentor Edition", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

os.makedirs(os.path.join(STATIC_DIR, "css"), exist_ok=True)
os.makedirs(os.path.join(STATIC_DIR, "js"), exist_ok=True)


# --- Request/Response Models ---
class SignUpRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=30)
    email: EmailStr
    password: str = Field(..., min_length=6)

class LoginRequest(BaseModel):
    identifier: str
    password: str

class VerifyEmailRequest(BaseModel):
    token: str

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=6)

class ProfileUpdateRequest(BaseModel):
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    username: Optional[str] = None

class OptimizeRequest(BaseModel):
    code: str
    language: str = "python"

class ExecuteRequest(BaseModel):
    code: str
    language: str = "python"
    stdin: Optional[str] = ""
    timeout: float = 7.0

# Student Team & Project Models
class CreateTeamRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=50)
    description: Optional[str] = ""
    avatar_color: Optional[str] = None

class JoinTeamRequest(BaseModel):
    invite_code: str

class CreateProjectRequest(BaseModel):
    team_id: str
    name: str = Field(..., min_length=2, max_length=60)
    description: Optional[str] = ""
    room_id: Optional[str] = None
    language: str = "python"

class CreateTaskRequest(BaseModel):
    title: str = Field(..., min_length=2, max_length=100)
    description: Optional[str] = ""
    assigned_to: Optional[str] = ""
    priority: str = "medium"
    due_date: Optional[str] = ""

class UpdateTaskRequest(BaseModel):
    status: Optional[str] = None
    assigned_to: Optional[str] = None
    title: Optional[str] = None
    priority: Optional[str] = None

class SubmitProjectRequest(BaseModel):
    submission_title: str
    repository_notes: Optional[str] = ""
    files_snapshot_json: Optional[str] = "{}"

class GradeSubmissionRequest(BaseModel):
    grade_score: int = Field(..., ge=0, le=100)
    feedback: str

# Room & Streak Models
class CreateRoomRequest(BaseModel):
    room_id: str = Field(..., min_length=3)
    name: str
    language: str = "python"
    password: Optional[str] = ""
    is_private: bool = False

class VerifyPasswordRequest(BaseModel):
    password: str

class RecordStreakRequest(BaseModel):
    team_id: Optional[str] = None

class MentorAnnotationRequest(BaseModel):
    filename: str
    line_number: int
    comment: str
    problematic_level: str = "warning"


# --- Auth Dependency ---
def get_current_user(authorization: Optional[str] = Header(None)) -> Optional[Dict[str, Any]]:
    if not authorization:
        return None
    token = authorization.replace("Bearer ", "").strip()
    if not token:
        return None
    return database.get_user_by_session(token)

def require_current_user(user: Optional[Dict[str, Any]] = Depends(get_current_user)) -> Dict[str, Any]:
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


# =========================================================================
# Authentication Endpoints
# =========================================================================
@app.post("/api/auth/signup")
async def signup(req: SignUpRequest):
    try:
        user_info = database.create_user(req.username, req.email, req.password)
        session_token = database.create_session(user_info["id"])
        return {
            "success": True,
            "message": "Account created successfully! Verification link generated.",
            "user": {
                "id": user_info["id"],
                "username": user_info["username"],
                "email": user_info["email"],
                "is_verified": False,
                "avatar_url": user_info["avatar_url"]
            },
            "token": session_token,
            "verification_token": user_info["verification_token"]
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/auth/login")
async def login(req: LoginRequest):
    user = database.authenticate_user(req.identifier, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username/email or password.")
    
    session_token = database.create_session(user["id"])
    return {
        "success": True,
        "message": f"Welcome back, {user['username']}!",
        "user": user,
        "token": session_token
    }


@app.post("/api/auth/logout")
async def logout(authorization: Optional[str] = Header(None)):
    if authorization:
        token = authorization.replace("Bearer ", "").strip()
        database.delete_session(token)
    return {"success": True, "message": "Logged out successfully."}


@app.get("/api/auth/me")
async def get_me(user: Dict[str, Any] = Depends(require_current_user)):
    return {"success": True, "user": user}


@app.put("/api/auth/profile")
async def update_profile(req: ProfileUpdateRequest, user: Dict[str, Any] = Depends(require_current_user)):
    try:
        updated = database.update_user_profile(
            user["id"],
            bio=req.bio,
            avatar_url=req.avatar_url,
            username=req.username
        )
        return {"success": True, "user": updated, "message": "Profile updated successfully."}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/auth/verify-email")
async def verify_email(req: VerifyEmailRequest):
    success = database.verify_email_with_token(req.token)
    if not success:
        raise HTTPException(status_code=400, detail="Invalid or expired verification token.")
    return {"success": True, "message": "Email address successfully verified!"}


@app.post("/api/auth/forgot-password")
async def forgot_password(req: ForgotPasswordRequest):
    token = database.request_password_reset(req.email)
    return {
        "success": True,
        "message": "If this email is registered, a password reset link has been dispatched.",
        "reset_token": token
    }


@app.post("/api/auth/reset-password")
async def reset_password(req: ResetPasswordRequest):
    try:
        success = database.reset_password_with_token(req.token, req.new_password)
        if not success:
            raise HTTPException(status_code=400, detail="Invalid or expired reset token.")
        return {"success": True, "message": "Password has been successfully reset! You can now login."}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/dev/outbox")
async def dev_outbox():
    items = database.get_latest_dev_outbox(10)
    return {"success": True, "outbox": items}


# =========================================================================
# Student-Focused Collaboration: Teams & College Projects
# =========================================================================

@app.post("/api/teams")
async def create_team(req: CreateTeamRequest, user: Dict[str, Any] = Depends(require_current_user)):
    try:
        team = database.create_team(req.name, req.description or "", user["id"], req.avatar_color)
        return {"success": True, "team": team}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/teams")
async def list_teams(user: Dict[str, Any] = Depends(require_current_user)):
    teams = database.get_user_teams(user["id"])
    return {"success": True, "teams": teams}


@app.get("/api/teams/{team_id}")
async def get_team(team_id: str, user: Dict[str, Any] = Depends(require_current_user)):
    team = database.get_team_details(team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found.")
    return {"success": True, "team": team}


@app.post("/api/teams/join")
async def join_team(req: JoinTeamRequest, user: Dict[str, Any] = Depends(require_current_user)):
    team = database.join_team_by_code(req.invite_code, user["id"])
    if not team:
        raise HTTPException(status_code=404, detail="Invalid invite code.")
    return {"success": True, "message": f"Successfully joined team '{team['name']}'!", "team": team}


@app.post("/api/projects")
async def create_project(req: CreateProjectRequest, user: Dict[str, Any] = Depends(require_current_user)):
    try:
        project = database.create_project(
            team_id=req.team_id,
            name=req.name,
            description=req.description or "",
            room_id=req.room_id,
            language=req.language
        )
        # Register room in metadata with project language and owner
        database.upsert_room_metadata(project["room_id"], project["name"], project["language"], user["id"])
        return {"success": True, "project": project}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str):
    project = database.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    return {"success": True, "project": project}


@app.post("/api/projects/{project_id}/tasks")
async def add_task(project_id: str, req: CreateTaskRequest, user: Dict[str, Any] = Depends(require_current_user)):
    try:
        task = database.create_task(
            project_id=project_id,
            title=req.title,
            description=req.description or "",
            assigned_to=req.assigned_to or "",
            priority=req.priority,
            due_date=req.due_date or "",
            created_by=user["username"]
        )
        return {"success": True, "task": task}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/projects/tasks/{task_id}")
async def update_task_endpoint(task_id: str, req: UpdateTaskRequest):
    updated = database.update_task(
        task_id=task_id,
        status=req.status,
        assigned_to=req.assigned_to,
        title=req.title,
        priority=req.priority
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Task not found.")
    return {"success": True, "task": updated}


@app.delete("/api/projects/tasks/{task_id}")
async def delete_task_endpoint(task_id: str):
    success = database.delete_task(task_id)
    return {"success": success}


@app.post("/api/projects/{project_id}/submit")
async def submit_project_endpoint(project_id: str, req: SubmitProjectRequest, user: Dict[str, Any] = Depends(require_current_user)):
    project = database.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    
    sub = database.submit_project(
        project_id=project_id,
        team_id=project["team_id"],
        submitted_by=user["username"],
        submission_title=req.submission_title,
        repository_notes=req.repository_notes or "",
        files_snapshot_json=req.files_snapshot_json or "{}"
    )
    return {"success": True, "submission": sub, "message": "Project successfully submitted for evaluation!"}


@app.post("/api/projects/submissions/{submission_id}/grade")
async def grade_submission_endpoint(submission_id: str, req: GradeSubmissionRequest, user: Dict[str, Any] = Depends(require_current_user)):
    graded = database.grade_submission(
        submission_id=submission_id,
        grade_score=req.grade_score,
        feedback=req.feedback,
        graded_by=user["username"]
    )
    if not graded:
        raise HTTPException(status_code=404, detail="Submission not found.")
    return {"success": True, "submission": graded, "message": "Feedback and grade submitted successfully."}


# =========================================================================
# Maintaining Streak & Interactive Tree Forest Feature
# =========================================================================

@app.get("/api/streaks")
async def get_streak_endpoint(team_id: Optional[str] = None, user: Optional[Dict[str, Any]] = Depends(get_current_user)):
    user_id = user["id"] if user else None
    streak_data = database.get_streak(user_id=user_id, team_id=team_id)
    return {"success": True, "streak": streak_data}


@app.post("/api/streaks/record")
async def record_streak_endpoint(req: RecordStreakRequest, user: Optional[Dict[str, Any]] = Depends(get_current_user)):
    user_id = user["id"] if user else None
    result = database.record_activity(user_id=user_id, team_id=req.team_id)
    return {"success": True, "streak": result}


# =========================================================================
# Room Metadata & Password Management (Teacher / Mentor Access)
# =========================================================================

@app.post("/api/rooms/create")
async def create_room_endpoint(req: CreateRoomRequest, user: Optional[Dict[str, Any]] = Depends(get_current_user)):
    owner_id = user["id"] if user else ""
    meta = database.upsert_room_metadata(
        room_id=req.room_id,
        name=req.name,
        language=req.language,
        owner_id=owner_id,
        password=req.password or "",
        is_private=req.is_private
    )
    await hub.get_or_create_room(req.room_id, req.name, req.language, owner_id)
    return {"success": True, "room": meta}


@app.get("/api/rooms/{room_id}/meta")
async def get_room_meta(room_id: str):
    meta = database.get_room_metadata(room_id)
    if not meta:
        return {"success": True, "room": {"room_id": room_id, "name": f"Room-{room_id}", "language": "python", "has_password": False, "is_private": False}}
    return {"success": True, "room": meta}


@app.post("/api/rooms/{room_id}/verify-password")
async def verify_password_endpoint(room_id: str, req: VerifyPasswordRequest):
    is_valid = database.verify_room_password(room_id, req.password)
    return {"success": True, "valid": is_valid}


@app.delete("/api/rooms/{room_id}")
async def delete_room_endpoint(room_id: str, user: Dict[str, Any] = Depends(require_current_user)):
    meta = database.get_room_metadata(room_id)
    if meta and meta.get("owner_id") and meta["owner_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Only room owner can delete this room.")
    database.delete_room_record(room_id)
    return {"success": True, "message": "Room deleted successfully."}


# =========================================================================
# Teacher / Mentor Problematic Line Annotations
# =========================================================================

@app.get("/api/rooms/{room_id}/annotations")
async def get_annotations(room_id: str, filename: Optional[str] = None):
    ann = database.get_mentor_annotations(room_id, filename)
    return {"success": True, "annotations": ann}


@app.post("/api/rooms/{room_id}/annotations")
async def create_annotation(room_id: str, req: MentorAnnotationRequest, user: Optional[Dict[str, Any]] = Depends(get_current_user)):
    author_name = user["username"] if user else "Mentor"
    ann = database.add_mentor_annotation(
        room_id=room_id,
        filename=req.filename,
        line_number=req.line_number,
        comment=req.comment,
        problematic_level=req.problematic_level,
        author_name=author_name
    )
    await hub.broadcast_to_room(room_id, {"type": "mentor_annotation_added", "annotation": ann})
    return {"success": True, "annotation": ann}


@app.delete("/api/annotations/{annotation_id}")
async def delete_annotation(annotation_id: str, room_id: Optional[str] = Query(None)):
    success = database.delete_mentor_annotation(annotation_id)
    if success and room_id:
        await hub.broadcast_to_room(room_id, {"type": "mentor_annotation_removed", "annotation_id": annotation_id})
    return {"success": success}


# =========================================================================
# Notifications Center
# =========================================================================

@app.get("/api/notifications")
async def list_notifications(user: Dict[str, Any] = Depends(require_current_user)):
    notifs = database.get_user_notifications(user["id"])
    return {"success": True, "notifications": notifs}


@app.post("/api/notifications/{notification_id}/read")
async def mark_read(notification_id: str):
    success = database.mark_notification_read(notification_id)
    return {"success": success}


# =========================================================================
# Code Optimizer & Sandbox Execution APIs
# =========================================================================

@app.post("/api/optimize")
async def optimize_code(req: OptimizeRequest):
    analysis = optimizer.analyze_code_for_optimizations(req.code, req.language)
    return {"success": True, "data": analysis}


@app.post("/api/execute")
async def execute(req: ExecuteRequest):
    result = executor.execute_code(req.code, req.language, stdin=req.stdin or "", timeout=req.timeout)
    return {"success": True, "result": result}


@app.get("/api/rooms/{room_id}")
async def get_room(room_id: str):
    room = await hub.get_or_create_room(room_id)
    return {"success": True, "room": room.get_state()}


# =========================================================================
# WebSocket Real-Time Collaboration Endpoint
# =========================================================================

@app.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str):
    await websocket.accept()
    client_id = f"c_{secrets.token_hex(4)}"
    
    # Query parameters / handshake
    token = websocket.query_params.get("token")
    requested_role = websocket.query_params.get("role", "editor")
    password = websocket.query_params.get("password", "")
    
    user_data = {}
    if token:
        u = database.get_user_by_session(token)
        if u:
            user_data = dict(u)
    
    if not user_data:
        guest_name = websocket.query_params.get("username", f"Coder_{secrets.token_hex(2)}")
        user_data = {
            "id": f"guest_{secrets.token_hex(4)}",
            "username": guest_name,
            "avatar_url": f"https://api.dicebear.com/7.x/bottts/svg?seed={guest_name}"
        }

    # Verify mentor mode password if mentor requested
    if requested_role == "mentor":
        if database.verify_room_password(room_id, password):
            user_data["role"] = "mentor"
        else:
            user_data["role"] = "viewer"  # Fallback to viewer if password failed
    else:
        user_data["role"] = requested_role

    await hub.connect(room_id, client_id, websocket, user_data)
    
    try:
        while True:
            text_data = await websocket.receive_text()
            try:
                data = json.loads(text_data)
                await hub.handle_message(room_id, client_id, data)
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        await hub.disconnect(room_id, client_id)
    except Exception:
        await hub.disconnect(room_id, client_id)


# =========================================================================
# Static and HTML Routes
# =========================================================================

@app.get("/")
async def serve_index():
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return JSONResponse({"status": "Server running", "message": "Frontend static files are being initialized."})

@app.get("/room/{room_id}")
async def serve_room(room_id: str):
    index_file = os.path.join(STATIC_DIR, "index.html")
    return FileResponse(index_file)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
