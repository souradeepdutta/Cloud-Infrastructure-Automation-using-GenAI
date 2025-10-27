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

def _load_security_rules():
    """Load security rules from TFSEC_RULES.md file."""
    try:
        rules_file = os.path.join(os.path.dirname(__file__), "TFSEC_RULES.md")
        with open(rules_file, 'r', encoding='utf-8') as f:
            content = f.read()
            # Extract just the rules sections, not the full doc
            lines = content.split('\n')
            rules = []
            capture = False
            for line in lines:
                if '**CRITICAL' in line or 'Constants (Always True' in line or 'Instance Type RAM' in line:
                    capture = True
                if capture and line.strip():
                    rules.append(line)
                if line.startswith('---'):
                    break
            return '\n'.join(rules)
    except Exception as e:
        print(f"⚠️ Could not load TFSEC_RULES.md: {e}")
        # Fallback rules
        return """
EC2: metadata_options{http_tokens=required} + associate_public_ip_address=false + ebs_block_device{encrypted=true}
S3: aws_s3_bucket_server_side_encryption_configuration(AES256) + aws_s3_bucket_public_access_block(all=true) + aws_s3_bucket_versioning(Enabled)
DynamoDB: server_side_encryption{enabled=true} + point_in_time_recovery{enabled=true}
Lambda: tracing_config{mode=Active}
RDS: storage_encrypted=true + publicly_accessible=false + backup_retention_period>=7
Constants: ami=ami-ff0fea8310f3, region=us-east-1, endpoint=http://localhost:4566
RAM: 2GB=t3.small, 4GB=t3.medium, 8GB=t3.large, 16GB=t3.xlarge
"""

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
    """Creates plan AND file structure. Learns from validation/security errors."""
    def run(self, state: GraphState):
        print("\n🧠 Planning architecture...")
        
        # Load security rules from file
        security_rules = _load_security_rules()
        
        # Build feedback from previous failures
        feedback = ""
        if state.get("validation_report") and not state.get("validation_passed"):
            feedback = f"\n\n🔴 PREVIOUS VALIDATION ERRORS:\n{state['validation_report']}\n\n"
            feedback += "👉 Analyze WHY these errors occurred and FIX them in the new plan.\n"
            feedback += "Common fixes: Check resource names, syntax, required parameters, security configs.\n"
        
        if state.get("security_report") and not state.get("security_passed"):
            feedback += f"\n\n🛡️ SECURITY SCAN FAILURES:\n{state['security_report']}\n\n"
            feedback += "👉 These are tfsec policy violations. Review the SECURITY RULES below and ensure ALL are implemented.\n"
        
        if state.get('human_feedback'):
            feedback += f"\n\n💬 USER FEEDBACK:\n{state['human_feedback']}\n"
        
        prompt = f"""You are an expert Terraform architect. Create infrastructure for: "{state['initial_request']}"
{feedback}

📋 SECURITY RULES (from tfsec - MUST implement ALL relevant ones):
{security_rules}

🧠 REASONING PROCESS:
1. What AWS resources are needed? (EC2, S3, DynamoDB, Lambda, RDS, etc.)
2. How many instances/resources? (Use `count` parameter for multiple)
3. What specifications? (RAM → instance_type, storage size, etc.)
4. Which security rules apply? (Check the rules above for each resource type)
5. Are all mandatory security configurations included?

⚡ IMPORTANT:
- Be SPECIFIC in briefs - include actual parameter names and values
- For EC2: Always include ami, instance_type, associate_public_ip_address, metadata_options, ebs_block_device
- For S3: Create SEPARATE resources for encryption, public_access_block, and versioning
- Use count parameter for multiple identical resources

OUTPUT VALID JSON:
{{
  "plan": "1. Configure LocalStack provider\\n2. Create X [resources] with Y [specs]\\n3. Apply security configurations\\n4. Add appropriate tags",
  "files": [
    {{"file_name": "provider.tf", "brief": "AWS provider configuration: region=us-east-1, access_key=test, secret_key=test, skip_credentials_validation=true, skip_metadata_api_check=true, skip_requesting_account_id=true, s3_use_path_style=true, endpoints for all services=http://localhost:4566"}},
    {{"file_name": "main.tf", "brief": "Detailed resource list: aws_instance resource_name count=5 ami=ami-ff0fea8310f3 instance_type=t3.large associate_public_ip_address=false metadata_options{{http_tokens=required}} ebs_block_device{{device_name=/dev/sda1 volume_size=30 encrypted=true}} tags{{Name=instance-${{count.index+1}}}}"}}
  ]
}}
"""
        
        response = llm.invoke(prompt)
        
        try:
            # Clean up markdown formatting
            cleaned_response = response.content.strip()
            if "```json" in cleaned_response:
                cleaned_response = cleaned_response.split("```json")[1].split("```")[0]
            elif "```" in cleaned_response:
                cleaned_response = cleaned_response.replace("```", "")
            
            parsed = json.loads(cleaned_response.strip())
            
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
    """Generates HCL code for a single file based on a detailed brief."""
    def run(self, state: GraphState):
        files_to_generate = state["file_structure"]
        if not files_to_generate:
            return {}

        # Take the next file to generate from the list
        current_file_spec = files_to_generate.pop(0)
        file_name = current_file_spec["file_name"]
        brief = current_file_spec["brief"]

        print(f"\n💻 Generating {file_name}...")
        
        # Load security rules for reference
        security_rules = _load_security_rules()
        
        prompt = f"""Generate complete, valid HCL (Terraform) code for: {file_name}

📝 BRIEF (follow exactly):
{brief}

🔐 SECURITY RULES (ensure compliance):
{security_rules}

⚡ CRITICAL REQUIREMENTS:
- Output ONLY valid HCL code, no explanations or markdown
- Follow the brief specifications exactly
- Include ALL security configurations mentioned in brief
- Use proper HCL syntax with correct block structure
- For provider.tf: Include ALL service endpoints pointing to http://localhost:4566
- For main.tf: Include complete resource blocks with all required and security parameters

📌 CONSTANTS (always use these):
- AMI for EC2: ami-ff0fea8310f3
- Region: us-east-1
- LocalStack endpoint: http://localhost:4566
- Credentials: access_key="test", secret_key="test"

Generate the complete, valid HCL code now:
"""
        
        response = llm.invoke(prompt)
        
        # Clean up markdown formatting
        generated_code = response.content.strip()
        if "```hcl" in generated_code:
            generated_code = generated_code.split("```hcl")[1].split("```")[0]
        elif "```terraform" in generated_code:
            generated_code = generated_code.split("```terraform")[1].split("```")[0]
        elif "```" in generated_code:
            # Remove any remaining markdown code fences
            generated_code = generated_code.replace("```", "")
        
        generated_code = generated_code.strip()
        print(f"✓ Generated {file_name} ({len(generated_code)} bytes)")
        
        # Store generated code
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