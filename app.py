# app.py
import time
import uuid
from typing import Any, Dict, Optional, Tuple, List

import streamlit as st
 
from workflow import build_workflow
from tools import terraform_destroy_tool, save_files_to_disk

# --- Configuration ---
MAX_RETRIES = 3

# --- Page Configuration ---
st.set_page_config(
    page_title="AWS Infrastructure Generator",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Custom CSS ---
st.markdown("""
<style>
    /* Import Inter font */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    
    /* Apply Inter font globally */
    html, body, [class*="css"] {
        font-family: 'Inter';
    }
    
    /* Center the main content */
    .block-container {
        max-width: 1200px;
        padding-left: 3rem;
        padding-right: 3rem;
        margin: 0 auto;
    }
    
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        text-align: center;
        margin-bottom: 1rem;
    }
    
    .sub-header {
        font-size: 1.2rem;
        color: #666;
        text-align: center;
        margin-bottom: 2rem;
    }
</style>
""", unsafe_allow_html=True)

# --- Initialize Session State ---
def initialize_session_state():
    """Initialize all session state variables with default values."""
    defaults = {
        "thread_id": str(uuid.uuid4()),
        "generated_files": {},
        "validation_passed": False,
        "security_passed": False,
        "deployment_passed": False,
        "validation_report": "",
        "security_report": "",
        "deployment_report": "",
        "cost_report": "",
        "cost_passed": False,
        "process_complete": False,
        "elapsed_time": 0,
        "plan": "",
        "workflow_outputs": [],  # List of all workflow runs (including retries)
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    
    if "config" not in st.session_state:
        st.session_state.config = {"configurable": {"thread_id": st.session_state.thread_id}}

initialize_session_state()

# --- Build workflow ---
app = build_workflow()


# --- UI Layout ---
st.markdown('<div class="main-header">AWS Infrastructure Generator</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">AWS-powered Infrastructure as Code</div>', unsafe_allow_html=True)

# --- Sidebar ---
with st.sidebar:
    st.header("📋 About")
    st.info("""
    This tool generates Terraform code for AWS infrastructure and deploys it to the cloud.
    
    **Features:**
    - 🧠 AI-powered architecture planning
    - 💻 Terraform code generation
    - 🔍 Syntax validation
    - 🛡️ Security scanning (tfsec)
    - 🚀 AWS deployment
    """)
    
    st.header("⚙️ Settings")
    st.metric("Max Retries", MAX_RETRIES)
    st.metric("Session ID", st.session_state.thread_id[:8] + "...")
    
    st.divider()
    
    if st.button("🔄 Reset Session", use_container_width=True):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()


# --- Helper Functions for Processing ---
def run_workflow_with_progress(inputs: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], float, List[Dict[str, Any]]]:
    """Execute the workflow and capture agent outputs."""
    
    start_time = time.time()
    
    # Track all workflow runs (including retries)
    all_runs = []
    current_run = {
        "retry": 0,
        "agents": {
            "planner": {"status": "pending", "output": ""},
            "code_generator": {"status": "pending", "output": ""},
            "code_validator": {"status": "pending", "output": ""},
            "security_scanner": {"status": "pending", "output": ""},
            "cost_estimator": {"status": "pending", "output": ""},
            "deployer": {"status": "pending", "output": ""}
        }
    }
    
    try:
        events = app.stream(inputs, st.session_state.config, stream_mode="values")
        final_state = None
        last_retry_count = 0
        
        for event in events:
            final_state = event
            current_retry = event.get("retry_count", 0)
            
            # If retry count increased, save the previous run and start a new one
            if current_retry > last_retry_count:
                all_runs.append(current_run)
                last_retry_count = current_retry
                current_run = {
                    "retry": current_retry,
                    "agents": {
                        "planner": {"status": "pending", "output": ""},
                        "code_generator": {"status": "pending", "output": ""},
                        "code_validator": {"status": "pending", "output": ""},
                        "security_scanner": {"status": "pending", "output": ""},
                        "cost_estimator": {"status": "pending", "output": ""},
                        "deployer": {"status": "pending", "output": ""}
                    }
                }
            
            # Track planner output
            if event.get("plan"):
                current_run["agents"]["planner"]["status"] = "complete"
                current_run["agents"]["planner"]["output"] = event.get("plan", "")
            
            # Track code generator output
            if event.get("generated_files"):
                current_run["agents"]["code_generator"]["status"] = "complete"
                files = event.get("generated_files", {})
                current_run["agents"]["code_generator"]["output"] = "\n\n".join([
                    f"**{filename}**\n```hcl\n{code}\n```" 
                    for filename, code in files.items()
                ])
            
            # Track validator output
            if event.get("validation_report"):
                current_run["agents"]["code_validator"]["status"] = "complete"
                current_run["agents"]["code_validator"]["output"] = event.get("validation_report", "")
            
            # Track security scanner output
            if event.get("security_report"):
                current_run["agents"]["security_scanner"]["status"] = "complete"
                current_run["agents"]["security_scanner"]["output"] = event.get("security_report", "")
            
            # Track cost estimator output
            if event.get("cost_report"):
                current_run["agents"]["cost_estimator"]["status"] = "complete"
                current_run["agents"]["cost_estimator"]["output"] = event.get("cost_report", "")
                print(f"📊 Cost report captured: {len(event.get('cost_report', ''))} chars")
            
            # Track deployer output
            if event.get("deployment_report"):
                current_run["agents"]["deployer"]["status"] = "complete"
                current_run["agents"]["deployer"]["output"] = event.get("deployment_report", "")
        
        # Add the final run
        all_runs.append(current_run)
        
        elapsed_time = time.time() - start_time
        
        # Print to terminal
        print(f"\n✅ Process complete! Time taken: {elapsed_time:.1f}s")
        
        return final_state, elapsed_time, all_runs
        
    except Exception as e:
        print(f"\n❌ Error occurred: {type(e).__name__}: {str(e)}")
        elapsed_time = time.time() - start_time
        all_runs.append(current_run)
        return None, elapsed_time, all_runs


def update_session_state_from_workflow(final_state: Optional[Dict[str, Any]], elapsed_time: float, all_runs: List[Dict[str, Any]]) -> None:
    """Update session state with workflow results."""
    if final_state:
        st.session_state.generated_files = final_state.get("generated_files", {})
        st.session_state.validation_passed = final_state.get("validation_passed", False)
        st.session_state.security_passed = final_state.get("security_passed", False)
        st.session_state.deployment_passed = final_state.get("deployment_passed", False)
        st.session_state.validation_report = final_state.get("validation_report", "")
        st.session_state.security_report = final_state.get("security_report", "")
        st.session_state.deployment_report = final_state.get("deployment_report", "")
        st.session_state.cost_report = final_state.get("cost_report", "")
        st.session_state.cost_passed = final_state.get("cost_passed", False)
        st.session_state.plan = final_state.get("plan", "")
        st.session_state.process_complete = True
        st.session_state.elapsed_time = elapsed_time
        
        # Store all workflow runs
        st.session_state.workflow_outputs = all_runs


# --- Main Content ---
st.subheader("What would you like to build?")

user_input = st.text_area(
    "What would you like to build?",
    height=100,
    placeholder="Example: Create an S3 bucket for storing user uploads with versioning enabled",
    key="user_input",
    label_visibility="collapsed"
)

generate_btn = st.button("Generate Infrastructure", type="primary", use_container_width=True)

# --- Process Generation ---
if generate_btn and user_input:
    st.session_state.process_complete = False
    st.session_state.workflow_outputs = []  # Clear previous outputs
    
    inputs = {
        "initial_request": user_input,
        "human_feedback": "",
        "retry_count": 0,
    }
    
    with st.spinner("🚀 Processing your request..."):
        final_state, elapsed_time, all_runs = run_workflow_with_progress(inputs)
    
    if final_state is not None:
        update_session_state_from_workflow(final_state, elapsed_time, all_runs)
        st.rerun()
    else:
        st.session_state.process_complete = False
        st.warning("Workflow failed. Please try again.")

# --- Display Results ---
if st.session_state.process_complete:
    st.divider()
    
    # Time taken in small corner
    st.markdown(
        f'<div style="text-align: right; font-size: 0.9rem; color: #666;">Time taken: {st.session_state.elapsed_time:.1f} sec</div>',
        unsafe_allow_html=True
    )
    
    # Display workflow outputs (including retries)
    for idx, workflow_run in enumerate(st.session_state.workflow_outputs):
        retry_num = workflow_run["retry"]
        agents = workflow_run["agents"]
        
        # Show retry header if this is a retry
        if retry_num > 0:
            st.markdown(f"### 🔄 Retry {retry_num}")
        
        # Planner Agent
        with st.expander("Planner Agent", expanded=(idx == len(st.session_state.workflow_outputs) - 1)):
            if agents["planner"]["status"] == "complete":
                st.markdown("✅ **Status:** Complete")
                st.markdown("**Output:**")
                st.text(agents["planner"]["output"])
            else:
                st.markdown("⏳ **Status:** Pending")
        
        # Code Generator Agent
        with st.expander("Code generator agent", expanded=False):
            if agents["code_generator"]["status"] == "complete":
                st.markdown("✅ **Status:** Complete")
                st.markdown("**Output:**")
                st.markdown(agents["code_generator"]["output"])
            else:
                st.markdown("⏳ **Status:** Pending")
        
        # Code Validator Agent
        with st.expander("Code Validator agent", expanded=False):
            if agents["code_validator"]["status"] == "complete":
                st.markdown("✅ **Status:** Complete")
                st.markdown("**Terminal Output:**")
                
                output = agents["code_validator"]["output"]
                
                # Check if validation passed or failed
                if "Validation successful" in output:
                    st.success("✅ Validation Passed")
                else:
                    st.error("❌ Validation Failed")
                
                # Show full verbose output
                with st.expander("Show verbose terminal output", expanded=False):
                    st.code(output, language="")
            else:
                st.markdown("⏳ **Status:** Pending")
        
        # Security Scanner Agent
        with st.expander("Security Scanner Agent", expanded=False):
            if agents["security_scanner"]["status"] == "complete":
                st.markdown("✅ **Status:** Complete")
                st.markdown("**Terminal Output:**")
                
                output = agents["security_scanner"]["output"]
                
                # Check if security scan passed or failed
                if "No security issues detected" in output or "security scan passed" in output:
                    st.success("✅ Security Scan Passed")
                else:
                    st.warning("⚠️ Security Issues Found")
                
                # Show full verbose output
                with st.expander("Show verbose terminal output", expanded=False):
                    st.code(output, language="")
            else:
                st.markdown("⏳ **Status:** Pending")
        
        # Deployer Agent
        with st.expander("Deployer agent", expanded=False):
            if agents["deployer"]["status"] == "complete":
                st.markdown("✅ **Status:** Complete")
                st.markdown("**Terminal Output:**")
                
                output = agents["deployer"]["output"]
                
                # Check if deployment succeeded
                if "Terraform apply successful" in output or "Apply complete" in output:
                    st.success("✅ Deployment Successful")
                else:
                    st.error("❌ Deployment Failed")
                
                # Show full verbose output
                with st.expander("Show verbose terminal output", expanded=True):
                    st.code(output, language="")
            else:
                st.markdown("⏳ **Status:** Pending")
        
        # Cost Estimator Agent (runs AFTER deployment)
        with st.expander("💰 Cost Estimator Agent", expanded=True):
            if agents["cost_estimator"]["status"] == "complete":
                st.markdown("✅ **Status:** Complete")
                st.markdown("**Deployed Resource Cost Analysis:**")
                
                cost_output = agents["cost_estimator"]["output"]
                
                # Check if cost estimation is unavailable
                if "Cost estimation unavailable" in cost_output:
                    st.info(cost_output)
                else:
                    # Parse and display cost data in a nice format
                    lines = cost_output.split('\n')
                    
                    # Extract total cost
                    total_cost = "N/A"
                    for line in lines:
                        if "ESTIMATED MONTHLY COST:" in line:
                            total_cost = line.split("$")[1].strip() if "$" in line else "N/A"
                            break
                    
                    # Display total with metric
                    st.metric("💰 Estimated Monthly Cost", f"${total_cost}")
                    
                    # Parse cost breakdown for table
                    breakdown_data = []
                    in_breakdown = False
                    for line in lines:
                        if "COST BREAKDOWN:" in line:
                            in_breakdown = True
                            continue
                        if in_breakdown and "|" in line and "----" not in line and "TOTAL" not in line.upper():
                            parts = [p.strip() for p in line.split("|") if p.strip()]
                            if len(parts) == 3:
                                breakdown_data.append({
                                    "Service": parts[0],
                                    "Resource": parts[1],
                                    "Monthly Cost": parts[2]
                                })
                        if "💡 COST OPTIMIZATION SUGGESTIONS:" in line:
                            break
                    
                    # Display breakdown table
                    if breakdown_data:
                        st.markdown("#### 📊 Cost Breakdown")
                        import pandas as pd
                        df = pd.DataFrame(breakdown_data)
                        st.dataframe(df, use_container_width=True, hide_index=True)
                    
                    # Extract and display suggestions
                    suggestions = []
                    in_suggestions = False
                    for line in lines:
                        if "💡 COST OPTIMIZATION SUGGESTIONS:" in line:
                            in_suggestions = True
                            continue
                        if in_suggestions and line.strip() and line[0].isdigit():
                            # Remove numbering
                            suggestion = line.split(".", 1)[1].strip() if "." in line else line.strip()
                            suggestions.append(suggestion)
                        if "📊 GENERAL RECOMMENDATIONS:" in line:
                            break
                    
                    if suggestions:
                        st.markdown("#### 💡 Cost Optimization Suggestions")
                        for suggestion in suggestions:
                            st.markdown(f"- {suggestion}")
                    
                    # Extract and display general recommendations
                    recommendations = []
                    in_recommendations = False
                    for line in lines:
                        if "📊 GENERAL RECOMMENDATIONS:" in line:
                            in_recommendations = True
                            continue
                        if in_recommendations and line.strip().startswith("•"):
                            recommendations.append(line.strip()[1:].strip())
                    
                    if recommendations:
                        st.markdown("#### 📋 General Recommendations")
                        for rec in recommendations:
                            st.markdown(f"- {rec}")
                    
                    # Show warning if cost is high
                    try:
                        cost_value = float(total_cost)
                        if cost_value > 100:
                            st.warning(f"⚠️ Monthly cost exceeds $100. Review your architecture for optimization opportunities.")
                    except:
                        pass
                        
            else:
                st.markdown("⏳ **Status:** Pending (runs after deployment)")
        
        # Add separator between retries
        if idx < len(st.session_state.workflow_outputs) - 1:
            st.divider()
    
    # Save to disk section
    if st.session_state.validation_passed:
        st.divider()
        st.markdown("### Save to Disk:")
        
        project_name = st.text_input(
            "Project directory name:",
            value=f"tf-project-{uuid.uuid4().hex[:6]}",
            key="project_name"
        )
        
        if st.button("💾 Save to Disk", use_container_width=True):
            success, message = save_files_to_disk(project_name, st.session_state.generated_files)
            if success:
                st.success(message)
            else:
                st.error(message)
    
    # Destroy resources section - only show if deployment was successful
    if st.session_state.deployment_passed:
        st.divider()
        st.markdown("### Destroy Resources:")
        st.warning("⚠️ This will permanently delete all deployed AWS resources. This action cannot be undone.")
        
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            if st.button("🗑️ Destroy All Resources", type="secondary", use_container_width=True):
                with st.spinner("Destroying resources..."):
                    try:
                        destroy_result = terraform_destroy_tool.invoke({})
                        
                        if "Terraform destroy successful" in destroy_result:
                            st.success("✅ All resources have been successfully destroyed!")
                            st.code(destroy_result, language="")
                            
                            # Update session state to reflect destruction
                            st.session_state.deployment_passed = False
                        else:
                            st.error("❌ Failed to destroy resources")
                            st.code(destroy_result, language="")
                    except Exception as e:
                        st.error(f"❌ Error during destroy: {str(e)}")

