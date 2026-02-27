import socket
import os, sys


mkdirs = lambda path: os.makedirs(path, exist_ok=True)


def find_free_port() -> int:
    """
    Find a free port on the system.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


