# tools.py
import subprocess
import os
import tempfile
import json
import shutil
from langchain_core.tools import tool

# --- Environment Setup for LocalStack ---
# These variables tell the AWS provider to target your local LocalStack instance.
LOCALSTACK_ENV = {
    "AWS_ACCESS_KEY_ID": "test",
    "AWS_SECRET_ACCESS_KEY": "test",
    "AWS_DEFAULT_REGION": "us-east-1",
}

# Create a persistent plugin cache directory to avoid re-downloading providers
PLUGIN_CACHE_DIR = os.path.join(os.path.dirname(__file__), "terraform_plugin_cache")
os.makedirs(PLUGIN_CACHE_DIR, exist_ok=True)

# Create a persistent working directory for terraform operations
WORK_DIR = os.path.join(os.path.dirname(__file__), "terraform_work")
os.makedirs(WORK_DIR, exist_ok=True)

@tool
def terraform_validate_tool(files: dict[str, str]) -> str:
    """
    Validates and formats a dictionary of Terraform files against LocalStack.
    The dictionary keys are filenames (e.g., 'main.tf') and values are the code content.
    Saves the files to a directory, runs `init`, `validate`, and `fmt`.
    Returns a JSON string of formatted files if successful, or a detailed error message.
    """
    try:
        # Clear the work directory before starting
        if os.path.exists(WORK_DIR):
            shutil.rmtree(WORK_DIR)
        os.makedirs(WORK_DIR, exist_ok=True)
        
        # Write files to persistent work directory
        for filename, content in files.items():
            with open(os.path.join(WORK_DIR, filename), "w") as f:
                f.write(content)

        # The environment variables are passed to the subprocess
        env = os.environ.copy()
        env.update(LOCALSTACK_ENV)
        # Use plugin cache to avoid re-downloading providers
        env["TF_PLUGIN_CACHE_DIR"] = PLUGIN_CACHE_DIR
        # Disable plugin discovery to force using cache
        env["TF_PLUGIN_CACHE_MAY_BREAK_DEPENDENCY_LOCK_FILE"] = "true"

        # Run terraform init with flags to prevent internet access
        subprocess.run(
            ["terraform", "init", "-no-color", "-input=false", "-upgrade=false", "-get=true"],
            cwd=WORK_DIR, capture_output=True, text=True, check=True, env=env
        )

        # Run terraform validate
        subprocess.run(
            ["terraform", "validate", "-no-color"],
            cwd=WORK_DIR, capture_output=True, text=True, check=True, env=env
        )

        # Run terraform fmt
        subprocess.run(
            ["terraform", "fmt", "-recursive"],
            cwd=WORK_DIR, capture_output=True, text=True, check=True
        )

        formatted_files = {}
        for filename in files.keys():
            with open(os.path.join(WORK_DIR, filename), 'r') as f:
                formatted_files[filename] = f.read()

        return (
            f"Validation successful. Code is syntactically correct and well-formed.\n\n"
            f"Formatted Files JSON:\n{json.dumps(formatted_files, indent=2)}"
        )

    except subprocess.CalledProcessError as e:
        error_message = (
            f"Terraform command failed.\n"
            f"Command: '{' '.join(e.cmd)}'\n"
            f"Stderr: {e.stderr}\n"
            f"Stdout: {e.stdout}"
        )
        return error_message
    except Exception as e:
        return f"An unexpected error occurred: {str(e)}"

@tool
def terraform_security_scan_tool(files: dict[str, str]) -> str:
    """
    Scans a dictionary of Terraform files for security issues using tfsec.
    The dictionary keys are filenames and values are the code content.
    Uses the same WORK_DIR where validation was performed to avoid redundant operations.
    Returns a success message if no issues are found, or a detailed report of the issues.
    """
    try:
        # Use the same work directory where validation was already performed
        # This ensures we scan the exact files that were validated
        if not os.path.exists(WORK_DIR):
            return "Error: Work directory not found. Please run validation first."
        
        # Run tfsec and capture the output.
        # tfsec exits with 0 if no problems are found.
        # It exits with a non-zero code if issues are detected.
        # 
        # Using --minimum-severity HIGH to only fail on HIGH and CRITICAL issues
        # Excluding specific checks that are not practical for LocalStack development:
        # - aws-s3-encryption-customer-key: Requires KMS keys which adds complexity for simple buckets
        # - aws-s3-enable-bucket-logging: Logging buckets can't log to themselves (chicken-egg problem)
        scan_result = subprocess.run(
            ["tfsec", ".", "--no-color", "--format", "default", 
             "--minimum-severity", "HIGH",
             "--exclude", "aws-s3-encryption-customer-key,aws-s3-enable-bucket-logging"],
            cwd=WORK_DIR, capture_output=True, text=True
        )

        # If no output and successful return code, all is well
        # tfsec exits with 0 when no problems detected (even if it prints summary stats)
        if scan_result.returncode == 0:
            return "Security scan passed. No security issues detected by tfsec."
        
        # Build a comprehensive report
        report = "Security scan detected issues.\n\n"
        if scan_result.stdout:
            report += f"tfsec Report:\n{scan_result.stdout}\n"
        if scan_result.stderr:
            report += f"\nErrors:\n{scan_result.stderr}"

        return report

    except FileNotFoundError:
        return (
            "Error: `tfsec` command not found. Please ensure it is installed and in your PATH.\n"
            "Installation instructions:\n"
            "  - Windows (choco): choco install tfsec\n"
            "  - Windows (scoop): scoop install tfsec\n"
            "  - Windows (manual): Download from https://github.com/aquasecurity/tfsec/releases\n"
            "  - macOS: brew install tfsec\n"
            "  - Linux: Download from https://github.com/aquasecurity/tfsec/releases"
        )
    except Exception as e:
        return f"An unexpected error occurred during security scan: {str(e)}"

@tool
def terraform_apply_tool(files: dict[str, str]) -> str:
    """
    Applies the given Terraform configuration to LocalStack.
    The dictionary keys are filenames and values are the code content.
    Runs `init` and `apply`. Returns the `terraform apply` output.
    """
    try:
        # Use the same work directory that was already initialized during validation
        # This avoids re-running init and re-downloading providers
        if not os.path.exists(os.path.join(WORK_DIR, ".terraform")):
            # If .terraform doesn't exist, we need to init
            env = os.environ.copy()
            env.update(LOCALSTACK_ENV)
            env["TF_PLUGIN_CACHE_DIR"] = PLUGIN_CACHE_DIR
            env["TF_PLUGIN_CACHE_MAY_BREAK_DEPENDENCY_LOCK_FILE"] = "true"
            
            subprocess.run(
                ["terraform", "init", "-no-color", "-input=false", "-upgrade=false"],
                cwd=WORK_DIR, capture_output=True, text=True, check=True, env=env
            )
        
        env = os.environ.copy()
        env.update(LOCALSTACK_ENV)

        # Run terraform apply (no need to init again, already done in validate)
        apply_result = subprocess.run(
            ["terraform", "apply", "-auto-approve", "-no-color"],
            cwd=WORK_DIR, capture_output=True, text=True, check=True, env=env
        )

        return (
            f"Terraform apply successful.\n\n"
            f"Output:\n{apply_result.stdout}"
        )

    except subprocess.CalledProcessError as e:
        error_message = (
            f"Terraform apply command failed.\n"
            f"Command: '{' '.join(e.cmd)}'\n"
            f"Stderr: {e.stderr}\n"
            f"Stdout: {e.stdout}"
        )
        return error_message
    except Exception as e:
        return f"An unexpected error occurred during apply: {str(e)}"