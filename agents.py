# agents.py
from dotenv import load_dotenv
load_dotenv()

import os
import json
from typing import TypedDict, Annotated, List, Dict
from langgraph.graph.message import add_messages
from langchain_google_genai import ChatGoogleGenerativeAI
# Make sure 'tools.py' is in the same directory and contains the tool definitions
from tools import terraform_validate_tool, terraform_apply_tool

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

class PlannerAgent:
    """Creates the initial high-level plan based on the user's request."""
    def run(self, state: GraphState):
        print("--- 🧠 PLANNER AGENT ---")
        error_context = ""
        # If a previous run failed, add the error report to the context for the LLM to fix.
        if state.get("validation_report") and not state.get("validation_passed"):
            error_context = f"""
An attempt to generate and validate code has failed. Create a new, simpler plan to fix the errors below.
Focus on the simplest possible resource structure to meet the original request.
Validation Errors:
{state['validation_report']}
"""
        prompt = f"""You are an expert infrastructure planner for AWS running on LocalStack. Your job is to create a high-level, step-by-step plan in plain English.

**CRITICAL RULES:**
1.  Read the user's request and any error context carefully.
2.  Your output MUST be a numbered list of simple, high-level steps.
3.  **DO NOT WRITE ANY HCL CODE OR TERRAFORM SNIPPETS.** Your role is to plan, not to code.
4.  The plan should only include the AWS resources the user explicitly asked for. Do not add extra complexity.
5.  If there are validation errors, your plan should aim to simplify the approach.

**User Request:** "{state['initial_request']}"
{state.get('human_feedback', '')}
{error_context}

Provide a concise, step-by-step plan in plain English for deploying this on AWS via LocalStack.
"""
        response = llm.invoke(prompt)
        print(f"--- Raw Planner Response ---\n{response.content}\n--------------------------")
        # Reset state for the new plan
        return {
            "plan": response.content,
            "generated_files": {},
            "file_structure": [],
            "validation_report": ""
        }

class FileArchitectAgent:
    """Decides which .tf files are needed and what their purpose is."""
    def run(self, state: GraphState):
        print("--- 🏛️ FILE ARCHITECT AGENT ---")
        prompt = f"""You are a Terraform file architect. Based on the plan, define the project structure by specifying which files to create and a clear, one-sentence brief for each.

**RULES:**
1.  Always create a `provider.tf` to configure the AWS provider for LocalStack.
2.  If the plan involves configurable values, create a `variables.tf`.
3.  The main resources go into `main.tf`.
4.  If resources produce outputs, create an `outputs.tf`.
5.  Your output **MUST** be a valid JSON list of objects, with "file_name" and "brief" keys.

**Plan:**
{state['plan']}

Provide your response as a JSON list.
"""
        response = llm.invoke(prompt)
        print(f"--- Raw Architect Response ---\n{response.content}\n----------------------------")
        try:
            # Clean up potential markdown formatting from the LLM response
            cleaned_response = response.content.strip().replace("```json", "").replace("```", "")
            file_structure = json.loads(cleaned_response)
            return {"file_structure": file_structure}
        except json.JSONDecodeError:
            print("❌ ERROR: Architect agent did not return valid JSON.")
            return {"file_structure": []}

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