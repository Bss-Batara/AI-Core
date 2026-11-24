
from pathlib import Path


def write_file(project_root, file_path, content):
    """Write a file only within the AI-Core project directory."""

    root = Path(project_root).resolve()
    target = (root / file_path).resolve()

    # Security: restrict writing to project directory
    if not target.is_relative_to(root):
        return "Error: Writing outside project directory is prohibited."

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

        return f"Success: File written to {target}"

    except Exception as e:
        return f"Error writing file: {e}"


if __name__ == "__main__":
    print("Write File Tool ready.")
    print("Project-scoped writing protection enabled.")
