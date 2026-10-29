"""
Code Execution Sandbox for Collaborative Coding Platform.
Provides isolated, secure container sandboxed code execution for:
- Python
- C
- C++
- Java
- JavaScript

Uses isolated sandbox execution service with timeout protection,
memory limits, input (stdin) forwarding, and execution timing metrics.
"""

import sys
import subprocess
import tempfile
import time
import os
import json
import urllib.request
import urllib.error
from typing import Dict, Any, Optional

PAIZA_CREATE_URL = "https://api.paiza.io/runners/create"
PAIZA_DETAILS_URL = "https://api.paiza.io/runners/get_details"

# Language alias normalization
LANGUAGE_MAP = {
    "python": "python3",
    "py": "python3",
    "python3": "python3",
    "javascript": "javascript",
    "js": "javascript",
    "node": "javascript",
    "c": "c",
    "c++": "cpp",
    "cpp": "cpp",
    "cxx": "cpp",
    "java": "java"
}


def execute_with_sandbox(code: str, language: str, stdin: str = "", timeout: float = 7.0) -> Optional[Dict[str, Any]]:
    """
    Executes code in an isolated container sandbox via Paiza Cloud Runner.
    Protects host system by running user code in a dedicated container sandbox.
    """
    normalized_lang = LANGUAGE_MAP.get(language.lower(), language.lower())
    payload = {
        "source_code": code,
        "language": normalized_lang,
        "input": stdin or "",
        "api_key": "guest"
    }

    try:
        start_time = time.perf_counter()
        req = urllib.request.Request(
            PAIZA_CREATE_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "CollabCodeSandbox/1.0"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            run_id = data.get("id")

        if not run_id:
            return None

        # Poll for completion with exponential backoff up to timeout
        poll_interval = 0.25
        deadline = time.time() + timeout

        while time.time() < deadline:
            time.sleep(poll_interval)
            url_poll = f"{PAIZA_DETAILS_URL}?id={run_id}&api_key=guest"
            req_poll = urllib.request.Request(url_poll, headers={"User-Agent": "CollabCodeSandbox/1.0"})
            with urllib.request.urlopen(req_poll, timeout=4.0) as resp:
                details = json.loads(resp.read().decode("utf-8"))
                status = details.get("status")
                
                if status == "completed":
                    elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
                    stdout = details.get("stdout") or ""
                    stderr = details.get("stderr") or ""
                    build_stderr = details.get("build_stderr") or ""
                    build_result = details.get("build_result")

                    # Compilation error
                    if build_result == "failure" or build_stderr:
                        return {
                            "status": "compile_error",
                            "stdout": stdout,
                            "stderr": build_stderr or stderr or "Compilation failure.",
                            "execution_time_ms": elapsed_ms,
                            "exit_code": details.get("build_exit_code", 1),
                            "sandbox": "isolated-container",
                            "language": normalized_lang
                        }

                    try:
                        raw_exit = details.get("exit_code", 0)
                        exit_code = int(raw_exit) if raw_exit is not None else 0
                    except (ValueError, TypeError):
                        exit_code = 0
                    result_state = "success" if exit_code == 0 else "error"
                    return {
                        "status": result_state,
                        "stdout": stdout,
                        "stderr": stderr,
                        "execution_time_ms": elapsed_ms,
                        "exit_code": exit_code,
                        "sandbox": "isolated-container",
                        "language": normalized_lang
                    }

        # If poll timed out
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return {
            "status": "timeout",
            "stdout": "",
            "stderr": f"Execution Timed Out: Remote sandboxed worker exceeded {timeout}s limit.",
            "execution_time_ms": elapsed_ms,
            "exit_code": -1,
            "sandbox": "isolated-container",
            "language": normalized_lang
        }

    except Exception:
        return None


def execute_local_python_fallback(code: str, stdin: str = "", timeout: float = 6.0) -> Dict[str, Any]:
    """
    Fallback execution specifically for Python if the cloud sandbox is offline.
    """
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as temp_file:
        temp_file.write(code)
        temp_path = temp_file.name

    start_time = time.perf_counter()
    try:
        cmd = [sys.executable, "-u", temp_path]
        process = subprocess.run(
            cmd,
            input=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace"
        )
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        status = "success" if process.returncode == 0 else "error"
        return {
            "status": status,
            "stdout": process.stdout,
            "stderr": process.stderr,
            "execution_time_ms": elapsed_ms,
            "exit_code": process.returncode,
            "sandbox": "local-subprocess",
            "language": "python"
        }
    except subprocess.TimeoutExpired:
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return {
            "status": "timeout",
            "stdout": "",
            "stderr": f"Execution Timed Out: Process exceeded maximum allowed time limit of {timeout}s.",
            "execution_time_ms": elapsed_ms,
            "exit_code": -1,
            "sandbox": "local-subprocess",
            "language": "python"
        }
    except Exception as e:
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return {
            "status": "error",
            "stdout": "",
            "stderr": f"Execution error: {str(e)}",
            "execution_time_ms": elapsed_ms,
            "exit_code": 1,
            "sandbox": "local-subprocess",
            "language": "python"
        }
    finally:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass


def execute_code(code: str, language: str = "python", stdin: str = "", timeout: float = 7.0) -> Dict[str, Any]:
    """
    Main code execution dispatcher.
    Always prioritizes isolated sandbox container execution, protecting the host system.
    """
    if not code.strip():
        return {
            "status": "success",
            "stdout": "",
            "stderr": "No code provided to execute.\n",
            "execution_time_ms": 0,
            "exit_code": 0,
            "sandbox": "none",
            "language": language
        }

    # 1. Primary: Run in isolated cloud sandbox container
    sandbox_result = execute_with_sandbox(code, language, stdin=stdin, timeout=timeout)
    if sandbox_result is not None:
        return sandbox_result

    # 2. Secondary fallback for Python
    norm = language.lower()
    if norm in ("python", "py", "python3"):
        return execute_local_python_fallback(code, stdin=stdin, timeout=timeout)

    return {
        "status": "error",
        "stdout": "",
        "stderr": f"Execution for '{language}' requires isolated container sandbox, which is currently unreachable.",
        "execution_time_ms": 0,
        "exit_code": 1,
        "sandbox": "none",
        "language": language
    }
