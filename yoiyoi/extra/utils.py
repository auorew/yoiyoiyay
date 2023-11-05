import os
import shutil

from functools import partial
from pathlib import Path


def get_file_chunk(filepath: str, chunk_size: int = 1024) -> bytes:
    with open(filepath, "rb") as file:
        return file.read(chunk_size)


def get_file_object(filepath: str):
    return open(filepath, "rb")


def chunk_reader(filepath: str, chunk_size: int = 1024) -> bytes:
    with open(filepath, "rb") as file:
        for chunk in iter(partial(file.read, chunk_size), b""):
            yield chunk
    return


def get_file_bytes(filepath: str) -> bytes:
    return get_file_chunk(filepath, None)


def replace_file(filepath: str, replaced_filepath: str):
    os.remove(replaced_filepath)
    os.rename(filepath, replaced_filepath)


def move_file(src: str, dst: Path) -> Path:
    shutil.move(src, dst)
    return dst


def delete_files(storage: set[Path]):
    for file in storage:
        file.unlink(missing_ok=True)
