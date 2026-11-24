
import os
import sys

def read_file(file_path):
    """Read the contents of a file safely."""

    if not os.path.isfile(file_path):
        return f"Error: File not found: {file_path}"

    try:
        with open(file_path, "r", encoding="utf-8") as file:
            return file.read()

    except Exception as e:
        return f"Error reading file: {e}"


if __name__ == "__main__":

    if len(sys.argv) < 2:
        print("Usage: python read_file.py <file_path>")

    else:
        result = read_file(sys.argv[1])
        print(result)
