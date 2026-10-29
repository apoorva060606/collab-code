"""
Real-Time Collaboration Hub for Coding Rooms.
Manages multi-room state, WebSocket connections, document synchronization,
remote cursors, multi-file and folder virtual tree, live chat, typing indicators,
Teacher/Mentor Mode with problematic line annotations, live coding broadcast,
task assignments, and streak celebrations.
"""

import json
import asyncio
import secrets
from datetime import datetime, timezone
from typing import Dict, Any, List, Set, Optional
from fastapi import WebSocket

import database

USER_COLORS = [
    "#3B82F6",  # Blue
    "#10B981",  # Emerald
    "#F59E0B",  # Amber
    "#EC4899",  # Pink
    "#8B5CF6",  # Purple
    "#06B6D4",  # Cyan
    "#EF4444",  # Red
    "#84CC16",  # Lime
    "#F97316",  # Orange
    "#14B8A6"   # Teal
]

DEFAULT_FILES = {
    "main.py": {
        "content": (
            "# Welcome to CollabCode Collaborative Platform!\n"
            "# Designed specifically for students and college project teams.\n\n"
            "def solve():\n"
            "    print('Hello, Collaborative World!')\n"
            "    data = [1, 2, 3, 4, 5]\n"
            "    total = sum(x * 2 for x in data)\n"
            "    print(f'Computed total: {total}')\n\n"
            "if __name__ == '__main__':\n"
            "    solve()\n"
        ),
        "language": "python"
    },
    "notes.md": {
        "content": (
            "# Room Scratchpad & Meeting Notes\n\n"
            "- Student-focused team collaboration enabled.\n"
            "- Multi-user simultaneous editing & cursor tracking.\n"
            "- Teacher/Mentor Mode with problematic line highlighting & real-time feedback.\n"
            "- Interactive Streak Forest visualizer active.\n"
        ),
        "language": "markdown"
    }
}


class Room:
    def __init__(self, room_id: str, name: str = "", language: str = "python", owner_id: str = ""):
        self.room_id = room_id
        self.name = name or f"Room-{room_id}"
        self.language = language
        self.owner_id = owner_id
        self.files: Dict[str, Dict[str, str]] = {
            fname: {"content": fval["content"], "language": fval["language"]}
            for fname, fval in DEFAULT_FILES.items()
        }
        self.active_file: str = "main.py"
        self.connections: Dict[str, WebSocket] = {}
        self.client_info: Dict[str, Dict[str, Any]] = {}
        self.chat_messages: List[Dict[str, Any]] = []
        self.broadcast_session: Dict[str, Any] = {"active": False, "mentor_name": "", "active_file": "main.py"}
        self._color_index: int = 0

    def get_next_color(self) -> str:
        color = USER_COLORS[self._color_index % len(USER_COLORS)]
        self._color_index += 1
        return color

    def add_client(self, client_id: str, websocket: WebSocket, user_data: Dict[str, Any]) -> Dict[str, Any]:
        color = self.get_next_color()
        user_id = user_data.get("id", f"guest_{secrets.token_hex(4)}")
        
        # Determine initial role
        role = user_data.get("role", "editor")
        if self.owner_id and user_id == self.owner_id:
            role = "owner"

        info = {
            "client_id": client_id,
            "user_id": user_id,
            "username": user_data.get("username", f"Coder_{client_id[:4]}"),
            "avatar_url": user_data.get("avatar_url", ""),
            "color": color,
            "role": role,  # 'owner', 'mentor', 'editor', 'viewer'
            "active_file": self.active_file,
            "cursor": {"line": 1, "column": 1, "selection": None}
        }
        self.connections[client_id] = websocket
        self.client_info[client_id] = info
        return info

    def remove_client(self, client_id: str) -> Optional[Dict[str, Any]]:
        self.connections.pop(client_id, None)
        return self.client_info.pop(client_id, None)

    def get_collaborators(self) -> List[Dict[str, Any]]:
        return list(self.client_info.values())

    def get_annotations(self) -> List[Dict[str, Any]]:
        return database.get_mentor_annotations(self.room_id)

    def get_state(self) -> Dict[str, Any]:
        meta = database.get_room_metadata(self.room_id) or {}
        return {
            "room_id": self.room_id,
            "name": self.name,
            "language": self.language,
            "owner_id": self.owner_id,
            "has_password": meta.get("has_password", False),
            "is_private": meta.get("is_private", False),
            "files": self.files,
            "active_file": self.active_file,
            "collaborators": self.get_collaborators(),
            "chat_messages": self.chat_messages[-50:],
            "annotations": self.get_annotations(),
            "broadcast_session": self.broadcast_session
        }


class CollaborationHub:
    def __init__(self):
        self.rooms: Dict[str, Room] = {}
        self._lock = asyncio.Lock()

    async def get_or_create_room(self, room_id: str, name: str = "", language: str = "python", owner_id: str = "") -> Room:
        async with self._lock:
            if room_id not in self.rooms:
                # Check if metadata exists in DB
                meta = database.get_room_metadata(room_id)
                if meta:
                    room_name = meta.get("name") or name or f"Room-{room_id}"
                    lang = meta.get("language") or language
                    owner = meta.get("owner_id") or owner_id
                else:
                    room_name = name or f"Room-{room_id}"
                    lang = language
                    owner = owner_id
                    database.upsert_room_metadata(room_id, room_name, lang, owner)

                self.rooms[room_id] = Room(room_id, room_name, lang, owner)
            return self.rooms[room_id]

    async def connect(self, room_id: str, client_id: str, websocket: WebSocket, user_data: Dict[str, Any]) -> Room:
        room = await self.get_or_create_room(room_id)
        info = room.add_client(client_id, websocket, user_data)
        
        # 1. Send initial state to connecting client
        await websocket.send_text(json.dumps({
            "type": "room_state",
            "self": info,
            "state": room.get_state()
        }))

        # 2. Broadcast user_joined to other participants
        await self.broadcast_to_room(
            room_id,
            {
                "type": "user_joined",
                "user": info
            },
            exclude_client=client_id
        )
        return room

    async def disconnect(self, room_id: str, client_id: str):
        if room_id in self.rooms:
            room = self.rooms[room_id]
            removed = room.remove_client(client_id)
            if removed:
                # If mentor was broadcasting, disable broadcast
                if room.broadcast_session.get("active") and removed.get("role") == "mentor":
                    room.broadcast_session = {"active": False, "mentor_name": "", "active_file": "main.py"}
                    await self.broadcast_to_room(room_id, {
                        "type": "mentor_broadcast_mode",
                        "active": False
                    })

                await self.broadcast_to_room(
                    room_id,
                    {
                        "type": "user_left",
                        "client_id": client_id,
                        "username": removed["username"]
                    }
                )

    async def broadcast_to_room(self, room_id: str, message: Dict[str, Any], exclude_client: Optional[str] = None):
        if room_id not in self.rooms:
            return
        
        room = self.rooms[room_id]
        payload = json.dumps(message)
        dead_clients = []

        for cid, ws in list(room.connections.items()):
            if exclude_client and cid == exclude_client:
                continue
            try:
                await ws.send_text(payload)
            except Exception:
                dead_clients.append(cid)

        for cid in dead_clients:
            room.remove_client(cid)

    async def handle_message(self, room_id: str, client_id: str, data: Dict[str, Any]):
        if room_id not in self.rooms:
            return
        
        room = self.rooms[room_id]
        sender_info = room.client_info.get(client_id, {})
        sender_role = sender_info.get("role", "editor")
        msg_type = data.get("type")

        # Check viewer permissions for write actions
        if sender_role == "viewer" and msg_type in ("code_change", "file_create", "file_delete", "file_rename", "folder_create", "folder_delete"):
            # Viewers are read-only
            return

        if msg_type == "code_change":
            filename = data.get("filename", room.active_file)
            content = data.get("content", "")
            if filename in room.files:
                room.files[filename]["content"] = content
            else:
                room.files[filename] = {"content": content, "language": data.get("language", "python")}

            await self.broadcast_to_room(
                room_id,
                {
                    "type": "code_change",
                    "filename": filename,
                    "content": content,
                    "sender_id": client_id
                },
                exclude_client=client_id
            )

        elif msg_type == "cursor_move":
            cursor_data = data.get("cursor", {})
            active_file = data.get("filename", room.active_file)
            if client_id in room.client_info:
                room.client_info[client_id]["cursor"] = cursor_data
                room.client_info[client_id]["active_file"] = active_file

            await self.broadcast_to_room(
                room_id,
                {
                    "type": "cursor_move",
                    "client_id": client_id,
                    "cursor": cursor_data,
                    "filename": active_file
                },
                exclude_client=client_id
            )

            # If mentor is conducting live broadcast session, students follow
            if room.broadcast_session.get("active") and sender_role == "mentor":
                room.broadcast_session["active_file"] = active_file
                await self.broadcast_to_room(
                    room_id,
                    {
                        "type": "mentor_broadcast_follow",
                        "mentor_name": sender_info.get("username", "Mentor"),
                        "filename": active_file,
                        "cursor": cursor_data
                    },
                    exclude_client=client_id
                )

        elif msg_type == "file_create":
            filename = data.get("filename", "").strip()
            language = data.get("language", "python")
            initial_content = data.get("content", f"# {filename}\n")
            if filename and filename not in room.files:
                room.files[filename] = {"content": initial_content, "language": language}
                await self.broadcast_to_room(
                    room_id,
                    {
                        "type": "file_created",
                        "filename": filename,
                        "language": language,
                        "content": initial_content,
                        "creator": sender_info.get("username", "Someone")
                    }
                )

        elif msg_type == "file_rename":
            old_name = data.get("old_filename", "").strip()
            new_name = data.get("new_filename", "").strip()
            if old_name and new_name and old_name in room.files and new_name not in room.files:
                file_obj = room.files.pop(old_name)
                room.files[new_name] = file_obj
                if room.active_file == old_name:
                    room.active_file = new_name
                await self.broadcast_to_room(
                    room_id,
                    {
                        "type": "file_renamed",
                        "old_filename": old_name,
                        "new_filename": new_name,
                        "active_file": room.active_file
                    }
                )

        elif msg_type == "file_delete":
            filename = data.get("filename")
            if filename and filename in room.files and len(room.files) > 1:
                del room.files[filename]
                if room.active_file == filename:
                    room.active_file = next(iter(room.files.keys()))
                await self.broadcast_to_room(
                    room_id,
                    {
                        "type": "file_deleted",
                        "filename": filename,
                        "active_file": room.active_file
                    }
                )

        elif msg_type == "folder_create":
            folder_name = data.get("folder_name", "").strip().rstrip("/")
            if folder_name:
                placeholder_file = f"{folder_name}/README.md"
                if placeholder_file not in room.files:
                    room.files[placeholder_file] = {
                        "content": f"# Directory: {folder_name}\nFiles in this module.\n",
                        "language": "markdown"
                    }
                    await self.broadcast_to_room(
                        room_id,
                        {
                            "type": "folder_created",
                            "folder_name": folder_name,
                            "placeholder_file": placeholder_file,
                            "files": room.files
                        }
                    )

        elif msg_type == "folder_delete":
            folder_name = data.get("folder_name", "").strip().rstrip("/")
            if folder_name:
                prefix = f"{folder_name}/"
                to_delete = [f for f in room.files if f.startswith(prefix)]
                for f in to_delete:
                    if len(room.files) > 1:
                        del room.files[f]
                if room.active_file not in room.files:
                    room.active_file = next(iter(room.files.keys()))
                await self.broadcast_to_room(
                    room_id,
                    {
                        "type": "folder_deleted",
                        "folder_name": folder_name,
                        "files": room.files,
                        "active_file": room.active_file
                    }
                )

        elif msg_type == "chat_message":
            text = data.get("text", "").strip()
            snippet = data.get("snippet", "")
            snippet_lang = data.get("snippet_language", "python")
            if (text or snippet) and client_id in room.client_info:
                msg = {
                    "id": f"msg_{secrets.token_hex(4)}",
                    "user_id": sender_info["user_id"],
                    "username": sender_info["username"],
                    "color": sender_info["color"],
                    "role": sender_info.get("role", "editor"),
                    "avatar_url": sender_info.get("avatar_url", ""),
                    "text": text,
                    "snippet": snippet,
                    "snippet_language": snippet_lang,
                    "timestamp": datetime.now(timezone.utc).strftime("%H:%M")
                }
                room.chat_messages.append(msg)
                if len(room.chat_messages) > 100:
                    room.chat_messages.pop(0)

                await self.broadcast_to_room(
                    room_id,
                    {
                        "type": "chat_message",
                        "message": msg
                    }
                )

        elif msg_type == "typing":
            is_typing = data.get("is_typing", False)
            await self.broadcast_to_room(
                room_id,
                {
                    "type": "typing_status",
                    "client_id": client_id,
                    "username": sender_info.get("username", "Collaborator"),
                    "is_typing": is_typing
                },
                exclude_client=client_id
            )

        # --- Teacher / Mentor Mode Messages ---
        elif msg_type == "mentor_highlight_line":
            filename = data.get("filename", room.active_file)
            line_num = int(data.get("line_number", 1))
            comment = data.get("comment", "").strip()
            level = data.get("problematic_level", "warning")
            author = sender_info.get("username", "Mentor")

            ann = database.add_mentor_annotation(
                room_id=room_id,
                filename=filename,
                line_number=line_num,
                comment=comment,
                problematic_level=level,
                author_name=author
            )

            await self.broadcast_to_room(
                room_id,
                {
                    "type": "mentor_annotation_added",
                    "annotation": ann
                }
            )

        elif msg_type == "mentor_remove_annotation":
            ann_id = data.get("annotation_id")
            if ann_id:
                database.delete_mentor_annotation(ann_id)
                await self.broadcast_to_room(
                    room_id,
                    {
                        "type": "mentor_annotation_removed",
                        "annotation_id": ann_id
                    }
                )

        elif msg_type == "mentor_broadcast_toggle":
            enabled = bool(data.get("enabled", False))
            room.broadcast_session = {
                "active": enabled,
                "mentor_name": sender_info.get("username", "Mentor"),
                "active_file": room.active_file
            }
            await self.broadcast_to_room(
                room_id,
                {
                    "type": "mentor_broadcast_mode",
                    "active": enabled,
                    "mentor_name": sender_info.get("username", "Mentor"),
                    "active_file": room.active_file
                }
            )

        elif msg_type == "mentor_assign_task":
            # Mentor assigns task directly to room / project
            title = data.get("title", "").strip()
            desc = data.get("description", "").strip()
            assignee = data.get("assigned_to", "").strip()
            priority = data.get("priority", "medium")
            project_id = data.get("project_id", "")

            task_obj = None
            if project_id:
                task_obj = database.create_task(
                    project_id=project_id,
                    title=title,
                    description=desc,
                    assigned_to=assignee,
                    priority=priority,
                    created_by=sender_info.get("username", "Mentor")
                )

            await self.broadcast_to_room(
                room_id,
                {
                    "type": "mentor_task_assigned",
                    "task": task_obj or {
                        "id": f"task_{secrets.token_hex(4)}",
                        "title": title,
                        "description": desc,
                        "assigned_to": assignee,
                        "priority": priority,
                        "status": "todo"
                    },
                    "mentor_name": sender_info.get("username", "Mentor")
                }
            )

        elif msg_type == "mentor_feedback":
            # Broadcast grade / feedback notification
            await self.broadcast_to_room(
                room_id,
                {
                    "type": "mentor_feedback_given",
                    "grade_score": data.get("grade_score"),
                    "feedback": data.get("feedback"),
                    "mentor_name": sender_info.get("username", "Mentor")
                }
            )

        # --- Room Management & Permissions ---
        elif msg_type == "set_role":
            # Check room password for mentor escalation or owner permission
            requested_role = data.get("role")
            room_pwd = data.get("password", "")

            if requested_role == "mentor":
                if database.verify_room_password(room_id, room_pwd):
                    sender_info["role"] = "mentor"
                    await self.broadcast_to_room(
                        room_id,
                        {
                            "type": "user_role_changed",
                            "client_id": client_id,
                            "role": "mentor",
                            "username": sender_info["username"]
                        }
                    )
                else:
                    # Password incorrect
                    ws = room.connections.get(client_id)
                    if ws:
                        await ws.send_text(json.dumps({
                            "type": "auth_error",
                            "message": "Incorrect room password for Mentor Mode access."
                        }))

        elif msg_type == "kick_user":
            if sender_role in ("owner", "mentor"):
                target_client_id = data.get("target_client_id")
                if target_client_id in room.connections:
                    target_ws = room.connections[target_client_id]
                    await target_ws.send_text(json.dumps({
                        "type": "kicked",
                        "message": "You were removed from this room by the host."
                    }))
                    await target_ws.close()
                    room.remove_client(target_client_id)
                    await self.broadcast_to_room(room_id, {
                        "type": "user_kicked",
                        "client_id": target_client_id
                    })

        elif msg_type == "streak_celebration":
            # Student maintained streak
            trees = data.get("trees_count", 1)
            streak_days = data.get("current_streak", 1)
            await self.broadcast_to_room(
                room_id,
                {
                    "type": "streak_celebration",
                    "username": sender_info.get("username", "Coder"),
                    "trees_count": trees,
                    "current_streak": streak_days
                }
            )

        elif msg_type == "code_executed":
            await self.broadcast_to_room(
                room_id,
                {
                    "type": "code_executed",
                    "result": data.get("result"),
                    "runner": sender_info.get("username", "Someone")
                }
            )


hub = CollaborationHub()
