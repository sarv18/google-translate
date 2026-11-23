import os
import shutil


def create_directory_structure(path, strct=None, replace=False):
    """
    Recursively creates directories and files based on a nested dictionary structure.

    Args:
        path: Base path to create structure in
        strct: Dictionary where keys are directory names and values are either
               nested dictionaries (subdirectories) or strings (file contents)
        replace: If True, delete existing subdirectories first
    """
    if replace and os.path.exists(path):
        shutil.rmtree(path)

    os.makedirs(path, exist_ok=True)

    if strct:
        for name, content in strct.items():
            full_path = os.path.join(path, name)
            if isinstance(content, dict):
                create_directory_structure(full_path, content, replace)
            else:
                with open(full_path, 'w') as f:
                    f.write(str(content))