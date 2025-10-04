# agents.py
from dotenv import load_dotenv
load_dotenv()

import os
import json
from typing import TypedDict, Annotated, List, Dict
from langgraph.graph.message import add_messages
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
    messages: Annotated[list, add_messages]

# --- Configure LLM ---
# We configure the connection to the Google Gemini model here.
# The model version is specified for consistent results.
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.3,  # Lower temperature for more deterministic, code-focused output
    google_api_key=os.getenv("GOOGLE_API_KEY")
)

# --- Agent Classes ---

class PlannerArchitectAgent:
    """Creates plan AND file structure with detailed briefs in one step - eliminates information loss."""
    def run(self, state: GraphState):
        print("--- 🧠💡 PLANNER + ARCHITECT AGENT ---")
        error_context = ""
        # If a previous run failed, add the error report to the context for the LLM to fix.
        if state.get("validation_report") and not state.get("validation_passed"):
            error_context = f"""
**PREVIOUS ATTEMPT FAILED - YOU MUST FIX THESE ERRORS:**

{state['validation_report']}

**FIXING INSTRUCTIONS:**
1. Read the errors above CAREFULLY
2. Create a SIMPLER plan and file structure that avoids these errors
3. If syntax errors: ensure briefs specify proper HCL syntax requirements
4. If security errors: include security features in the briefs (encryption, access blocks, etc.)
5. Make briefs MORE DETAILED and SPECIFIC
6. Keep the plan minimal (3-5 steps maximum)
"""
        
        prompt = f"""You are an expert Terraform architect. You must create BOTH a minimal implementation plan AND detailed file structure in ONE response.

**YOUR TASK:**
1. Create a 3-5 step implementation plan (high-level, plain English)
2. Define which Terraform files are needed
3. For EACH file, provide a VERY DETAILED brief that includes:
   - Exact resource types to create (e.g., aws_s3_bucket, aws_s3_bucket_server_side_encryption_configuration)
   - Specific configurations needed (encryption: AES256, versioning: Enabled, etc.)
   - Security requirements (public access: blocked, encryption: enabled)
   - Resource relationships and dependencies
   - All attributes that must be set

**CRITICAL CONSTRAINTS:**
- Plan must be 3-5 steps MAXIMUM
- Only plan what user EXPLICITLY requested - no extras
- DO NOT add variables.tf unless user mentioned "configurable" or "parameters"
- DO NOT add outputs.tf unless user asked to "see", "get", or "output" something
- Keep resources at their SIMPLEST viable configuration
- Security features should be detailed in briefs

**USER REQUEST:** "{state['initial_request']}"
{state.get('human_feedback', '')}
{error_context}

**OUTPUT FORMAT (MUST BE VALID JSON):**
{{
  "plan": "1. Configure AWS provider\\n2. Create S3 bucket with security\\n3. Add encryption configuration",
  "files": [
    {{
      "file_name": "provider.tf",
      "brief": "Configure AWS provider for LocalStack with region us-east-1, test credentials, and endpoints for s3 pointing to http://localhost:4566"
    }},
    {{
      "file_name": "main.tf",
      "brief": "Create aws_s3_bucket resource named 'example' with bucket name from var or hardcoded. Create aws_s3_bucket_server_side_encryption_configuration resource with sse_algorithm AES256. Create aws_s3_bucket_public_access_block resource with all four settings (block_public_acls, block_public_policy, ignore_public_acls, restrict_public_buckets) set to true. Create aws_s3_bucket_versioning resource with status Enabled."
    }}
  ]
}}

**EXAMPLE OF GOOD DETAILED BRIEF:**
"Create aws_dynamodb_table resource named 'users' with hash_key 'id' of type S, billing_mode PAY_PER_REQUEST, server_side_encryption block with enabled true, point_in_time_recovery block with enabled true"

**EXAMPLE OF BAD BRIEF (too vague):**
"Create DynamoDB table" ← NEVER DO THIS!

Now generate the JSON response with plan and detailed file structure for: {state['initial_request']}
"""
        
        response = llm.invoke(prompt)
        print(f"--- Raw Planner+Architect Response ---\n{response.content}\n--------------------------")
        
        try:
            # Clean up potential markdown formatting
            cleaned_response = response.content.strip().replace("```json", "").replace("```", "")
            parsed = json.loads(cleaned_response)
            
            plan = parsed.get("plan", "")
            file_structure = parsed.get("files", [])
            
            if not plan or not file_structure:
                print("⚠️ Warning: Response missing plan or files. Using fallback.")
                return {
                    "plan": "1. Configure provider\n2. Create main resources",
                    "file_structure": [
                        {"file_name": "provider.tf", "brief": "Configure AWS provider for LocalStack"},
                        {"file_name": "main.tf", "brief": f"Create resources for: {state['initial_request']}"}
                    ],
                    "generated_files": {},
                    "validation_report": "",
                    "security_report": ""
                }
            
            print(f"✅ Plan: {plan}")
            print(f"✅ File Structure: {len(file_structure)} files")
            
            # Reset state for the new plan
            return {
                "plan": plan,
                "file_structure": file_structure,
                "generated_files": {},
                "validation_report": "",
                "security_report": ""
            }
            
        except json.JSONDecodeError as e:
            print(f"❌ ERROR: PlannerArchitect did not return valid JSON: {e}")
            print(f"Response was: {response.content[:500]}")
            # Provide fallback structure
            return {
                "plan": "1. Configure AWS provider\n2. Create requested resources",
                "file_structure": [
                    {"file_name": "provider.tf", "brief": "Configure AWS provider for LocalStack with all required endpoints"},
                    {"file_name": "main.tf", "brief": f"Create all resources needed for: {state['initial_request']}"}
                ],
                "generated_files": {},
                "validation_report": "",
                "security_report": ""
            }

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

        print(f"--- 💻 CODE GENERATOR AGENT (File: {file_name}) ---")
        prompt = f"""You are a Terraform code generator. Your task is to write HCL code for the file `{file_name}` to deploy AWS resources to LocalStack.

**CONTEXT:**
- **This File's Purpose (`{file_name}`):** {brief}
- **Complete File Structure Plan:** {[f['file_name'] for f in state['file_structure']] + [file_name]}
- **Already Generated Files (for reference):**
{json.dumps(state.get('generated_files', {}), indent=2)}

**RULES:**
1.  Generate ONLY the HCL code for `{file_name}`. Do not add any explanations or markdown.
2.  **Strictly adhere to the file's brief.**
3.  **ARCHITECTURE RULE:** `variable` blocks go ONLY in `variables.tf`. `output` blocks go ONLY in `outputs.tf`. `provider` blocks go ONLY in `provider.tf`.
4.  **LOCALSTACK PROVIDER RULE:** If you are writing the `provider.tf` file, you **MUST** configure it to point to LocalStack endpoints. Use the example below.

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
        print(f"--- Raw Generator Response ({file_name}) ---\n{generated_code}\n--------------------------------------")
        
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
        print("--- 🔍 CODE VALIDATOR AGENT ---")
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
        print("--- 🚀 DEPLOYER AGENT ---")
        if not state.get("validation_passed"):
            return {"deployment_report": "Skipping deployment because validation failed."}
        
        files = state["generated_files"]
        # Invoke the tool that runs `terraform apply`
        deployment_report = terraform_apply_tool.invoke({"files": files})
        print(f"--- Deployment Report ---\n{deployment_report}\n-------------------------")
        
        return {"deployment_report": deployment_report}

class SecurityScannerAgent:
    """Scans the validated Terraform code for security vulnerabilities using tfsec."""
    def run(self, state: GraphState):
        print("--- 🛡️ SECURITY SCANNER AGENT ---")
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