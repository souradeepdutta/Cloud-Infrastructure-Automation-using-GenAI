"""
Agent definitions for AWS Infrastructure Generator.
Contains all agent classes that handle planning, code generation, validation, 
security scanning, deployment, and cost estimation.
"""
import json
import os
from typing import Dict, List, TypedDict, Optional

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

from tools import (
    ToolResponseMessages,
    terraform_apply_tool,
    terraform_cost_estimate_tool,
    terraform_security_scan_tool,
    terraform_validate_tool,
)

load_dotenv()

# --- Configuration ---
MAX_RETRIES = 3

# --- Define Graph State ---
class GraphState(TypedDict, total=False):
    """State dictionary passed between agents in the workflow."""
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
    security_warning: bool  # Flag to indicate security warnings were found but deployment proceeded
    deployment_passed: bool
    retry_count: int
    cost_report: str
    cost_passed: bool
    # Error recovery fields
    error_analysis: Dict[str, str]
    needs_full_retry: bool
    fix_strategy: str
    targeted_fix_applied: bool
    targeted_fix_strategy: str
    targeted_fix_description: str


# Google Gemini
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.0,
    google_api_key=os.getenv("GOOGLE_API_KEY")
)
print("✓ Using Google Gemini API")

# GitHub Models (using OpenAI-compatible API)
# from langchain_openai import ChatOpenAI
# llm = ChatOpenAI(
#     model="gpt-5",
#     temperature=0.0,
#     api_key=os.getenv("GITHUB_TOKEN"),
#     base_url="https://models.inference.ai.azure.com",
#     default_headers={
#         "Authorization": f"Bearer {os.getenv('GITHUB_TOKEN')}"
#     }
# )
# print("✓ Using GitHub Models API")

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
S3: 4 resources - bucket + encryption(AES256) + public_access_block(all true) + versioning(Enabled)
EC2: metadata_options{http_tokens=required}, no public IP, encrypted EBS, security group
DynamoDB: server_side_encryption + point_in_time_recovery
Lambda: IAM role + tracing_config(Active)
RDS: storage_encrypted + not publicly_accessible + backup_retention>=7
"""


def _create_fallback_structure(initial_request: str) -> Dict:
    """Create a fallback plan structure when LLM response fails."""
    return {
        "plan": "1. Configure AWS provider\n2. Create requested resources with security",
        "file_structure": [
            {
                "file_name": "provider.tf",
                "brief": "Standard AWS provider configuration for the 'us-east-1' region."
            },
            {
                "file_name": "main.tf",
                "brief": f"Create all resources needed for: {initial_request}"
            }
        ]
    }


def _parse_llm_json_response(response_content: str) -> Dict:
    """
    Parse LLM response that may contain JSON wrapped in markdown.
    Handles both clean JSON and markdown-wrapped JSON with multiple fallback strategies.

    Args:
        response_content: Raw LLM response string

    Returns:
        Parsed JSON dictionary

    Raises:
        json.JSONDecodeError: If JSON cannot be parsed
    """
    content = response_content.strip()

    # Remove markdown code fences
    content = content.replace("```json", "").replace("```", "").strip()

    # Find JSON object boundaries
    start_idx = content.find("{")
    if start_idx == -1:
        raise json.JSONDecodeError("No JSON object found", content, 0)

    # Find the matching closing brace
    brace_count = 0
    end_idx = -1

    for i in range(start_idx, len(content)):
        if content[i] == '{':
            brace_count += 1
        elif content[i] == '}':
            brace_count -= 1
            if brace_count == 0:
                end_idx = i + 1
                break

    if end_idx == -1:
        raise json.JSONDecodeError("No matching closing brace", content, start_idx)

    # Extract the JSON object
    json_str = content[start_idx:end_idx]
    
    # Try to parse directly first
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        # If direct parsing fails, try to clean up common issues
        # Remove trailing commas before closing braces/brackets
        import re
        cleaned_json = re.sub(r',(\s*[}\]])', r'\1', json_str)
        
        try:
            return json.loads(cleaned_json)
        except json.JSONDecodeError:
            # Last resort: try to extract just the essential fields manually
            print(f"⚠️ JSON parsing failed. Original error: {e}")
            print(f"⚠️ Problematic JSON (first 500 chars): {json_str[:500]}")
            raise


def _clean_markdown_code_fences(code: str) -> str:
    """
    Remove markdown code fences from generated code.

    Args:
        code: Raw code string possibly containing markdown fences

    Returns:
        Cleaned code string
    """
    code = code.strip()
    for fence in ["```hcl", "```terraform", "```"]:
        if fence in code:
            parts = code.split(fence)
            if len(parts) >= 2:
                code = parts[1].split("```")[0] if fence != "```" else parts[1]
                break
    return code.strip()


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

OUTPUT ONLY VALID JSON (no comments, no trailing commas):
{{
  "plan": "1. Setup provider\\n2. Create [specific resource]\\n3. Add [specific security config]",
  "files": [
    {{"file_name": "provider.tf", "brief": "Standard AWS provider for region us-east-1"}},
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
                return {
                    **_create_fallback_structure(state['initial_request']),
                    "retry_count": retry_count
                }

            print(f"✅ Plan created: {len(file_structure)} files to generate")
            return {
                "plan": plan,
                "file_structure": file_structure,
                "retry_count": retry_count
            }

        except (json.JSONDecodeError, ValueError) as e:
            print(f"⚠️ Warning: Could not parse LLM response as JSON: {e}")
            print("Using fallback structure...")
            return {
                **_create_fallback_structure(state['initial_request']),
                "retry_count": retry_count
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

        # Get FULL context from state (like chat history)
        full_context = self._build_full_context(state, file_name)

        print(f"\n💻 Generating {file_name}...")
        if full_context["has_previous_files"]:
            print(f"   📋 Context: {full_context['context_summary']}")
        
        prompt = f"""Generate HCL code for {file_name}. Output ONLY code, NO markdown, NO explanations.

{full_context["context_section"]}

Brief: {brief}

RULES:
- Follow the brief exactly - it contains all resource names and key attributes
- For provider.tf: Use a standard AWS provider configuration (region us-east-1)
- Use .id for resource references (e.g., aws_s3_bucket.name.id)
- If existing resources are listed above, reference them instead of creating duplicates
- Keep code clean and minimal
- Output pure HCL code only

**CRITICAL: Generate unique resource names using random_id**
ALWAYS include this resource at the top of main.tf to ensure unique names:
```hcl
resource "random_id" "suffix" {{
  byte_length = 4
}}
```

Then use it for ALL resource names that need to be globally/regionally unique:
- S3 buckets: bucket = "my-bucket-${{random_id.suffix.hex}}"
- Security groups: name_prefix = "my-sg-${{random_id.suffix.hex}}-"
- DynamoDB tables: name = "my-table-${{random_id.suffix.hex}}"
- Lambda functions: function_name = "my-function-${{random_id.suffix.hex}}"
- RDS instances: identifier = "my-db-${{random_id.suffix.hex}}"
- IAM roles: name = "my-role-${{random_id.suffix.hex}}"
- KMS keys: use description with timestamp (descriptions don't need to be unique)

**Correct provider.tf for AWS (include random provider):**
```hcl
terraform {{
  required_providers {{
    aws = {{
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }}
    random = {{
      source  = "hashicorp/random"
      version = "~> 3.0"
    }}
  }}
}}

provider "aws" {{
  region = "us-east-1"
}}
```

**IMPORTANT for EC2 instances:**
**NEVER hardcode AMI IDs** - they change frequently and vary by region. Use a data source:

```hcl
data "aws_ami" "amazon_linux_2" {{
  most_recent = true
  owners      = ["amazon"]

  filter {{
    name   = "name"
    values = ["amzn2-ami-hvm-*-x86_64-gp2"]
  }}

  filter {{
    name   = "virtualization-type"
    values = ["hvm"]
  }}
}}

resource "aws_instance" "example" {{
  ami           = data.aws_ami.amazon_linux_2.id  # Use data source
  instance_type = "t3.micro"
  subnet_id     = tolist(data.aws_subnets.default.ids)[0]
  
  # MANDATORY: These 3 blocks are REQUIRED for every EC2 instance
  metadata_options {{
    http_tokens   = "required"  # REQUIRED - Enable IMDSv2
    http_endpoint = "enabled"
  }}

  root_block_device {{
    encrypted = true  # REQUIRED - Encrypt root volume
  }}

  vpc_security_group_ids = [aws_security_group.example.id]
  
  # Only set to true if instance needs public access (blogs, web servers)
  associate_public_ip_address = false
}}
```

**CRITICAL FOR EC2: Always Create a Subnet**

EVERY EC2 instance MUST have a subnet_id. Use this pattern:

```hcl
data "aws_availability_zones" "available" {{
  state = "available"
}}

resource "aws_subnet" "main" {{
  vpc_id            = data.aws_vpc.default.id
  cidr_block        = "172.31.0.0/20"
  availability_zone = data.aws_availability_zones.available.names[0]
  tags = {{ Name = "main-subnet" }}
}}

# Then use: subnet_id = aws_subnet.main.id
```

**CRITICAL - DO NOT USE THESE (DEPRECATED/INVALID):**
- ❌ Hardcoded AMI IDs like "ami-12345678" (outdated/invalid/region-specific)
- ❌ aws_subnet_ids (deprecated in AWS provider 5.x - use aws_subnets instead)
- ❌ "default_for_az" filter (doesn't exist in AWS API)
- ❌ "mapPublicIpOnLaunch" filter (unreliable - avoid it)

**CORRECT Data Source:** Use `data "aws_subnets"` (plural) NOT `aws_subnet_ids`

**IMPORTANT for Security Groups:**
Use name_prefix with random_id suffix for uniqueness:
```hcl
resource "aws_security_group" "example" {{
  name_prefix = "example-sg-${{random_id.suffix.hex}}-"
  description = "Security group description"
  vpc_id      = data.aws_vpc.default.id
  
  egress {{
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }}
}}
```

**CRITICAL REMINDER FOR EC2 INSTANCES:**
EVERY aws_instance resource MUST include these (no exceptions):
1. **subnet_id** = aws_subnet.main.id (EC2 CANNOT be created without a subnet!)
2. **metadata_options** {{ http_tokens = "required", http_endpoint = "enabled" }}
3. **root_block_device** {{ encrypted = true }}
4. **vpc_security_group_ids** = [...]

For EC2, always create a subnet using the simpler approach shown above.

Now, generate the complete and correct HCL code for: {file_name}
"""
        response = llm.invoke(prompt)

        # Clean up markdown formatting
        generated_code = _clean_markdown_code_fences(response.content)

        print(f"✓ Generated {file_name} ({len(generated_code)} bytes)")

        # Update generated files
        updated_files = state.get("generated_files", {})
        updated_files[file_name] = generated_code

        return {
            "generated_files": updated_files,
            "file_structure": files_to_generate
        }
    
    def _build_full_context(self, state: GraphState, current_file: str) -> Dict:
        """Build COMPLETE context like chat history - everything is in state already!"""
        
        # Get generated files from state
        generated_files = state.get("generated_files", {})
        
        # Start with no context
        if not generated_files and not state.get("plan"):
            return {
                "has_previous_files": False,
                "context_section": "",
                "context_summary": "First file"
            }
        
        context_parts = []
        
        # 1. User's original request
        if state.get("initial_request"):
            context_parts.append(f"USER REQUEST: {state['initial_request']}")
        
        # 2. Overall plan
        if state.get("plan"):
            context_parts.append(f"\nOVERALL PLAN:\n{state['plan']}")
        
        # 3. Files already generated with their resources
        if generated_files:
            context_parts.append("\nALREADY GENERATED FILES:")
            for filename, code in generated_files.items():
                resources = self._extract_resources(code)
                context_parts.append(f"\n✓ {filename}")
                if resources:
                    context_parts.append("  Resources defined:")
                    for res in resources[:10]:  # Limit to avoid token overflow
                        context_parts.append(f"    - {res}")
        
        # 4. Remaining files to generate
        remaining_files = state.get("file_structure", [])
        if remaining_files:
            context_parts.append(f"\nREMAINING FILES: {', '.join([f['file_name'] for f in remaining_files])}")
        
        context_parts.append(f"\nCURRENT FILE: {current_file}\n")
        
        context_section = "\n".join(context_parts)
        
        # Summary for logging
        file_count = len(generated_files)
        summary = f"{file_count} files done, {len(remaining_files)} remaining"
        
        return {
            "has_previous_files": len(generated_files) > 0,
            "context_section": context_section,
            "context_summary": summary
        }
    
    def _extract_resources(self, code: str) -> List[str]:
        """Extract resource identifiers from Terraform code."""
        import re
        
        resources = []
        
        # Match: resource "type" "name"
        resource_pattern = r'resource\s+"([^"]+)"\s+"([^"]+)"'
        matches = re.findall(resource_pattern, code)
        for resource_type, resource_name in matches:
            resources.append(f"{resource_type}.{resource_name}")
        
        # Match: data "type" "name"
        data_pattern = r'data\s+"([^"]+)"\s+"([^"]+)"'
        data_matches = re.findall(data_pattern, code)
        for data_type, data_name in data_matches:
            resources.append(f"data.{data_type}.{data_name}")
        
        return resources


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
            
            # Extract only the error portion
            error_lines = []
            capture = False
            for line in validation_report.split('\n'):
                if 'Error:' in line or 'error' in line.lower():
                    capture = True
                if capture:
                    error_lines.append(line)
                    if line.strip() == '' and len(error_lines) > 5:
                        break
            
            error_summary = '\n'.join(error_lines[:30])  # Limit to 30 lines
            
            print("\n" + "=" * 80)
            print("VALIDATION ERROR:")
            print("=" * 80)
            print(error_summary)
            print("=" * 80 + "\n")

        return {
            "validation_report": validation_report,
            "validation_passed": validation_passed,
            "generated_files": formatted_files
        }


class DeployerAgent:
    """Deploys the validated code to AWS."""
    
    def run(self, state: GraphState):
        print("\n🚀 Deploying to AWS...")
        if not state.get("validation_passed"):
            return {"deployment_report": "Skipping deployment because validation failed."}
        
        if not state.get("security_passed"):
            return {"deployment_report": "Skipping deployment because security scan failed."}
        
        files = state["generated_files"]
        deployment_report = terraform_apply_tool.invoke({"files": files})
        
        # Check if deployment actually succeeded
        if "Terraform apply successful" in deployment_report:
            print("✅ Deployment complete")
            return {
                "deployment_report": deployment_report,
                "deployment_passed": True
            }
        else:
            print("❌ Deployment failed")
            
            # Extract only the error portion (after "Error:" keyword)
            error_lines = []
            capture = False
            for line in deployment_report.split('\n'):
                if 'Error:' in line or 'error' in line.lower():
                    capture = True
                if capture:
                    error_lines.append(line)
                    # Stop after capturing the error block
                    if line.strip() == '' and len(error_lines) > 5:
                        break
            
            error_summary = '\n'.join(error_lines[:30])  # Limit to 30 lines
            
            print("\n" + "=" * 80)
            print("DEPLOYMENT ERROR:")
            print("=" * 80)
            print(error_summary)
            print("=" * 80 + "\n")
            
            # Treat deployment failure as validation failure to trigger retry
            existing_report = state.get("validation_report", "")
            combined_report = f"{existing_report}\n\n--- DEPLOYMENT ERRORS ---\n{deployment_report}"
            return {
                "deployment_report": deployment_report,
                "deployment_passed": False,
                "validation_report": combined_report,
                "validation_passed": False  # Mark validation as failed to trigger retry
            }


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
            print("⚠️  tfsec security scan found issues.")
            print("⚠️  Proceeding with deployment - security warnings will be shown to user")
            
            # Option B: Deploy anyway but warn the user
            # This is more practical for development/testing while still informing about risks
            return {
                "security_report": security_report,
                "security_passed": True,  # Allow deployment to proceed
                "security_warning": True  # Flag for UI to show prominent warning
            }


class CostEstimatorAgent:
    """Estimates infrastructure costs from deployed resources (post-deployment analysis)."""
    
    def run(self, state: GraphState):
        print("\n💰 Analyzing deployed resource costs...")
        print(f"   Deployment passed: {state.get('deployment_passed', False)}")
        
        files = state["generated_files"]
        
        cost_report = terraform_cost_estimate_tool.invoke({"files": files})
        
        # Cost estimation is informational - always pass (never blocks)
        cost_passed = True
        
        # Check if cost estimation was successful
        if "Cost estimation unavailable" in cost_report:
            print("⚠️ Cost estimation unavailable - no resources deployed yet.")
        else:
            print("✅ Cost analysis complete.")
        
        print(f"   Cost report length: {len(cost_report)} chars")
        
        return {
            "cost_report": cost_report,
            "cost_passed": cost_passed
        }


class ErrorAnalyzerAgent:
    """Analyzes errors and determines if targeted fix is possible."""
    
    def run(self, state: GraphState):
        print("\n🔍 Analyzing error...")
        
        # Determine which error we're dealing with
        error_report = ""
        error_type = ""
        
        if not state.get("validation_passed"):
            error_report = state.get("validation_report", "")
            error_type = "validation"
        elif not state.get("security_passed"):
            error_report = state.get("security_report", "")
            error_type = "security"
        elif not state.get("deployment_passed"):
            error_report = state.get("deployment_report", "")
            error_type = "deployment"
        
        if not error_report:
            print("❌ No error report found")
            return {"needs_full_retry": True, "error_analysis": "No error report"}
        
        # Pattern matching for common fixable errors
        fixable, analysis = self._analyze_error_pattern(error_report, error_type)
        
        if fixable:
            print(f"✅ Fixable error detected: {analysis['category']}")
            print(f"   Strategy: {analysis['strategy']}")
            return {
                "needs_full_retry": False,
                "error_analysis": analysis,
                "fix_strategy": analysis['strategy']
            }
        else:
            print(f"⚠️ Complex error - needs full retry")
            return {
                "needs_full_retry": True,
                "error_analysis": analysis
            }
    
    def _analyze_error_pattern(self, error_report: str, error_type: str) -> tuple:
        """Pattern match common errors."""
        import re
        
        error_lower = error_report.lower()
        
        # For security errors, don't apply targeted fixes - always do full retry
        # This prevents false positives from security warnings
        if error_type == "security":
            # Check if these are just warnings vs actual blocking errors
            if "high" in error_lower or "critical" in error_lower:
                return False, {
                    "category": "security_issues",
                    "strategy": "full_retry",
                    "fix_description": "Security issues require full regeneration with updated requirements"
                }
            else:
                # Minor security warnings - should not block deployment
                return False, {
                    "category": "security_warning",
                    "strategy": "skip",
                    "fix_description": "Minor security warnings - can proceed with deployment"
                }
        
        # Define error patterns with their metadata
        error_patterns = [
            {
                "keywords": ["already exists", "alreadyexists"],
                "category": "resource_exists",
                "strategy": "add_random_suffix",
                "description_template": "Add random_id suffix to {resource}",
                "extract_resource": lambda report: self._extract_resource_from_report(report)
            },
            {
                "keywords": ["db_subnet_group_name", "elasticache_subnet_group_name", "cache_subnet_group_name"],
                "required_keywords": ["not found", "does not exist", "missing", "invalid", "required"],
                "category": "missing_subnet_group",
                "strategy": "add_subnet_group",
                "description_template": "Add missing DB/cache subnet group resource"
            },
            {
                "keywords": ["security group", "security_group"],
                "additional_keywords": ["not found", "does not exist"],
                "category": "missing_security_group",
                "strategy": "add_security_group",
                "description_template": "Add missing security group resource"
            },
            {
                "keywords": ["reference", "depends on", "no resource"],
                "category": "invalid_reference",
                "strategy": "fix_reference",
                "description_template": "Fix invalid resource reference"
            },
            {
                "keywords": ["iam"],
                "additional_keywords": ["role", "policy"],
                "required_keywords": ["not found", "does not exist"],
                "category": "missing_iam",
                "strategy": "add_iam_role",
                "description_template": "Add missing IAM role/policy"
            }
        ]
        
        # Check each pattern
        for pattern in error_patterns:
            if self._matches_pattern(error_lower, pattern):
                result = {
                    "category": pattern["category"],
                    "strategy": pattern["strategy"],
                    "fix_description": pattern["description_template"]
                }
                
                # Handle resource extraction if needed
                if "extract_resource" in pattern:
                    resource = pattern["extract_resource"](error_report)
                    result["resource"] = resource
                    result["fix_description"] = pattern["description_template"].format(resource=resource)
                
                return True, result
        
        # Unknown error - needs full retry
        return False, {
            "category": "unknown",
            "strategy": "full_retry",
            "fix_description": "Complex error requiring full regeneration"
        }
    
    def _matches_pattern(self, error_lower: str, pattern: dict) -> bool:
        """Check if error matches a specific pattern."""
        # Check primary keywords
        if not any(keyword in error_lower for keyword in pattern["keywords"]):
            return False
        
        # Check additional keywords if specified
        if "additional_keywords" in pattern:
            if not any(keyword in error_lower for keyword in pattern["additional_keywords"]):
                return False
        
        # Check required keywords if specified
        if "required_keywords" in pattern:
            if not any(keyword in error_lower for keyword in pattern["required_keywords"]):
                return False
        
        return True
    
    def _extract_resource_from_report(self, error_report: str) -> str:
        """Extract resource identifier from error report."""
        import re
        match = re.search(r'resource "([^"]+)" "([^"]+)"', error_report)
        return f"{match.group(1)}.{match.group(2)}" if match else "unknown"


class TargetedFixAgent:
    """Applies targeted fixes to existing code instead of full regeneration."""
    
    def run(self, state: GraphState):
        print("\n🔧 Applying targeted fix...")
        
        analysis = state.get("error_analysis", {})
        strategy = analysis.get("strategy", "unknown")
        
        print(f"   Fix strategy: {strategy}")
        print(f"   Description: {analysis.get('fix_description', 'N/A')}")
        
        # Get full context for the fix
        context = self._build_fix_context(state)
        
        # Generate fix based on strategy
        fix_prompt = self._build_fix_prompt(state, analysis, context)
        
        # Use LLM to generate the fix
        response = llm.invoke(fix_prompt)
        fixed_code = _clean_markdown_code_fences(response.content)
        
        # Update the main.tf file (most errors are in main.tf)
        updated_files = state["generated_files"].copy()
        updated_files["main.tf"] = fixed_code
        
        print(f"✓ Targeted fix applied to main.tf")
        
        return {
            "generated_files": updated_files,
            "targeted_fix_applied": True,
            "targeted_fix_strategy": strategy,
            "targeted_fix_description": analysis.get('fix_description', 'N/A')
        }
    
    def _build_fix_context(self, state: GraphState) -> str:
        """Build full context for the fix (like chat history)."""
        context_parts = []
        
        # User request
        if state.get("initial_request"):
            context_parts.append(f"USER REQUEST: {state['initial_request']}")
        
        # Plan
        if state.get("plan"):
            context_parts.append(f"\nPLAN:\n{state['plan']}")
        
        # Error details
        error_type = "validation"
        if not state.get("validation_passed"):
            error_report = state.get("validation_report", "")
        elif not state.get("security_passed"):
            error_report = state.get("security_report", "")
            error_type = "security"
        else:
            error_report = state.get("deployment_report", "")
            error_type = "deployment"
        
        context_parts.append(f"\nERROR TYPE: {error_type}")
        context_parts.append(f"ERROR DETAILS:\n{error_report}")
        
        return "\n".join(context_parts)
    
    def _build_fix_prompt(self, state: GraphState, analysis: Dict, context: str) -> str:
        """Build prompt for targeted fix."""
        strategy = analysis.get("strategy", "unknown")
        current_code = state["generated_files"].get("main.tf", "")
        
        base_prompt = f"""You are fixing a Terraform error. Apply ONLY the specific fix needed.

{context}

CURRENT CODE (main.tf):
```hcl
{current_code}
```

FIX NEEDED: {analysis.get('fix_description', 'Fix the error')}

"""
        
        # Strategy-specific instructions
        if strategy == "add_random_suffix":
            resource = analysis.get('resource', 'unknown')
            base_prompt += f"""
SPECIFIC FIX:
The resource '{resource}' already exists. Add random_id suffix for uniqueness.

Example:
- BEFORE: bucket = "my-bucket"
- AFTER: bucket = "my-bucket-${{random_id.suffix.hex}}"

Make sure random_id resource exists at the top. Output the COMPLETE fixed main.tf:
"""
        
        elif strategy == "add_subnet_group":
            base_prompt += """
SPECIFIC FIX:
Add the missing subnet group resource (aws_db_subnet_group or aws_elasticache_subnet_group).

Use existing subnets from VPC (data.aws_subnets.default.ids or create new subnets).
Then update the DB/cache resource to reference it.

Output the COMPLETE fixed main.tf:
"""
        
        elif strategy == "add_security_group":
            base_prompt += """
SPECIFIC FIX:
Add the missing security group with appropriate rules.

Consider what the resource needs:
- RDS needs port 5432 (PostgreSQL) or 3306 (MySQL)
- Redis/Memcached needs port 6379/11211
- Web servers need port 80/443

Output the COMPLETE fixed main.tf:
"""
        
        elif strategy == "fix_reference":
            base_prompt += """
SPECIFIC FIX:
Fix the invalid resource reference.

Check:
1. Resource exists and is spelled correctly
2. Use correct syntax: resource_type.name.attribute
3. Common attributes: .id (most), .arn (IAM), .name (some)

Output the COMPLETE fixed main.tf:
"""
        
        elif strategy == "add_iam_role":
            base_prompt += """
SPECIFIC FIX:
Add the missing IAM role and/or policy.

Include:
1. IAM role with assume_role_policy
2. IAM policy with required permissions
3. IAM role policy attachment

Output the COMPLETE fixed main.tf:
"""
        
        else:
            base_prompt += """
Analyze the error and fix it. Output the COMPLETE fixed main.tf:
"""
        
        return base_prompt


