# tools.py
import json
import logging
import os
import shutil
import subprocess
from typing import Dict

from langchain_core.tools import tool

# Configure logging
logger = logging.getLogger(__name__)




# Success indicators for tool responses
class ToolResponseMessages:
    """Constants for tool response messages to avoid magic strings."""
    VALIDATION_SUCCESS = "Validation successful"
    SECURITY_SUCCESS = "No security issues detected"
    VALIDATION_PREFIX = "Formatted Files JSON:"

# Persistent directories for Terraform operations
PLUGIN_CACHE_DIR = os.path.join(os.path.dirname(__file__), "terraform_plugin_cache")
WORK_DIR = os.path.join(os.path.dirname(__file__), "terraform_work")

# Ensure directories exist
os.makedirs(PLUGIN_CACHE_DIR, exist_ok=True)
os.makedirs(WORK_DIR, exist_ok=True)


# --- Helper Functions ---

def _prepare_work_directory(files: Dict[str, str]) -> None:
    """
    Prepare work directory by clearing it and writing new files.
    
    Args:
        files: Dictionary of filename -> content to write
    """
    # Clear and recreate work directory
    if os.path.exists(WORK_DIR):
        shutil.rmtree(WORK_DIR)
    os.makedirs(WORK_DIR, exist_ok=True)
    
    # Write all files to work directory
    for filename, content in files.items():
        filepath = os.path.join(WORK_DIR, filename)
        with open(filepath, "w") as f:
            f.write(content)


def _get_terraform_env() -> dict:
    """
    Get environment variables for Terraform execution.
    
    Returns:
        Dictionary with environment variables
    """
    env = os.environ.copy()
    env["TF_PLUGIN_CACHE_DIR"] = PLUGIN_CACHE_DIR
    env["TF_PLUGIN_CACHE_MAY_BREAK_DEPENDENCY_LOCK_FILE"] = "true"
    return env


def _run_terraform_command(args: list, env: dict = None) -> subprocess.CompletedProcess:
    """
    Run a Terraform command in the work directory.
    
    Args:
        args: Command arguments (e.g., ["init", "-no-color"])
        env: Environment variables (uses _get_terraform_env() if None)
        
    Returns:
        CompletedProcess result
        
    Raises:
        subprocess.CalledProcessError: If command fails
    """
    if env is None:
        env = _get_terraform_env()
    
    return subprocess.run(
        ["terraform"] + args,
        cwd=WORK_DIR,
        capture_output=True,
        text=True,
        check=True,
        env=env
    )


def _format_error_message(error: subprocess.CalledProcessError) -> str:
    """
    Format a CalledProcessError into a readable error message.
    
    Args:
        error: The subprocess error
        
    Returns:
        Formatted error string
    """
    return (
        f"Terraform command failed.\n"
        f"Command: '{' '.join(error.cmd)}'\n"
        f"Stderr: {error.stderr}\n"
        f"Stdout: {error.stdout}"
    )


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
        # Get the absolute path of the workspace root
        workspace_root = os.path.dirname(os.path.abspath(__file__))
        project_path = os.path.join(workspace_root, project_name)
        
        # Create the project directory
        os.makedirs(project_path, exist_ok=True)
        
        # Save all files
        for filename, code in files.items():
            filepath = os.path.join(project_path, filename)
            with open(filepath, "w") as f:
                f.write(code)
        
        return True, f"✨ Files saved to '{project_path}'"
    except Exception as e:
        return False, f"❌ Error saving files: {e}"


# --- Terraform Tools ---

@tool
def terraform_validate_tool(files: Dict[str, str]) -> str:
    """
    Validate and format Terraform files.
    
    Runs terraform init, validate, and fmt on the provided files.
    
    Args:
        files: Dictionary of filename -> content (e.g., {'main.tf': '...'})
        
    Returns:
        Success message with formatted files JSON, or detailed error message
    """
    try:
        _prepare_work_directory(files)
        env = _get_terraform_env()
        
        # Initialize Terraform (using cached providers)
        _run_terraform_command(
            ["init", "-no-color", "-input=false", "-upgrade=false", "-get=true"],
            env
        )
        
        # Validate syntax
        _run_terraform_command(["validate", "-no-color"], env)
        
        # Format code
        _run_terraform_command(["fmt", "-recursive"])
        
        # Read formatted files
        formatted_files = {}
        for filename in files.keys():
            filepath = os.path.join(WORK_DIR, filename)
            with open(filepath, 'r') as f:
                formatted_files[filename] = f.read()
        
        return (
            f"{ToolResponseMessages.VALIDATION_SUCCESS}. Code is syntactically correct and well-formed.\n\n"
            f"{ToolResponseMessages.VALIDATION_PREFIX}\n{json.dumps(formatted_files, indent=2)}"
        )

    except subprocess.CalledProcessError as e:
        logger.error(f"Terraform validation command failed: {e.cmd}", exc_info=True)
        return _format_error_message(e)
    except FileNotFoundError as e:
        logger.error(f"Terraform executable not found: {e}")
        return f"Error: Terraform executable not found. Please ensure Terraform is installed and in PATH."
    except PermissionError as e:
        logger.error(f"Permission denied during validation: {e}")
        return f"Error: Permission denied. Please check file/directory permissions."
    except Exception as e:
        logger.exception("Unexpected error during terraform validation")
        return f"An unexpected error occurred: {str(e)}"


@tool
def terraform_security_scan_tool(files: Dict[str, str]) -> str:
    """
    Scan Terraform files for security issues using tfsec.
    
    Scans files in the work directory that was prepared during validation.
    
    Args:
        files: Dictionary of filename -> content (used for validation check)
        
    Returns:
        Success message if no issues found, or detailed security report
    """
    try:
        if not os.path.exists(WORK_DIR):
            return "Error: Work directory not found. Please run validation first."
        
        # Run tfsec with high severity threshold and practical exclusions
        # Excluded checks:
        # - aws-s3-encryption-customer-key: KMS adds complexity for simple buckets
        # - aws-s3-enable-bucket-logging: Logging buckets can't log to themselves
        # - aws-ec2-no-public-egress-sgr: Egress to 0.0.0.0/0 is standard practice (instances need internet access)
        scan_result = subprocess.run(
            [
                "tfsec", ".",
                "--no-color",
                "--format", "default",
                "--minimum-severity", "HIGH",
                "--exclude", "aws-s3-encryption-customer-key,aws-s3-enable-bucket-logging,aws-ec2-no-public-egress-sgr"
            ],
            cwd=WORK_DIR,
            capture_output=True,
            text=True
        )

        # tfsec exits with 0 when no problems are detected
        if scan_result.returncode == 0:
            return f"Security scan passed. {ToolResponseMessages.SECURITY_SUCCESS} by tfsec."
        
        # Build comprehensive security report
        report_parts = ["Security scan detected issues.\n"]
        
        if scan_result.stdout:
            report_parts.append(f"\ntfsec Report:\n{scan_result.stdout}")
        if scan_result.stderr:
            report_parts.append(f"\nErrors:\n{scan_result.stderr}")

        return "".join(report_parts)

    except FileNotFoundError:
        logger.warning("tfsec executable not found")
        return (
            "Error: `tfsec` command not found. Please ensure it is installed and in your PATH.\n"
            "Installation instructions:\n"
            "  - Windows (choco): choco install tfsec\n"
            "  - Windows (scoop): scoop install tfsec\n"
            "  - Windows (manual): Download from https://github.com/aquasecurity/tfsec/releases\n"
            "  - macOS: brew install tfsec\n"
            "  - Linux: Download from https://github.com/aquasecurity/tfsec/releases"
        )
    except subprocess.CalledProcessError as e:
        logger.error(f"tfsec command failed: {e.cmd}", exc_info=True)
        return f"Error: tfsec command failed: {e.stderr}"
    except Exception as e:
        logger.exception("Unexpected error during security scan")
        return f"An unexpected error occurred during security scan: {str(e)}"


@tool
def terraform_apply_tool(files: Dict[str, str]) -> str:
    """
    Apply Terraform configuration to AWS.
    
    Uses the work directory that was already initialized during validation.
    
    Args:
        files: Dictionary of filename -> content (used for validation check)
        
    Returns:
        Success message with apply output, or detailed error message
    """
    try:
        # Verify Terraform is initialized
        terraform_dir = os.path.join(WORK_DIR, ".terraform")
        if not os.path.exists(terraform_dir):
            return "Error: Terraform not initialized. Validation must be run first."
        
        env = _get_terraform_env()
        
        # Apply with auto-approve
        apply_result = _run_terraform_command(
            ["apply", "-auto-approve", "-no-color"],
            env
        )

        return (
            f"Terraform apply successful.\n\n"
            f"Output:\n{apply_result.stdout}"
        )

    except subprocess.CalledProcessError as e:
        logger.error(f"Terraform apply command failed: {e.cmd}", exc_info=True)
        return _format_error_message(e)
    except FileNotFoundError as e:
        logger.error(f"Terraform executable not found during apply: {e}")
        return f"Error: Terraform executable not found. Please ensure Terraform is installed and in PATH."
    except Exception as e:
        logger.exception("Unexpected error during terraform apply")
        return f"An unexpected error occurred during apply: {str(e)}"


@tool
def terraform_destroy_tool() -> str:
    """
    Destroy all Terraform-managed infrastructure.
    
    Uses the work directory with existing state to destroy all resources.
    
    Returns:
        Success message with destroy output, or detailed error message
    """
    try:
        # Verify Terraform is initialized and state exists
        terraform_dir = os.path.join(WORK_DIR, ".terraform")
        state_file = os.path.join(WORK_DIR, "terraform.tfstate")
        
        if not os.path.exists(terraform_dir):
            return "Error: Terraform not initialized. No resources to destroy."
        
        if not os.path.exists(state_file):
            return "Error: No Terraform state file found. No resources have been deployed."
        
        env = _get_terraform_env()
        
        # Destroy with auto-approve
        destroy_result = _run_terraform_command(
            ["destroy", "-auto-approve", "-no-color"],
            env
        )

        return (
            f"Terraform destroy successful. All resources have been removed.\n\n"
            f"Output:\n{destroy_result.stdout}"
        )

    except subprocess.CalledProcessError as e:
        logger.error(f"Terraform destroy command failed: {e.cmd}", exc_info=True)
        return _format_error_message(e)
    except FileNotFoundError as e:
        logger.error(f"Terraform executable not found during destroy: {e}")
        return f"Error: Terraform executable not found. Please ensure Terraform is installed and in PATH."
    except Exception as e:
        logger.exception("Unexpected error during terraform destroy")
        return f"An unexpected error occurred during destroy: {str(e)}"
