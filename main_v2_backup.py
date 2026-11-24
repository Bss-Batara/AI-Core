import requests
import json
import shutil
import difflib
from datetime import datetime
from pathlib import Path

from tools.list_files import list_files
from tools.read_file import read_file
from tools.write_file import write_file


# ==========================================
# AI CORE ENGINE V2
# ==========================================

BASE_DIR = Path(__file__).parent.resolve()
RULES_FILE = BASE_DIR / "CORE_RULES.md"
MEMORY_FILE = BASE_DIR / "PROJECT_MEMORY.md"

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen2.5-coder:3b"

MAX_ACTIONS = 5
TIMEOUT = 240

BACKUP_DIR = BASE_DIR / "_backups"


# ==========================================
# CONTEXT
# ==========================================

def load_context():

    rules = RULES_FILE.read_text(encoding="utf-8") if RULES_FILE.exists() else ""
    memory = MEMORY_FILE.read_text(encoding="utf-8") if MEMORY_FILE.exists() else ""

    return f"""
{rules}

PROJECT MEMORY:
{memory}

PROJECT ROOT:
{BASE_DIR}

You are AI-Core, a software engineering assistant.
"""


# ==========================================
# SECURITY
# ==========================================

def safe_path(file_path):

    target = (BASE_DIR / file_path).resolve()

    if not target.is_relative_to(BASE_DIR):
        raise ValueError("Access outside project prohibited.")

    return target


# ==========================================
# FILE TOOLS
# ==========================================

def scan_project():

    return list_files(str(BASE_DIR))


def read_project_file(file_path):

    try:

        target = safe_path(file_path)

        if not target.is_file():
            return f"Error: File not found: {file_path}"

        return read_file(str(target))

    except Exception as e:

        return f"Error: {e}"


def create_backup(target):

    if not target.exists():
        return None

    BACKUP_DIR.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    backup_name = f"{target.name}_{timestamp}.bak"

    backup_path = BACKUP_DIR / backup_name

    shutil.copy2(target, backup_path)

    return backup_path


def write_project_file(file_path, content):

    try:

        target = safe_path(file_path)

        backup = create_backup(target)

        result = write_file(
            str(BASE_DIR),
            file_path,
            content
        )

        return result, backup

    except Exception as e:

        return f"Error: {e}", None


# ==========================================
# OLLAMA
# ==========================================

def call_ai(messages):

    payload = {
        "model": MODEL,
        "stream": False,
        "messages": messages,
        "options": {
            "temperature": 0.1
        }
    }

    response = requests.post(
        OLLAMA_URL,
        json=payload,
        timeout=TIMEOUT
    )

    response.raise_for_status()

    result = response.json()

    content = result.get("message", {}).get("content", "")

    if not content or not content.strip():

        raise ValueError("Model returned empty response.")

    return content


# ==========================================
# JSON HANDLER
# ==========================================

def extract_json(text):

    text = text.strip()

    # Remove markdown fences
    if text.startswith("```"):

        text = text.replace("```json", "")
        text = text.replace("```", "")
        text = text.strip()

    # Direct JSON
    try:

        return json.loads(text)

    except json.JSONDecodeError:

        pass

    # Attempt extraction from surrounding text
    start = text.find("{")
    end = text.rfind("}")

    if start != -1 and end != -1 and end > start:

        candidate = text[start:end + 1]

        return json.loads(candidate)

    raise ValueError("No valid JSON found in model response.")


# ==========================================
# DIFF PREVIEW
# ==========================================

def show_diff(old_content, new_content, file_path):

    old_lines = old_content.splitlines()
    new_lines = new_content.splitlines()

    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"Original: {file_path}",
        tofile=f"Modified: {file_path}",
        lineterm=""
    )

    print("\nCHANGE PREVIEW:\n")

    diff_text = "\n".join(diff)

    if diff_text:

        print(diff_text)

    else:

        print("No changes detected.")


# ==========================================
# AGENT SYSTEM PROMPT
# ==========================================

AGENT_INSTRUCTIONS = """

You are AI-Core Autonomous Coding Agent.

Return ONLY valid JSON.
Do not use markdown fences.

AVAILABLE ACTIONS:

READ:
{"action":"read_file","path":"filename.py"}

WRITE:
{"action":"write_file","path":"filename.py","content":"complete code"}

ANSWER:
{"action":"answer","response":"message"}

RULES:

1. Understand the complete task.
2. Existing files must be read before modification.
3. Analyze the actual file content.
4. If modification is requested, you MUST make the modification.
5. Never return unchanged code when modification is requested.
6. Preserve existing functionality.
7. Return COMPLETE file content.
8. Never use placeholders.
9. Never invent source code.
10. Never delete files.
11. Never execute terminal commands.
12. Only work inside project root.
13. After writing, verify the file.
14. If task is complete, use answer action.

WORKFLOW:

Read -> Analyze -> Write -> Verify -> Answer

WRITE RULE:

When modifying a file, generate the entire final file.
Do not generate only snippets.
"""


# ==========================================
# AGENT LOOP
# ==========================================

def ask_ai(prompt):

    system_context = load_context()

    messages = [
        {
            "role": "system",
            "content": system_context + AGENT_INSTRUCTIONS
        },
        {
            "role": "user",
            "content": prompt
        }
    ]

    read_files = set()

    # ======================================
    # LOOP
    # ======================================

    for cycle in range(MAX_ACTIONS):

        print(f"\n[AI CORE] Cycle {cycle + 1}/{MAX_ACTIONS}")

        # ==================================
        # AI DECISION
        # ==================================

        try:

            raw_response = call_ai(messages)

            action_data = extract_json(raw_response)

        except Exception as e:

            print("[AI CORE ERROR]", e)

            # Retry with explicit correction
            messages.append({
                "role": "user",
                "content": f"""
Your previous response failed.

Error:
{e}

Return a valid JSON object only.
Do not use markdown.
Choose a valid action.
"""
            })

            try:

                raw_response = call_ai(messages)

                action_data = extract_json(raw_response)

            except Exception as retry_error:

                return f"AI-Core Decision Error: {retry_error}"

        action = action_data.get("action")

        # ==================================
        # READ FILE
        # ==================================

        if action == "read_file":

            file_path = action_data.get("path", "")

            print("[TOOL] Read:", file_path)

            try:

                target = safe_path(file_path)

                tool_result = read_project_file(file_path)

                if target.is_file():

                    read_files.add(str(target))

            except Exception as e:

                tool_result = f"Security Error: {e}"

            messages.append({
                "role": "assistant",
                "content": raw_response
            })

            messages.append({
                "role": "user",
                "content": f"""
READ TOOL RESULT:

File:
{file_path}

Content:
{tool_result}

Continue the original task.
Return the next action as valid JSON.
"""
            })

            continue

        # ==================================
        # WRITE FILE
        # ==================================

        elif action == "write_file":

            file_path = action_data.get("path", "")
            content = action_data.get("content", "")

            if not isinstance(content, str) or not content.strip():

                return "AI-Core: Write rejected. Empty file content."

            try:

                target = safe_path(file_path)

            except Exception as e:

                return f"Security Error: {e}"

            # Existing file must be read
            if target.exists() and str(target) not in read_files:

                messages.append({
                    "role": "assistant",
                    "content": raw_response
                })

                messages.append({
                    "role": "user",
                    "content": f"""
SECURITY CHECK FAILED.

You must read this file before modifying it:

{file_path}

Use read_file first.
Return JSON only.
"""
                })

                continue

            # Read original content
            if target.exists():

                old_content = target.read_text(
                    encoding="utf-8"
                )

            else:

                old_content = ""

            # ==================================
            # CHANGE VALIDATION
            # ==================================

            if old_content == content:

                print("\n[AI CORE] No changes detected.")

                messages.append({
                    "role": "assistant",
                    "content": raw_response
                })

                messages.append({
                    "role": "user",
                    "content": f"""
No changes were detected in {file_path}.

The requested modification may not have been implemented.

Analyze the original request again and generate
the actual modified complete file.

Do not return unchanged content.
Return JSON only.
"""
                })

                continue

            # ==================================
            # DIFF
            # ==================================

            print("\n" + "=" * 50)
            print("AI CORE WRITE REVIEW")
            print("=" * 50)

            print("File:", file_path)

            print(
                "Operation:",
                "MODIFY" if target.exists() else "CREATE"
            )

            show_diff(
                old_content,
                content,
                file_path
            )

            print("\n" + "=" * 50)

            # ==================================
            # APPROVAL
            # ==================================

            approval = input(
                "Approve changes? (y/n): "
            ).strip().lower()

            if approval != "y":

                return "Write cancelled by user."

            # ==================================
            # BACKUP AND WRITE
            # ==================================

            result, backup = write_project_file(
                file_path,
                content
            )

            print("\n[TOOL]", result)

            if backup:

                print("[BACKUP]", backup)

            # ==================================
            # VERIFICATION
            # ==================================

            print("\n[AI CORE] Verification...")

            verified_content = read_project_file(file_path)

            if verified_content != content:

                return (
                    "Verification failed. "
                    "Written content does not match expected content."
                )

            print("[AI CORE] Verification successful.")

            read_files.add(str(target))

            messages.append({
                "role": "assistant",
                "content": raw_response
            })

            messages.append({
                "role": "user",
                "content": f"""
WRITE RESULT:

File:
{file_path}

Result:
{result}

Verification:
SUCCESS

The file was written and verified.

Now provide the final answer.
Use the answer action.
Return valid JSON only.
"""
            })

            continue

        # ==================================
        # ANSWER
        # ==================================

        elif action == "answer":

            return action_data.get(
                "response",
                "Task completed."
            )

        else:

            return f"AI-Core: Unknown action: {action}"

    return (
        "AI-Core stopped because the maximum "
        "action cycle limit was reached."
    )


# ==========================================
# MAIN LOOP
# ==========================================

if __name__ == "__main__":

    print("=" * 50)
    print("AI CORE ENGINE V2")
    print("Model:", MODEL)
    print("Read Tool: ENABLED")
    print("Write Tool: ENABLED")
    print("Diff Review: ENABLED")
    print("Backup: ENABLED")
    print("Verification: ENABLED")
    print("Terminal Execution: DISABLED")
    print("Maximum Cycles:", MAX_ACTIONS)
    print("=" * 50)

    print("Commands:")
    print("/files")
    print("/read <file_path>")
    print("exit")
    print("=" * 50)

    while True:

        try:

            user_input = input("\nYou: ").strip()

        except (KeyboardInterrupt, EOFError):

            print("\nAI-Core stopped.")
            break

        if user_input.lower() in ["exit", "quit"]:

            print("\nAI-Core stopped.")
            break

        if not user_input:

            continue

        # ==================================
        # COMMANDS
        # ==================================

        if user_input == "/files":

            print(scan_project())
            continue

        if user_input.startswith("/read "):

            file_path = user_input[6:].strip()

            print("\n" + read_project_file(file_path))
            continue

        # ==================================
        # AGENT
        # ==================================

        result = ask_ai(user_input)

        print("\nAI:", result)