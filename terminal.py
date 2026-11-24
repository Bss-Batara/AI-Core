import subprocess

ALLOWED_COMMANDS = ["python", "python3", "git"]

def run_command(command):
    """Run a restricted command."""

    parts = command.strip().split()

    if not parts:
        return "Error: Empty command."

    if parts[0] not in ALLOWED_COMMANDS:
        return "Error: Command not allowed."

    try:
        result = subprocess.run(
            parts,
            capture_output=True,
            text=True,
            timeout=60
        )

        return result.stdout + result.stderr

    except subprocess.TimeoutExpired:
        return "Error: Command timed out."

    except Exception as e:
        return f"Error: {e}"

if __name__ == "__main__":
    print("Restricted terminal tool ready.")``