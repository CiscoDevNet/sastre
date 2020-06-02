from pathlib import Path

current_dir = Path(__file__).resolve().parent


def module_dir():
    return current_dir
