# agents.py
from dotenv import load_dotenv
load_dotenv()

import os
import json
from typing import TypedDict, List, Dict
from langchain_google_genai import ChatGoogleGenerativeAI
# Make sure 'tools.py' is in the same directory and contains the tool definitions
from tools import terraform_validate_tool, terraform_apply_tool, terraform_security_scan_tool

# --- Define Graph State ---
# This TypedDict represents the shared state that flows through the graph.
# Each agent can read from and write to this state.
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

# --- Configure LLM ---
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.0,
    google_api_key=os.getenv("GOOGLE_API_KEY")
)

# --- Helper Functions ---

def _create_fallback_structure(initial_request: str) -> dict:
    """Creates a fallback plan structure when LLM response fails."""
    return {
        "plan": "1. Configure AWS provider\n2. Create requested resources",
        "file_structure": [
            {"file_name": "provider.tf", "brief": "Configure AWS provider for LocalStack with all required endpoints"},
            {"file_name": "main.tf", "brief": f"Create all resources needed for: {initial_request}"}
        ]
    }

# --- Agent Classes ---

class PlannerArchitectAgent:
    """Creates plan AND file structure with detailed briefs in one step - eliminates information loss."""
    def run(self, state: GraphState):
        print("\n🧠 Planning architecture...")
        error_context = ""
        # If a previous run failed, add the error report to the context for the LLM to fix.
        if state.get("validation_report") and not state.get("validation_passed"):
            error_context = f"""
⚠️ PREVIOUS ERRORS TO FIX:
{state['validation_report']}

FIX BY: Simplifying the plan, ensuring security resources are separate, and being more specific in briefs.
"""
        
        prompt = f"""Think step-by-step to create a MINIMAL Terraform architecture.

User wants: {state['initial_request']}
{error_context}

Reasoning process:
1. What AWS resources are EXPLICITLY requested? (Don't add extras)
2. What security configs are MANDATORY for these resources?
3. What files are needed? (provider.tf always + main.tf)

🔐 SECURITY REQUIREMENTS (separate resources):
S3: bucket + encryption_configuration(AES256) + public_access_block(all true) + versioning(Enabled)
DynamoDB: table with server_side_encryption + point_in_time_recovery blocks
Lambda: function + iam_role + tracing_config(Active)
EC2: encrypted volumes + metadata_options(http_tokens=required) + no public IP
RDS: storage_encrypted + not publicly_accessible + backup_retention >= 7

⚠️ KEEP IT SIMPLE:
- NO variables.tf or outputs.tf unless explicitly requested
- NO KMS keys (use AES256)
- NO log buckets (unless asked)
- 3-4 steps max in plan

OUTPUT JSON:
{{
  "plan": "1. Setup provider\\n2. Create [resource]\\n3. Add security configs",
  "files": [
    {{"file_name": "provider.tf", "brief": "AWS provider for LocalStack: region us-east-1, test creds, endpoints http://localhost:4566"}},
    {{"file_name": "main.tf", "brief": "Resource-by-resource list: aws_s3_bucket 'my_bucket' bucket='name', aws_s3_bucket_server_side_encryption_configuration sse_algorithm=AES256, aws_s3_bucket_public_access_block all=true, aws_s3_bucket_versioning status=Enabled"}}
  ]
}}

GOOD brief: "aws_dynamodb_table 'users' hash_key='id':S billing_mode=PAY_PER_REQUEST server_side_encryption enabled=true point_in_time_recovery enabled=true"
BAD brief: "Create DynamoDB table" (too vague!)
"""
        
        # Add human feedback if provided
        if state.get('human_feedback'):
            prompt += f"\n\nHuman feedback: {state['human_feedback']}"
        
        response = llm.invoke(prompt)
        # Debug output hidden for cleaner console
        
        try:
            # Clean up potential markdown formatting
            cleaned_response = response.content.strip().replace("```json", "").replace("```", "")
            parsed = json.loads(cleaned_response)
            
            plan = parsed.get("plan", "")
            file_structure = parsed.get("files", [])
            
            if not plan or not file_structure:
                print("⚠️ Warning: Response missing plan or files. Using fallback.")
                return _create_fallback_structure(state['initial_request'])
            
            print(f"✅ Plan created: {len(file_structure)} files to generate")
            
            return {
                "plan": plan,
                "file_structure": file_structure
            }
            
        except json.JSONDecodeError as e:
            print(f"❌ ERROR: PlannerArchitect did not return valid JSON: {e}")
            print(f"Response was: {response.content[:500]}")
            return _create_fallback_structure(state['initial_request'])

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
        prompt = f"""Generate HCL code for {file_name}. Output ONLY code, no explanations.

Brief: {brief}

RULES:
- Follow the brief exactly
- For provider.tf: LocalStack endpoints (us-east-1, test creds, http://localhost:4566)
- Use .id for resource references (e.g., aws_s3_bucket.name.id)
- Keep code clean and minimal

**Correct `provider.tf` for LocalStack:**
```hcl
terraform {{
  required_providers {{
    aws = {{
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }}
  }}
}}

# Configure the AWS provider to target LocalStack
provider "aws" {{
  region                      = "us-east-1"
  access_key                  = "test"
  secret_key                  = "test"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true
  s3_use_path_style           = true # Required for S3 in some versions

  # Define endpoints for all services to be used
  endpoints {{
    s3           = "http://localhost:4566"
    lambda       = "http://localhost:4566"
    dynamodb     = "http://localhost:4566"
    apigateway   = "http://localhost:4566"
    iam          = "http://localhost:4566"
    sts          = "http://localhost:4566"
    sqs          = "http://localhost:4566"
    sns          = "http://localhost:4566"
    # Add other services here as needed, all pointing to http://localhost:4566
  }}
}}
```

Now, generate the complete and correct HCL code for the file: {file_name}.
"""
        response = llm.invoke(prompt)
        # Clean up markdown formatting
        generated_code = response.content.strip().replace("```hcl", "").replace("```", "")
        print(f"✓ Generated {file_name}")
        
        # Generated code
        updated_files = state.get("generated_files", {})
        updated_files[file_name] = generated_code
        
        # Return the updated state
        return {
            "generated_files": updated_files,
            "file_structure": files_to_generate
        }

class CodeValidatorAgent:
    """Validates the entire set of generated Terraform files using the custom tool."""
    def run(self, state: GraphState):
        print("\n🔍 Validating Terraform code...")
        files = state["generated_files"]
        
        # Invoke the tool that runs `terraform init`, `validate`, and `fmt`
        validation_report = terraform_validate_tool.invoke({"files": files})
        validation_passed = "Validation successful" in validation_report

        formatted_files = files
        if validation_passed:
            print("✅ Terraform syntax validation successful.")
            try:
                # The tool returns formatted code in a JSON block, so we parse it
                json_part = validation_report.split("Formatted Files JSON:")
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
    """Deploys the validated code to LocalStack using the custom tool."""
    def run(self, state: GraphState):
        print("\n🚀 Deploying to LocalStack...")
        if not state.get("validation_passed"):
            return {"deployment_report": "Skipping deployment because validation failed."}
        
        files = state["generated_files"]
        # Invoke the tool that runs `terraform apply`
        deployment_report = terraform_apply_tool.invoke({"files": files})
        print("✅ Deployment complete")
        
        return {"deployment_report": deployment_report}

class SecurityScannerAgent:
    """Scans the validated Terraform code for security vulnerabilities using tfsec."""
    def run(self, state: GraphState):
        print("\n🛡️ Running security scan (tfsec)...")
        files = state["generated_files"]
        
        # Invoke the security scan tool
        security_report = terraform_security_scan_tool.invoke({"files": files})
        security_passed = "No security issues detected" in security_report

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