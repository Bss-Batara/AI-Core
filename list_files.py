import os
import sys

def list_files(directory, max_depth=3):
    """List project files and folders with limited depth."""
    if not os.path.isdir(directory):
        return f"Error: Directory not found: {directory}"

    result = []

    for root, dirs, files in os.walk(directory):
        depth = root[len(directory):].count(os.sep)

        if depth >= max_depth:
            dirs[:] = []

        dirs[:] = [d for d in dirs if d not in {
            ".git", "node_modules", "__pycache__", ".venv"
        }]

        for name in files:
            result.append(os.path.join(root, name))

    return "\n".join(result)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python list_files.py <directory>")
    else:
        print(list_files(sys.argv[1]))