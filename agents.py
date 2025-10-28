# agents.py - Simplified Generic Approach
from dotenv import load_dotenv
load_dotenv()

import os
import json
from typing import TypedDict, List, Dict
from langchain_google_genai import ChatGoogleGenerativeAI
from tools import (
    ToolResponseMessages,
    terraform_validate_tool,
    terraform_apply_tool,
    terraform_security_scan_tool
)

# --- Configuration ---
MAX_RETRIES = 3

# --- Define Graph State ---
class GraphState(TypedDict):
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


# Google Gemini
# llm = ChatGoogleGenerativeAI(
#     model="gemini-2.5-flash",
#     temperature=0.0,
#     google_api_key=os.getenv("GOOGLE_API_KEY")
# )
# print("✓ Using Google Gemini API")

# GitHub Models (using OpenAI-compatible API)
from langchain_openai import ChatOpenAI
llm = ChatOpenAI(
    model="gpt-5",
    temperature=0.0,
    api_key=os.getenv("GITHUB_TOKEN"),
    base_url="https://models.inference.ai.azure.com",
    default_headers={
        "Authorization": f"Bearer {os.getenv('GITHUB_TOKEN')}"
    }
)
print("✓ Using GitHub Models API")

# --- Helper Functions ---

def _load_security_rules() -> str:
    """Load security rules from TFSEC_RULES.md file with fallback."""
    rules_file = os.path.join(os.path.dirname(__file__), "TFSEC_RULES.md")
    
    try:
        with open(rules_file, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        print(f"⚠️ Could not load TFSEC_RULES.md: {e}")
        return """
S3: 4 resources - bucket + encryption(AES256) + public_access_block(all true) + versioning(Enabled)
EC2: metadata_options{http_tokens=required}, no public IP, encrypted EBS, security group
DynamoDB: server_side_encryption + point_in_time_recovery
Lambda: IAM role + tracing_config(Active)
RDS: storage_encrypted + not publicly_accessible + backup_retention>=7
"""

def _create_fallback_structure(initial_request: str) -> dict:
    """Creates a fallback plan structure when LLM response fails."""
    return {
        "plan": "1. Configure AWS provider for LocalStack\n2. Create requested resources with security",
        "file_structure": [
            {"file_name": "provider.tf", "brief": "AWS provider for LocalStack: region us-east-1, test creds, all endpoints http://localhost:4566"},
            {"file_name": "main.tf", "brief": f"Create all resources needed for: {initial_request}"}
        ]
    }

def _parse_llm_json_response(response_content: str) -> dict:
    """Parse LLM response that may contain JSON wrapped in markdown."""
    cleaned = response_content.strip().replace("```json", "").replace("```", "")
    return json.loads(cleaned.strip())

# --- Agent Classes ---

class PlannerArchitectAgent:
    """Creates plan AND file structure with detailed briefs."""
    
    def run(self, state: GraphState):
        print("\n🧠 Planning architecture...")
        
        retry_count = state.get("retry_count", 0)
        error_context = ""
        
        if state.get("validation_report") and not state.get("validation_passed"):
            retry_count += 1
            print(f"⚠️  Retry attempt {retry_count}/{MAX_RETRIES}")
            error_context = f"""
⚠️ PREVIOUS ERRORS TO FIX:
{state['validation_report']}

FIX BY: Analyzing the exact error and being more specific in resource briefs.
"""
        
        security_rules = _load_security_rules()
        prompt = f"""Think step-by-step to create a MINIMAL Terraform architecture.

User wants: {state['initial_request']}
{error_context}

Reasoning process:
1. What AWS resources are EXPLICITLY requested? (Don't add extras)
2. What security configs are MANDATORY for these resources?
3. What files are needed? (provider.tf always + main.tf)

🔐 SECURITY REQUIREMENTS:
{security_rules}

⚠️ KEEP IT SIMPLE:
- NO variables.tf or outputs.tf unless explicitly requested
- NO KMS keys (use AES256)
- NO log buckets (unless asked)
- 3-5 steps max in plan
- Be SPECIFIC in briefs: list each resource type with key attributes

OUTPUT JSON:
{{
  "plan": "1. Setup provider\\n2. Create [specific resource]\\n3. Add [specific security config]",
  "files": [
    {{"file_name": "provider.tf", "brief": "AWS provider for LocalStack: region us-east-1, test creds, all endpoints http://localhost:4566"}},
    {{"file_name": "main.tf", "brief": "Resource-by-resource list with key attributes. Example: aws_s3_bucket 'bucket1' bucket='name', aws_s3_bucket_server_side_encryption_configuration 'bucket1' sse_algorithm=AES256, aws_s3_bucket_public_access_block 'bucket1' all=true, aws_s3_bucket_versioning 'bucket1' status=Enabled"}}
  ]
}}

GOOD brief: "aws_dynamodb_table 'users' hash_key='id':S billing_mode=PAY_PER_REQUEST server_side_encryption enabled=true point_in_time_recovery enabled=true"
BAD brief: "Create DynamoDB table" (too vague!)

CRITICAL: The brief for main.tf MUST list EVERY resource that will be created with their key attributes."""

        if state.get('human_feedback'):
            prompt += f"\n\nHuman feedback: {state['human_feedback']}"
        
        response = llm.invoke(prompt)
        
        try:
            parsed = _parse_llm_json_response(response.content)
            plan = parsed.get("plan", "")
            file_structure = parsed.get("files", [])
            
            if not plan or not file_structure:
                print("⚠️ Warning: Response missing plan or files. Using fallback.")
                return {**_create_fallback_structure(state['initial_request']), "retry_count": retry_count}
            
            print(f"✅ Plan created: {len(file_structure)} files to generate")
            return {
                "plan": plan,
                "file_structure": file_structure,
                "retry_count": retry_count
            }
            
        except json.JSONDecodeError as e:
            print(f"❌ ERROR: PlannerArchitect did not return valid JSON: {e}")
            print(f"Response was: {response.content[:500]}")
            return {**_create_fallback_structure(state['initial_request']), "retry_count": retry_count}


class CodeGeneratorAgent:
    """Generates HCL code for a single file based on a brief."""
    
    def run(self, state: GraphState):
        files_to_generate = state["file_structure"]
        if not files_to_generate:
            return {}

        # Take the next file to generate from the list
        current_file_spec = files_to_generate.pop(0)
        file_name = current_file_spec["file_name"]
        brief = current_file_spec["brief"]

        print(f"\n💻 Generating {file_name}...")
        
        prompt = f"""Generate HCL code for {file_name}. Output ONLY code, NO markdown, NO explanations.

Brief: {brief}

RULES:
- Follow the brief exactly - it contains all resource names and key attributes
- For provider.tf: LocalStack endpoints (us-east-1, test/test, http://localhost:4566)
- Use .id for resource references (e.g., aws_s3_bucket.name.id)
- Keep code clean and minimal
- Output pure HCL code only

**Correct provider.tf for LocalStack:**
```hcl
terraform {{
  required_providers {{
    aws = {{
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }}
  }}
}}

provider "aws" {{
  region                      = "us-east-1"
  access_key                  = "test"
  secret_key                  = "test"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true
  s3_use_path_style           = true

  endpoints {{
    s3           = "http://localhost:4566"
    lambda       = "http://localhost:4566"
    dynamodb     = "http://localhost:4566"
    apigateway   = "http://localhost:4566"
    iam          = "http://localhost:4566"
    sts          = "http://localhost:4566"
    sqs          = "http://localhost:4566"
    sns          = "http://localhost:4566"
    ec2          = "http://localhost:4566"
    rds          = "http://localhost:4566"
  }}
}}
```

Now, generate the complete and correct HCL code for: {file_name}
"""
        response = llm.invoke(prompt)
        
        # Clean up markdown formatting
        generated_code = response.content.strip()
        for fence in ["```hcl", "```terraform", "```"]:
            if fence in generated_code:
                parts = generated_code.split(fence)
                if len(parts) >= 2:
                    generated_code = parts[1].split("```")[0] if fence != "```" else parts[1]
                    break
        generated_code = generated_code.strip()
        
        print(f"✓ Generated {file_name} ({len(generated_code)} bytes)")
        
        # Update generated files
        updated_files = state.get("generated_files", {})
        updated_files[file_name] = generated_code
        
        return {
            "generated_files": updated_files,
            "file_structure": files_to_generate
        }


class CodeValidatorAgent:
    """Validates the entire set of generated Terraform files."""
    
    def run(self, state: GraphState):
        print("\n🔍 Validating Terraform code...")
        files = state["generated_files"]
        
        validation_report = terraform_validate_tool.invoke({"files": files})
        validation_passed = ToolResponseMessages.VALIDATION_SUCCESS in validation_report

        formatted_files = files
        if validation_passed:
            print("✅ Terraform syntax validation successful.")
            try:
                json_part = validation_report.split(ToolResponseMessages.VALIDATION_PREFIX)
                if len(json_part) > 1:
                    formatted_files = json.loads(json_part[1].strip())
            except (IndexError, json.JSONDecodeError):
                print("⚠️ Warning: Could not parse formatted code from tool output.")
        else:
            print("❌ Terraform syntax validation failed.")

        return {
            "validation_report": validation_report,
            "validation_passed": validation_passed,
            "generated_files": formatted_files
        }


class DeployerAgent:
    """Deploys the validated code to LocalStack."""
    
    def run(self, state: GraphState):
        print("\n🚀 Deploying to LocalStack...")
        if not state.get("validation_passed"):
            return {"deployment_report": "Skipping deployment because validation failed."}
        
        files = state["generated_files"]
        deployment_report = terraform_apply_tool.invoke({"files": files})
        print("✅ Deployment complete")
        
        return {"deployment_report": deployment_report}


class SecurityScannerAgent:
    """Scans the validated Terraform code for security vulnerabilities using tfsec."""
    
    def run(self, state: GraphState):
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
            # Append security issues to validation_report so PlannerAgent can address them
            existing_report = state.get("validation_report", "")
            combined_report = f"{existing_report}\n\n--- SECURITY ISSUES ---\n{security_report}"
            return {
                "security_report": security_report,
                "security_passed": False,
                "validation_report": combined_report,
                "validation_passed": False  # Mark validation as failed to trigger retry
            }
