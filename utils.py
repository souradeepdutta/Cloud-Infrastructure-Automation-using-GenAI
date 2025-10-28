"""
Shared utility functions for the AWS Infrastructure Generator.
"""

import os


def save_files_to_disk(project_name: str, files: dict) -> tuple[bool, str]:
    """
    Save generated Terraform files to a project directory.
    
    Args:
        project_name: Name of the project directory
        files: Dictionary of filename -> content
        
    Returns:
        tuple: (success: bool, message: str)
    """
    try:
        os.makedirs(project_name, exist_ok=True)
        for filename, code in files.items():
            filepath = os.path.join(project_name, filename)
            with open(filepath, "w") as f:
                f.write(code)
        return True, f"✨ Files saved to './{project_name}/'"
    except Exception as e:
        return False, f"❌ Error saving files: {e}"
