"""
Terraform tool implementations for AWS Infrastructure Generator.
Provides tools for validation, security scanning, deployment, cost estimation, and resource destruction.
"""
import json
import logging
import os
import shutil
import subprocess
from typing import Dict, List, Tuple

from langchain_core.tools import tool

# Configure logging
logger = logging.getLogger(__name__)


# --- Pricing Constants (US-East-1, as of Nov 2025) ---
# EC2 instance hourly rates (On-Demand, Linux)
EC2_PRICING = {
    "t2.micro": 0.0116, "t2.small": 0.023, "t2.medium": 0.0464,
    "t3.micro": 0.0104, "t3.small": 0.0208, "t3.medium": 0.0416,
    "t3.large": 0.0832, "t3.xlarge": 0.1664,
    "m5.large": 0.096, "m5.xlarge": 0.192, "m5.2xlarge": 0.384,
}

# RDS instance hourly rates
RDS_PRICING = {
    "db.t3.micro": 0.017, "db.t3.small": 0.034, "db.t3.medium": 0.068,
    "db.t3.large": 0.136, "db.m5.large": 0.192, "db.m5.xlarge": 0.384,
}

# ElastiCache node hourly rates
ELASTICACHE_PRICING = {
    "cache.t3.micro": 0.017, "cache.t3.small": 0.034,
    "cache.m5.large": 0.161, "cache.r5.large": 0.201,
}

# Storage and other costs
STORAGE_COSTS = {
    "ebs_gp2_per_gb": 0.10,
    "s3_standard_per_gb": 0.023,
    "rds_storage_per_gb": 0.115,
}

# Average hours per month for cost calculations
MONTHLY_HOURS = 730


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
        with open(filepath, "w", encoding='utf-8') as f:
            f.write(content)


def _get_terraform_env() -> Dict:
    """
    Get environment variables for Terraform execution.

    Returns:
        Dictionary with environment variables
    """
    env = os.environ.copy()
    env["TF_PLUGIN_CACHE_DIR"] = PLUGIN_CACHE_DIR
    env["TF_PLUGIN_CACHE_MAY_BREAK_DEPENDENCY_LOCK_FILE"] = "true"
    return env


def _run_terraform_command(args: List[str], env: Dict = None) -> subprocess.CompletedProcess:
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
    error_parts = [
        "=" * 80,
        "TERRAFORM ERROR",
        "=" * 80,
        f"\nCommand: {' '.join(error.cmd)}",
        f"\nExit Code: {error.returncode}",
        "\n" + "-" * 80,
    ]
    
    if error.stdout and error.stdout.strip():
        error_parts.extend([
            "\nSTDOUT:",
            "-" * 80,
            error.stdout.strip(),
            "-" * 80,
        ])
    
    if error.stderr and error.stderr.strip():
        error_parts.extend([
            "\nSTDERR:",
            "-" * 80,
            error.stderr.strip(),
            "-" * 80,
        ])
    
    error_parts.append("=" * 80)
    
    return "\n".join(error_parts)


def save_files_to_disk(project_name: str, files: Dict) -> Tuple[bool, str]:
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
            with open(filepath, "w", encoding='utf-8') as f:
                f.write(code)

        return True, f"✨ Files saved to '{project_path}'"
    except Exception as e:
        logger.exception("Error saving files to disk")
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
            with open(filepath, 'r', encoding='utf-8') as f:
                formatted_files[filename] = f.read()

        return (
            f"{ToolResponseMessages.VALIDATION_SUCCESS}. "
            f"Code is syntactically correct and well-formed.\n\n"
            f"{ToolResponseMessages.VALIDATION_PREFIX}\n{json.dumps(formatted_files, indent=2)}"
        )

    except subprocess.CalledProcessError as e:
        logger.error(f"Terraform validation command failed: {e.cmd}", exc_info=True)
        return _format_error_message(e)
    except FileNotFoundError as e:
        logger.error(f"Terraform executable not found: {e}")
        return "Error: Terraform executable not found. Please ensure Terraform is installed and in PATH."
    except PermissionError as e:
        logger.error(f"Permission denied during validation: {e}")
        return "Error: Permission denied. Please check file/directory permissions."
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
        # - aws-s3-encryption-customer-key: Customer-managed keys not always needed
        # - aws-s3-enable-bucket-logging: Logging buckets don't need their own logs
        # - aws-ec2-no-public-egress-sgr: Egress to 0.0.0.0/0 is standard (internet access)
        # - aws-ec2-no-public-ingress-sgr: Public ingress is intentional for web servers/blogs
        scan_result = subprocess.run(
            [
                "tfsec", ".",
                "--no-color",
                "--format", "default",
                "--minimum-severity", "HIGH",
                "--exclude", "aws-s3-encryption-customer-key,aws-s3-enable-bucket-logging,aws-ec2-no-public-egress-sgr,aws-ec2-no-public-ingress-sgr"
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
        return "Error: Terraform executable not found. Please ensure Terraform is installed and in PATH."
    except Exception as e:
        logger.exception("Unexpected error during terraform apply")
        return f"An unexpected error occurred during apply: {str(e)}"


@tool
def terraform_cost_estimate_tool(files: Dict[str, str]) -> str:
    """
    Estimate monthly AWS infrastructure costs from deployed resources.

    Analyzes the terraform state file to extract deployed resources and
    calculates estimated costs using simple heuristics.

    Args:
        files: Dictionary of filename -> content (not used, but required by tool signature)

    Returns:
        Cost estimate report with breakdown and optimization suggestions
    """
    try:
        # Check if resources have been deployed
        state_file = os.path.join(WORK_DIR, "terraform.tfstate")
        if not os.path.exists(state_file):
            return "Cost estimation unavailable: No resources have been deployed yet."

        # Read terraform state
        with open(state_file, 'r', encoding='utf-8') as f:
            state_data = json.load(f)

        # Extract resources from state
        resources = state_data.get("resources", [])
        if not resources:
            return "Cost estimation unavailable: No resources found in state."

        # Calculate costs
        total_cost = 0
        cost_breakdown = []
        suggestions = []

        for resource in resources:
            resource_type = resource.get("type", "")
            resource_name = resource.get("name", "")
            instances = resource.get("instances", [])

            for instance in instances:
                attributes = instance.get("attributes", {})
                cost_info = _estimate_resource_cost(resource_type, resource_name, attributes)

                if cost_info:
                    total_cost += cost_info["monthly_cost"]
                    cost_breakdown.append(cost_info)

                    # Generate suggestions
                    resource_suggestions = _generate_simple_suggestions(
                        resource_type, resource_name, attributes, cost_info["monthly_cost"]
                    )
                    suggestions.extend(resource_suggestions)

        # Format output
        return _format_cost_report(total_cost, cost_breakdown, suggestions)

    except FileNotFoundError:
        return "Cost estimation unavailable: Terraform state file not found."
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing terraform state: {e}")
        return "Cost estimation unavailable: Could not parse terraform state file."
    except Exception as e:
        logger.exception("Unexpected error during cost estimation")
        return f"Cost estimation error: {str(e)}"


def _format_cost_report(
    total_cost: float,
    cost_breakdown: List[Dict],
    suggestions: List[str]
) -> str:
    """Format cost report with breakdown and suggestions."""
    output = f"💰 ESTIMATED MONTHLY COST: ${total_cost:.2f}\n"
    output += "=" * 60 + "\n\n"
    output += "COST BREAKDOWN:\n"
    output += "-" * 60 + "\n"

    for item in cost_breakdown:
        output += f"{item['service']:15} | {item['resource']:30} | ${item['monthly_cost']:>8.2f}\n"

    output += "-" * 60 + "\n"
    output += f"{'TOTAL':15} | {'':<30} | ${total_cost:>8.2f}\n"

    # Add suggestions
    if suggestions:
        output += "\n" + "=" * 60 + "\n"
        output += "💡 COST OPTIMIZATION SUGGESTIONS:\n"
        output += "=" * 60 + "\n"
        for i, suggestion in enumerate(suggestions[:8], 1):
            output += f"\n{i}. {suggestion}"

    # Add general recommendations
    output += "\n\n" + "=" * 60 + "\n"
    output += "📊 GENERAL RECOMMENDATIONS:\n"
    output += "=" * 60 + "\n"
    output += "\n• Set up AWS Budgets to track spending"
    output += "\n• Enable AWS Cost Anomaly Detection"
    output += "\n• Use Cost Explorer for detailed analysis"
    output += "\n• Tag all resources for cost allocation"

    if total_cost > 100:
        output += (
            f"\n\n⚠️  Monthly cost exceeds $100. "
            f"Review your architecture for optimization opportunities."
        )

    return output


def _estimate_resource_cost(resource_type: str, resource_name: str, attributes: dict) -> Dict:
    """
    Estimate cost for a single resource based on type and attributes.
    Uses conservative estimates based on AWS pricing as of Nov 2025.
    """
    # EC2 Instances
    if resource_type == "aws_instance":
        instance_type = attributes.get("instance_type", "t3.micro")
        hourly_rate = EC2_PRICING.get(instance_type, EC2_PRICING["t3.micro"])
        monthly_cost = hourly_rate * MONTHLY_HOURS
        
        # Add EBS volume cost
        ebs_volumes = attributes.get("root_block_device", [])
        if ebs_volumes:
            volume_size = ebs_volumes[0].get("volume_size", 20) if isinstance(ebs_volumes, list) else 20
            monthly_cost += volume_size * STORAGE_COSTS["ebs_gp2_per_gb"]
        
        return {
            "service": "EC2",
            "resource": f"{instance_type} ({resource_name})",
            "monthly_cost": monthly_cost
        }
    
    # S3 Buckets
    elif resource_type == "aws_s3_bucket":
        # Estimate: 10GB storage + minimal requests
        storage_gb = 10
        monthly_cost = storage_gb * STORAGE_COSTS["s3_standard_per_gb"]
        
        return {
            "service": "S3",
            "resource": f"Bucket ({resource_name})",
            "monthly_cost": monthly_cost
        }
    
    # DynamoDB Tables
    elif resource_type == "aws_dynamodb_table":
        billing_mode = attributes.get("billing_mode", "PAY_PER_REQUEST")
        
        if billing_mode == "PAY_PER_REQUEST":
            # Estimate: 1M writes, 5M reads per month
            monthly_cost = (1 * 1.25) + (5 * 0.25)  # $1.25/M writes, $0.25/M reads
        else:
            # Provisioned mode
            read_capacity = attributes.get("read_capacity", 5)
            write_capacity = attributes.get("write_capacity", 5)
            monthly_cost = (read_capacity * 0.00013 + write_capacity * 0.00065) * MONTHLY_HOURS
        
        return {
            "service": "DynamoDB",
            "resource": f"Table ({resource_name})",
            "monthly_cost": monthly_cost
        }
    
    # RDS Instances
    elif resource_type == "aws_db_instance":
        instance_class = attributes.get("instance_class", "db.t3.micro")
        allocated_storage = attributes.get("allocated_storage", 20)
        
        hourly_rate = RDS_PRICING.get(instance_class, RDS_PRICING["db.t3.micro"])
        monthly_cost = (hourly_rate * MONTHLY_HOURS) + (allocated_storage * STORAGE_COSTS["rds_storage_per_gb"])
        
        return {
            "service": "RDS",
            "resource": f"{instance_class} ({resource_name})",
            "monthly_cost": monthly_cost
        }
    
    # Lambda Functions
    elif resource_type == "aws_lambda_function":
        # Estimate: 1M requests, 128MB, 200ms duration
        monthly_cost = 0.20  # $0.20 per 1M requests (within free tier for most)
        
        return {
            "service": "Lambda",
            "resource": f"Function ({resource_name})",
            "monthly_cost": monthly_cost
        }
    
    # NAT Gateway
    elif resource_type == "aws_nat_gateway":
        # $0.045/hour + $0.045/GB data processed (estimate 100GB)
        monthly_cost = (0.045 * MONTHLY_HOURS) + (100 * 0.045)
        
        return {
            "service": "NAT Gateway",
            "resource": resource_name,
            "monthly_cost": monthly_cost
        }
    
    # Load Balancers
    elif resource_type == "aws_lb" or resource_type == "aws_alb":
        # ALB: $0.0225/hour + LCU charges (estimate $0.008/LCU * 730)
        monthly_cost = (0.0225 * MONTHLY_HOURS) + (0.008 * MONTHLY_HOURS)
        
        return {
            "service": "Load Balancer",
            "resource": resource_name,
            "monthly_cost": monthly_cost
        }
    
    # ElastiCache
    elif resource_type == "aws_elasticache_cluster":
        node_type = attributes.get("node_type", "cache.t3.micro")
        num_nodes = attributes.get("num_cache_nodes", 1)
        
        hourly_rate = ELASTICACHE_PRICING.get(node_type, ELASTICACHE_PRICING["cache.t3.micro"])
        monthly_cost = hourly_rate * MONTHLY_HOURS * num_nodes
        
        return {
            "service": "ElastiCache",
            "resource": f"{node_type} x{num_nodes}",
            "monthly_cost": monthly_cost
        }
    
    return None


def _generate_simple_suggestions(resource_type: str, resource_name: str, attributes: dict, monthly_cost: float) -> List[str]:
    """Generate cost optimization suggestions for a resource."""
    suggestions = []
    
    # EC2 suggestions
    if resource_type == "aws_instance":
        instance_type = attributes.get("instance_type", "")
        if "t2." in instance_type:
            suggestions.append(f"Consider upgrading '{resource_name}' from T2 to T3 instances for ~10% cost savings and better performance")
        if monthly_cost > 50:
            suggestions.append(f"'{resource_name}' costs ${monthly_cost:.2f}/month. Use Reserved Instances for 40-60% savings on long-term workloads")
    
    # DynamoDB suggestions
    elif resource_type == "aws_dynamodb_table":
        billing_mode = attributes.get("billing_mode", "")
        if billing_mode == "PAY_PER_REQUEST" and monthly_cost > 10:
            suggestions.append(f"Table '{resource_name}' uses on-demand pricing. Switch to provisioned capacity if traffic is predictable (50%+ savings)")
    
    # RDS suggestions
    elif resource_type == "aws_db_instance" and monthly_cost > 30:
        suggestions.append(f"RDS '{resource_name}' costs ${monthly_cost:.2f}/month. Consider Aurora Serverless v2 for variable workloads (up to 90% savings)")
    
    # S3 suggestions
    elif resource_type == "aws_s3_bucket":
        suggestions.append(f"Enable S3 Intelligent-Tiering on '{resource_name}' to automatically optimize storage costs")
    
    # NAT Gateway suggestions
    elif resource_type == "aws_nat_gateway":
        suggestions.append(f"NAT Gateway costs ${monthly_cost:.2f}/month. Consider VPC endpoints for AWS services to reduce data transfer costs")
    
    return suggestions


@tool
def terraform_destroy_tool() -> str:
    """
    Destroy all Terraform-managed infrastructure.

    Uses the work directory with existing state to destroy all resources.

    Returns:
        Success message with destroy output, or detailed error message
    """
    print("\n🗑️ Destroying Terraform resources...")
    
    try:
        # Verify Terraform is initialized and state exists
        terraform_dir = os.path.join(WORK_DIR, ".terraform")
        state_file = os.path.join(WORK_DIR, "terraform.tfstate")

        if not os.path.exists(terraform_dir):
            error_msg = "Error: Terraform not initialized. No resources to destroy."
            print(f"❌ {error_msg}")
            return error_msg

        if not os.path.exists(state_file):
            error_msg = "Error: No Terraform state file found. No resources have been deployed."
            print(f"❌ {error_msg}")
            return error_msg

        env = _get_terraform_env()

        print("⏳ Running terraform destroy -auto-approve...")
        
        # Destroy with auto-approve
        destroy_result = _run_terraform_command(
            ["destroy", "-auto-approve", "-no-color"],
            env
        )

        print("✅ Terraform destroy successful!")

        return (
            f"Terraform destroy successful. All resources have been removed.\n\n"
            f"Output:\n{destroy_result.stdout}"
        )

    except subprocess.CalledProcessError as e:
        logger.error(f"Terraform destroy command failed: {e.cmd}", exc_info=True)
        error_msg = _format_error_message(e)
        print(f"❌ Destroy failed:\n{error_msg}")
        return error_msg
    except FileNotFoundError as e:
        logger.error(f"Terraform executable not found during destroy: {e}")
        error_msg = "Error: Terraform executable not found. Please ensure Terraform is installed and in PATH."
        print(f"❌ {error_msg}")
        return error_msg
    except Exception as e:
        logger.exception("Unexpected error during terraform destroy")
        error_msg = f"An unexpected error occurred during destroy: {str(e)}"
        print(f"❌ {error_msg}")
        return error_msg

