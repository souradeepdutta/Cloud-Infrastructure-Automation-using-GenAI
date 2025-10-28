## **Project Context: AI-Powered Terraform Generator**

### 1. Core Directives (Your Instructions)

* **LocalStack Only:** All code is for **LocalStack v3.5.0**. All AWS provider configurations and resource attributes must be compatible with it.
* **Follow Patterns:** Match existing code style, agent structure, and state management logic. Do not introduce new patterns.
* **No Guessing:** If the user request or an error is ambiguous, ask for clarification.
* **Complete Code:** Do not provide partial implementations, TODO comments, or placeholders.

---

### 2. Project Overview

* **Goal:** Convert a user's natural language request into secure, valid Terraform HCL code and deploy it to a local LocalStack instance.
* **Core Tech:**
    * **Workflow:** LangGraph (Python)
    * **UI:** Streamlit
    * **IaC:** Terraform
    * **Security:** `tfsec`
    * **Emulator:** LocalStack (AWS)
    * **LLM:** Google Gemini

---

### 3. Agent Workflow (Sequential)

The system is a 5-agent graph. State is passed sequentially.

1.  **Planner Architect Agent**
    * **Input:** User request (e.g., "create an S3 bucket") and any previous error reports.
    * **Task:** Reads `TFSEC_RULES.md` for context. Creates a step-by-step plan and a JSON list of files to be created (e.g., `provider.tf`, `main.tf`, `variables.tf`) with detailed briefs for each.
    * **Output:** JSON `{ "plan": "...", "files": [...] }`

2.  **Code Generator Agent**
    * **Input:** The `files` list from the Planner.
    * **Task:** Loops through the list, generating HCL code for *one file at a time*. It pops a file, generates code, and adds it to the `generated_files` state. It also cleans any markdown fences (like ` ```hcl `) from the LLM output.
    * **Output:** A dictionary of `generated_files` (filename -> HCL code).

3.  **Code Validator Agent**
    * **Input:** All `generated_files`.
    * **Task:** Saves files to `terraform_work/` and runs `terraform init`, `terraform validate`, and `terraform fmt`.
    * **Output:** Success message with formatted code, or a detailed error report.

4.  **Security Scanner Agent**
    * **Input:** Validated HCL files.
    * **Task:** Runs `tfsec` in the `terraform_work/` directory to find security issues.
    * **Output:** Success message or a detailed security report.

5.  **Deployer Agent**
    * **Input:** Validated and secure HCL files.
    * **Task:** Runs `terraform apply -auto-approve` to deploy the resources to LocalStack.
    * **Output:** `terraform apply` output.

---

### 4. Core Workflow State (`GraphState`)

This `TypedDict` is passed between all agents. These are the most important keys:

* `initial_request: str`: The user's original prompt.
* `file_structure: List`: The queue of files for the Code Generator.
* `generated_files: Dict`: The dictionary of generated code.
* `validation_report: str`: Error output from `terraform validate` or `tfsec`.
* `security_report: str`: Error output from `tfsec`.
* `validation_passed: bool`: Flag set by Validator.
* `security_passed: bool`: Flag set by Security Scanner.
* `retry_count: int`: Tracks the number of retries (max 3).

---

### 5. Tool, Command, & Constant Reference

The agents use tools that run these specific shell commands and values.

* **`terraform_validate_tool`:**
    * `terraform init -no-color -input=false -upgrade=false`
    * `terraform validate -no-color`
    * `terraform fmt -recursive`

* **`terraform_security_scan_tool`:**
    * `tfsec . --no-color --format default --minimum-severity HIGH --exclude aws-s3-encryption-customer-key,aws-s3-enable-bucket-logging`
    * *(Note the exclusions for S3 encryption and logging)*

* **`terraform_apply_tool`:**
    * `terraform apply -auto-approve -no-color -parallelism=1`
    * *(Note: `parallelism=1` is used for LocalStack stability)*

* **LocalStack Constants (Non-negotiable):**
    * **Region:** `us-east-1`
    * **Access Key:** `test`
    * **Secret Key:** `test`
    * **Endpoint URL:** `http://localhost:4566`
    * **S3 Path Style:** `true`

---

### 6. Critical Security Rules (Summary of `TFSEC_RULES.md`)

The **Planner Architect** must enforce these.

* **S3 Buckets:** Always require 4 separate resources:
    1.  `aws_s3_bucket`
    2.  `aws_s3_bucket_server_side_encryption_configuration` (use `AES256`)
    3.  `aws_s3_bucket_public_access_block` (all 4 settings `true`)
    4.  `aws_s3_bucket_versioning` (`status = "Enabled"`)
* **EC2 Instances:**
    * `associate_public_ip_address = false`
    * `metadata_options { http_tokens = "required" }`
    * All EBS volumes must have `encrypted = true`
* **DynamoDB Tables:**
    * `server_side_encryption { enabled = true }`
    * `point_in_time_recovery { enabled = true }`
* **RDS Databases:**
    * `storage_encrypted = true`
    * `publicly_accessible = false`

---

### 7. Routing & Retry Logic

* **Code Generation:** The workflow loops back to the `Code Generator` agent until the `file_structure` list is empty.
* **Failure:** If `Code Validator` or `Security Scanner` fails, the router triggers a retry.
* **Retry:** A "retry" means the workflow **returns to the Planner Architect agent**. The `validation_report` (containing the error) is passed back as context, and `retry_count` is incremented.
* **Max Retries:** The workflow stops after 3 failed retries.