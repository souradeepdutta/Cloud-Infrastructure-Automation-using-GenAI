# agents.py
import json
import os
from typing import Dict, List, TypedDict

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

from tools import (
    ToolResponseMessages,
    terraform_apply_tool,
    terraform_security_scan_tool,
    terraform_validate_tool,
)

# Load environment variables
load_dotenv()

# --- Configuration ---
MAX_RETRIES = 3  # Maximum retry attempts for failed validation/security


# --- Environment Validation ---
def _validate_environment() -> None:
    """Validate required environment variables at startup."""
    # At least one API key must be present
    google_key = os.getenv("GOOGLE_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    github_token = os.getenv("GITHUB_TOKEN")
    
    if not (google_key or openai_key or github_token):
        raise EnvironmentError(
            "Missing required API key. Please set at least one of:\n"
            "  - GOOGLE_API_KEY (for Gemini)\n"
            "  - OPENAI_API_KEY (for OpenAI)\n"
            "  - GITHUB_TOKEN (for GitHub Models)\n"
            "Please create a .env file or set these environment variables."
        )
    
    # Log which API is being used
    if google_key:
        print("✓ Using Google Gemini API")
    if openai_key:
        print("✓ Using OpenAI API available")
    if github_token:
        print("✓ Using GitHub Models API available")


# Validate at module load
_validate_environment()


# --- Define Graph State ---
class GraphState(TypedDict):
    """Shared state that flows through the agent graph."""
    initial_request: str
    plan: str
    file_structure: List[Dict[str, str]]
    generated_files: Dict[str, str]
    validation_report: str
    deployment_report: str
    human_feedback: str
    validation_passed: bool
    security_report: str
    security_passed: bool
    retry_count: int


# --- Configure LLM ---
def _get_llm():
    """Get configured LLM instance based on available API keys."""
    google_key = os.getenv("GOOGLE_API_KEY")
    
    if google_key:
        return ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            temperature=0.0,
            google_api_key=google_key
        )
    
    # Fallback to OpenAI/GitHub Models if Gemini not available
    # (Uncomment when needed)
    # from langchain_openai import ChatOpenAI
    # return ChatOpenAI(
    #     model="gpt-4",
    #     temperature=0.0,
    #     api_key=os.getenv("OPENAI_API_KEY") or os.getenv("GITHUB_TOKEN")
    # )
    
    raise EnvironmentError("No valid LLM configuration found")


llm = _get_llm()


# --- Helper Functions ---

def _load_security_rules() -> str:
    """Load security rules from TFSEC_RULES.md file with fallback."""
    rules_file = os.path.join(os.path.dirname(__file__), "TFSEC_RULES.md")
    
    try:
        with open(rules_file, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        print(f"⚠️ Could not load TFSEC_RULES.md: {e}")
        # Minimal fallback rules
        return """
S3: Create 4 resources - bucket + encryption_configuration + public_access_block + versioning
EC2: metadata_options{http_tokens=required}, associate_public_ip_address=false, ebs_block_device{encrypted=true}
"""


def _create_fallback_structure(initial_request: str) -> dict:
    """Create a minimal fallback plan structure when LLM response fails."""
    return {
        "plan": "1. Configure AWS provider for LocalStack\n2. Create requested resources with security",
        "file_structure": [
            {
                "file_name": "provider.tf",
                "brief": "AWS provider: region=us-east-1, credentials=test/test, s3_use_path_style=true, endpoint=http://localhost:4566"
            },
            {
                "file_name": "main.tf",
                "brief": f"Create resources for: {initial_request}"
            }
        ]
    }


def _parse_llm_json_response(response_content: str) -> dict:
    """
    Parse LLM response that may contain JSON wrapped in markdown code blocks.
    
    Args:
        response_content: Raw LLM response content
        
    Returns:
        Parsed JSON dictionary
        
    Raises:
        json.JSONDecodeError: If JSON parsing fails
    """
    cleaned = response_content.strip()
    
    # Remove markdown code fences
    if "```json" in cleaned:
        cleaned = cleaned.split("```json")[1].split("```")[0]
    elif "```" in cleaned:
        cleaned = cleaned.replace("```", "")
    
    return json.loads(cleaned.strip())


def _build_feedback_message(state: GraphState) -> str:
    """
    Build comprehensive feedback message from validation and security failures.
    
    Args:
        state: Current graph state
        
    Returns:
        Formatted feedback string for LLM context
    """
    feedback_parts = []
    
    # Add validation errors
    if state.get("validation_report") and not state.get("validation_passed"):
        feedback_parts.append(
            f"\n🔴 PREVIOUS VALIDATION ERRORS:\n{state['validation_report']}\n\n"
            "👉 Analyze WHY these errors occurred and FIX them in the new plan.\n"
            "Common fixes: Check resource names, syntax, required parameters, security configs."
        )
    
    # Add security scan failures
    if state.get("security_report") and not state.get("security_passed"):
        feedback_parts.append(
            f"\n🛡️ SECURITY SCAN FAILURES:\n{state['security_report']}\n\n"
            "👉 These are tfsec policy violations. Review the SECURITY RULES below and ensure ALL are implemented."
        )
    
    # Add human feedback
    if state.get('human_feedback'):
        feedback_parts.append(f"\n💬 USER FEEDBACK:\n{state['human_feedback']}")
    
    return "\n".join(feedback_parts)


# --- Agent Classes ---

class PlannerArchitectAgent:
    """Creates architecture plan and file structure. Learns from validation/security errors."""
    
    def run(self, state: GraphState) -> dict:
        """
        Generate infrastructure plan with file structure.
        
        Args:
            state: Current graph state containing request and feedback
            
        Returns:
            Dictionary with 'plan' and 'file_structure' keys
        """
        print("\n🧠 Planning architecture...")
        
        # Increment retry count if coming from a failure
        retry_count = state.get("retry_count", 0)
        if not state.get("validation_passed") or not state.get("security_passed"):
            if state.get("validation_report") or state.get("security_report"):
                retry_count += 1
                print(f"⚠️  Retry attempt {retry_count}/{MAX_RETRIES}")
        
        security_rules = _load_security_rules()
        feedback = _build_feedback_message(state)
        
        prompt = self._build_planning_prompt(state['initial_request'], feedback, security_rules)
        response = llm.invoke(prompt)
        
        try:
            parsed = _parse_llm_json_response(response.content)
            plan = parsed.get("plan", "")
            file_structure = parsed.get("files", [])
            
            if not plan or not file_structure:
                print("⚠️ Warning: Response missing plan or files. Using fallback.")
                return _create_fallback_structure(state['initial_request'])
            
            print(f"✅ Plan created: {len(file_structure)} files to generate")
            return {
                "plan": plan, 
                "file_structure": file_structure,
                "retry_count": retry_count
            }
            
        except json.JSONDecodeError as e:
            print(f"❌ ERROR: Invalid JSON response: {e}")
            print(f"Response preview: {response.content[:500]}")
            return _create_fallback_structure(state['initial_request'])
    
    @staticmethod
    def _build_planning_prompt(initial_request: str, feedback: str, security_rules: str) -> str:
        """Build the planning prompt for the LLM."""
        return f"""You are an expert Terraform architect. Create MINIMAL, SIMPLE infrastructure for: "{initial_request}"
{feedback}

📋 SECURITY RULES (implement only if relevant):
{security_rules}

🎯 KEEP IT SIMPLE:
1. What resources are needed? (ONLY what's requested - don't add extras)
2. How many instances/resources?
3. What specifications? (RAM → instance_type, storage size, etc.)

⚡ CRITICAL RULES:
- ONLY create 2 files MAXIMUM: provider.tf and main.tf
- Put ALL resources in main.tf (bucket + encryption + public_access_block + versioning in ONE file)
- Keep it MINIMAL - don't over-engineer
- For S3: Put bucket AND its security configs (encryption, public_access_block, versioning) in main.tf
- For EC2: Only create if explicitly requested

OUTPUT VALID JSON (EXACTLY 2 files):
{{
  "plan": "1. Configure LocalStack provider\\n2. Create requested resources with security",
  "files": [
    {{"file_name": "provider.tf", "brief": "AWS provider: region=us-east-1, credentials=test/test, all endpoints=http://localhost:4566, s3_use_path_style=true"}},
    {{"file_name": "main.tf", "brief": "ALL resources in ONE file: [describe EXACTLY what user requested] with security configs"}}
  ]
}}
"""


class CodeGeneratorAgent:
    """Generates HCL code for files based on detailed specifications."""
    
    def run(self, state: GraphState) -> dict:
        """
        Generate Terraform code for the next file in the queue.
        
        Args:
            state: Current graph state containing file_structure and generated_files
            
        Returns:
            Dictionary with updated 'generated_files' and 'file_structure'
        """
        files_to_generate = state["file_structure"]
        if not files_to_generate:
            return {}

        # Process next file in queue
        current_file = files_to_generate.pop(0)
        file_name = current_file["file_name"]
        brief = current_file["brief"]

        print(f"\n💻 Generating {file_name}...")
        
        prompt = self._build_generation_prompt(file_name, brief)
        response = llm.invoke(prompt)
        
        # Clean markdown code fences from response
        generated_code = self._clean_code_response(response.content)
        
        print(f"✓ Generated {file_name} ({len(generated_code)} bytes)")
        
        # Update generated files
        updated_files = state.get("generated_files", {})
        updated_files[file_name] = generated_code
        
        return {
            "generated_files": updated_files,
            "file_structure": files_to_generate
        }
    
    @staticmethod
    def _build_generation_prompt(file_name: str, brief: str) -> str:
        """Build the code generation prompt for the LLM."""
        return f"""Generate SIMPLE, MINIMAL HCL (Terraform) code for: {file_name}

📝 BRIEF: {brief}

⚡ CRITICAL:
- Output ONLY valid HCL code, NO explanations, NO markdown
- Keep it SIMPLE - don't over-engineer
- For S3 buckets: Include bucket + encryption config + public_access_block + versioning in main.tf
- For provider.tf: Only essential endpoints (s3, ec2, dynamodb, lambda, rds if needed)

📌 CONSTANTS:
- AMI: ami-ff0fea8310f3
- Region: us-east-1
- Endpoint: http://localhost:4566
- Credentials: access_key="test", secret_key="test"

Generate the code:
"""
    
    @staticmethod
    def _clean_code_response(response_content: str) -> str:
        """Remove markdown code fences from LLM response."""
        cleaned = response_content.strip()
        
        # Remove various markdown code fence formats
        for fence in ["```hcl", "```terraform", "```"]:
            if fence in cleaned:
                parts = cleaned.split(fence)
                if len(parts) >= 2:
                    cleaned = parts[1].split("```")[0] if fence != "```" else parts[1]
                    break
        
        return cleaned.strip()


class CodeValidatorAgent:
    """Validates generated Terraform files using terraform validate and fmt."""
    
    def run(self, state: GraphState) -> dict:
        """
        Validate all generated Terraform files.
        
        Args:
            state: Current graph state containing generated_files
            
        Returns:
            Dictionary with validation_report, validation_passed, and formatted files
        """
        print("\n🔍 Validating Terraform code...")
        files = state["generated_files"]
        
        validation_report = terraform_validate_tool.invoke({"files": files})
        validation_passed = ToolResponseMessages.VALIDATION_SUCCESS in validation_report

        # Extract formatted files if validation succeeded
        formatted_files = self._extract_formatted_files(validation_report, files, validation_passed)
        
        status = "✅" if validation_passed else "❌"
        print(f"{status} Terraform syntax validation {'successful' if validation_passed else 'failed'}.")

        return {
            "validation_report": validation_report,
            "validation_passed": validation_passed,
            "generated_files": formatted_files
        }
    
    @staticmethod
    def _extract_formatted_files(validation_report: str, original_files: dict, validation_passed: bool) -> dict:
        """Extract formatted files from validation report or return originals."""
        if not validation_passed:
            return original_files
        
        try:
            # Parse formatted files from tool output
            if ToolResponseMessages.VALIDATION_PREFIX in validation_report:
                json_part = validation_report.split(ToolResponseMessages.VALIDATION_PREFIX)[1].strip()
                return json.loads(json_part)
        except (IndexError, json.JSONDecodeError) as e:
            print(f"⚠️ Warning: Could not parse formatted code: {e}")
        
        return original_files


class DeployerAgent:
    """Deploys validated Terraform code to LocalStack."""
    
    def run(self, state: GraphState) -> dict:
        """
        Deploy infrastructure to LocalStack.
        
        Args:
            state: Current graph state containing validation status and files
            
        Returns:
            Dictionary with deployment_report
        """
        print("\n🚀 Deploying to LocalStack...")
        
        if not state.get("validation_passed"):
            return {"deployment_report": "Skipping deployment: validation failed."}
        
        files = state["generated_files"]
        deployment_report = terraform_apply_tool.invoke({"files": files})
        
        print("✅ Deployment complete")
        return {"deployment_report": deployment_report}


class SecurityScannerAgent:
    """Scans Terraform code for security vulnerabilities using tfsec."""
    
    def run(self, state: GraphState) -> dict:
        """
        Run security scan on generated Terraform files.
        
        Args:
            state: Current graph state containing generated_files
            
        Returns:
            Dictionary with security_report, security_passed, and potentially updated validation status
        """
        print("\n🛡️ Running security scan (tfsec)...")
        files = state["generated_files"]
        
        security_report = terraform_security_scan_tool.invoke({"files": files})
        security_passed = ToolResponseMessages.SECURITY_SUCCESS in security_report

        if security_passed:
            print("✅ tfsec security scan passed.")
            return {
                "security_report": security_report,
                "security_passed": True
            }
        else:
            print("❌ tfsec security scan found issues.")
            # Combine security issues with validation report for planner to address
            combined_report = self._combine_reports(state.get("validation_report", ""), security_report)
            
            return {
                "security_report": security_report,
                "security_passed": False,
                "validation_report": combined_report,
                "validation_passed": False  # Trigger retry through planner
            }
    
    @staticmethod
    def _combine_reports(validation_report: str, security_report: str) -> str:
        """Combine validation and security reports for comprehensive feedback."""
        return f"{validation_report}\n\n--- SECURITY ISSUES ---\n{security_report}"
