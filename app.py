"""
AWS Infrastructure Generator - Streamlit UI
Main application entry point for AI-powered Terraform code generation and deployment.
"""
import sys
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st

from tools import save_files_to_disk, terraform_destroy_tool
from workflow import build_workflow

# --- Configuration ---
MAX_RETRIES = 3


# --- Custom stdout capture for real-time UI updates ---
class StreamlitStatusCapture:
    """Captures print statements and displays them in both terminal and Streamlit UI."""
    
    # Emojis that indicate a status message
    STATUS_EMOJIS = ('🧠', '💻', '🔍', '🛡️', '🚀', '💰', '✅', '✓', '❌', '⚠️', '🔧')
    
    def __init__(self, status_placeholder):
        self.status_placeholder = status_placeholder
        self.terminal_stdout = sys.stdout
        
    def write(self, text):
        # Write to terminal
        self.terminal_stdout.write(text)
        self.terminal_stdout.flush()
        
        # Update UI if it's a status message (contains emojis or key markers)
        if text.strip() and any(emoji in text for emoji in self.STATUS_EMOJIS):
            clean_text = text.strip()
            
            # Update the UI placeholder with appropriate styling
            if '✅' in clean_text or '✓' in clean_text:
                self.status_placeholder.success(clean_text)
            elif '❌' in clean_text:
                self.status_placeholder.error(clean_text)
            elif '⚠️' in clean_text:
                self.status_placeholder.warning(clean_text)
            else:
                self.status_placeholder.info(clean_text)
    
    def flush(self):
        self.terminal_stdout.flush()


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
        "security_warning": False,
        "deployment_passed": False,
        "validation_report": "",
        "security_report": "",
        "deployment_report": "",
        "cost_report": "",
        "cost_passed": False,
        "process_complete": False,
        "elapsed_time": 0,
        "plan": "",
        "workflow_outputs": [],
        "resources_destroyed": False,
        "workflow_running": False,
        "pending_request": None,
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    if "config" not in st.session_state:
        st.session_state.config = {
            "configurable": {"thread_id": st.session_state.thread_id}
        }

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
    
    if st.button("🔄 Reset Session", width="stretch"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()


# --- Helper Functions for Processing ---
def _create_agent_run_structure(retry: int = 0) -> Dict[str, Any]:
    """Create empty agent run structure for tracking workflow progress."""
    return {
        "retry": retry,
        "agents": {
            "planner": {"status": "pending", "output": ""},
            "code_generator": {"status": "pending", "output": ""},
            "code_validator": {"status": "pending", "output": ""},
            "error_analyzer": {"status": "pending", "output": ""},
            "targeted_fixer": {"status": "pending", "output": ""},
            "security_scanner": {"status": "pending", "output": ""},
            "cost_estimator": {"status": "pending", "output": ""},
            "deployer": {"status": "pending", "output": ""}
        }
    }


def _update_agent_status(current_run: Dict[str, Any], event: Dict[str, Any]) -> None:
    """Update agent status based on workflow event."""
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

    # Track error analyzer output
    if "error_analysis" in event or "needs_full_retry" in event:
        current_run["agents"]["error_analyzer"]["status"] = "complete"
        analysis = event.get("error_analysis", {})
        needs_retry = event.get("needs_full_retry", False)
        
        if isinstance(analysis, dict):
            output_parts = [
                f"Error Category: {analysis.get('category', 'unknown')}",
                f"Fix Strategy: {analysis.get('strategy', 'unknown')}",
                f"Description: {analysis.get('fix_description', 'N/A')}",
                f"Needs Full Retry: {'Yes' if needs_retry else 'No (Targeted Fix)'}"
            ]
            current_run["agents"]["error_analyzer"]["output"] = "\n".join(output_parts)
        else:
            current_run["agents"]["error_analyzer"]["output"] = str(analysis)

    # Track targeted fixer output
    if "targeted_fix_applied" in event or "targeted_fix_strategy" in event:
        current_run["agents"]["targeted_fixer"]["status"] = "complete"
        strategy = event.get("targeted_fix_strategy", "unknown")
        description = event.get("targeted_fix_description", "N/A")
        output_parts = [
            f"Fix Strategy: {strategy}",
            f"Description: {description}",
            f"Status: Fix applied to main.tf and ready for re-validation"
        ]
        current_run["agents"]["targeted_fixer"]["output"] = "\n".join(output_parts)

    # Track security scanner output
    if event.get("security_report"):
        current_run["agents"]["security_scanner"]["status"] = "complete"
        current_run["agents"]["security_scanner"]["output"] = event.get("security_report", "")

    # Track cost estimator output
    if event.get("cost_report"):
        current_run["agents"]["cost_estimator"]["status"] = "complete"
        current_run["agents"]["cost_estimator"]["output"] = event.get("cost_report", "")

    # Track deployer output
    if event.get("deployment_report"):
        current_run["agents"]["deployer"]["status"] = "complete"
        current_run["agents"]["deployer"]["output"] = event.get("deployment_report", "")


def run_workflow_with_progress(
    inputs: Dict[str, Any]
) -> Tuple[Optional[Dict[str, Any]], float, List[Dict[str, Any]]]:
    """
    Execute the workflow and capture agent outputs with real-time status updates.
    Uses stdout capture to sync terminal and UI messages.
    
    Returns:
        Tuple of (final_state, elapsed_time, all_workflow_runs)
    """
    start_time = time.time()
    all_runs = []
    current_run = _create_agent_run_structure()
    
    # Create placeholder for real-time status updates
    status_placeholder = st.empty()
    
    # Track previous event for agent status tracking
    prev_event = {}

    # Redirect stdout to capture print statements
    original_stdout = sys.stdout
    sys.stdout = StreamlitStatusCapture(status_placeholder)

    try:
        events = app.stream(inputs, st.session_state.config, stream_mode="values")
        final_state = None
        last_retry_count = 0

        for event in events:
            final_state = event
            current_retry = event.get("retry_count", 0)

            # Handle retry transitions
            if current_retry > last_retry_count:
                all_runs.append(current_run)
                last_retry_count = current_retry
                current_run = _create_agent_run_structure(current_retry)
                prev_event = {}

            _update_agent_status(current_run, event)
            prev_event = event.copy()

        # Add the final run
        all_runs.append(current_run)
        elapsed_time = time.time() - start_time
        
        # Restore original stdout
        sys.stdout = original_stdout
        
        # Show final completion status
        status_placeholder.success(f"✅ Process complete! Time taken: {elapsed_time:.1f}s")
        time.sleep(2)
        status_placeholder.empty()

        print(f"\n✅ Process complete! Time taken: {elapsed_time:.1f}s")
        return final_state, elapsed_time, all_runs

    except Exception as e:
        # Restore original stdout
        sys.stdout = original_stdout
        
        print(f"\n❌ Error occurred: {type(e).__name__}: {str(e)}")
        elapsed_time = time.time() - start_time
        all_runs.append(current_run)
        status_placeholder.error(f"❌ Error occurred: {str(e)}")
        time.sleep(2)
        status_placeholder.empty()
        return None, elapsed_time, all_runs




def update_session_state_from_workflow(
    final_state: Optional[Dict[str, Any]],
    elapsed_time: float,
    all_runs: List[Dict[str, Any]]
) -> None:
    """Update session state with workflow results."""
    if not final_state:
        return

    # Update all state fields from final workflow state
    state_mappings = {
        "generated_files": {},
        "validation_passed": False,
        "security_passed": False,
        "security_warning": False,
        "deployment_passed": False,
        "validation_report": "",
        "security_report": "",
        "deployment_report": "",
        "cost_report": "",
        "cost_passed": False,
        "plan": "",
    }

    for key, default_value in state_mappings.items():
        st.session_state[key] = final_state.get(key, default_value)

    st.session_state.process_complete = True
    st.session_state.elapsed_time = elapsed_time
    st.session_state.workflow_outputs = all_runs



# --- Main Content ---
st.subheader("What would you like to build?")

user_input = st.text_area(
    "What would you like to build?",
    height=100,
    placeholder="Example: Create an S3 bucket for storing user uploads with versioning enabled",
    key="user_input",
    label_visibility="collapsed",
    disabled=st.session_state.workflow_running
)

generate_btn = st.button(
    "Generate Infrastructure", 
    type="primary", 
    width="stretch",
    disabled=st.session_state.workflow_running
)

# --- Process Generation ---
# Stage 1: Button clicked - set flag and rerun to show disabled state
if generate_btn and user_input and not st.session_state.workflow_running:
    st.session_state.workflow_running = True
    st.session_state.process_complete = False
    st.session_state.workflow_outputs = []  # Clear previous outputs
    st.session_state["pending_request"] = user_input  # Store the request
    st.rerun()

# Stage 2: Flag is set - execute workflow
if st.session_state.workflow_running and st.session_state.get("pending_request"):
    user_request = st.session_state["pending_request"]
    
    inputs = {
        "initial_request": user_request,
        "human_feedback": "",
        "retry_count": 0,
    }
    
    try:
        # Run workflow with real-time status updates
        final_state, elapsed_time, all_runs = run_workflow_with_progress(inputs)
        
        if final_state is not None:
            update_session_state_from_workflow(final_state, elapsed_time, all_runs)
        else:
            st.session_state.process_complete = False
    except Exception as e:
        st.error(f"❌ Unexpected error: {str(e)}")
        st.session_state.process_complete = False
    finally:
        # Always reset workflow_running flag and clear pending request
        st.session_state.workflow_running = False
        st.session_state["pending_request"] = None
        st.rerun()

# --- Display Results ---
def _check_agent_success(agent_name: str, output: str) -> bool:
    """Check if agent execution was successful based on output."""
    success_indicators = {
        "code_validator": "Validation successful",
        "security_scanner": ["No security issues detected", "security scan passed"],
        "deployer": ["Terraform apply successful", "Apply complete"]
    }
    
    indicators = success_indicators.get(agent_name)
    if not indicators:
        return False
    
    if isinstance(indicators, str):
        return indicators in output
    return any(indicator in output for indicator in indicators)


def _display_agent_output(
    agent_name: str,
    display_name: str,
    agent_data: Dict[str, str],
    expanded: bool = False
) -> None:
    """Display a single agent's output in an expander."""
    status_icon = "✅" if agent_data["status"] == "complete" else "⏳"
    status_text = "Complete" if agent_data["status"] == "complete" else "Pending"

    with st.expander(display_name, expanded=expanded):
        st.markdown(f"{status_icon} **Status:** {status_text}")

        if agent_data["status"] == "complete":
            output = agent_data["output"]

            # Special handling for different agent types
            if agent_name == "planner":
                st.markdown("**Output:**")
                st.text(output)

            elif agent_name == "code_generator":
                st.markdown("**Output:**")
                st.markdown(output)

            elif agent_name == "error_analyzer":
                st.markdown("**Analysis:**")
                st.info(output)

            elif agent_name == "targeted_fixer":
                st.markdown("**Fix Applied:**")
                st.success(output)

            elif agent_name in ["code_validator", "security_scanner", "deployer"]:
                st.markdown("**Terminal Output:**")
                
                # Check success status
                passed = _check_agent_success(agent_name, output)
                
                # Define messages
                success_messages = {
                    "code_validator": "Validation Passed",
                    "security_scanner": "Security Scan Passed",
                    "deployer": "Deployment Successful"
                }
                
                failed_messages = {
                    "code_validator": "Validation Failed",
                    "security_scanner": "Security Issues Found",
                    "deployer": "Deployment Failed"
                }
                
                if passed:
                    st.success(f"✅ {success_messages[agent_name]}")
                else:
                    if agent_name == "security_scanner":
                        st.warning(f"⚠️ {failed_messages[agent_name]}")
                    else:
                        st.error(f"❌ {failed_messages[agent_name]}")
                
                with st.expander("Show verbose terminal output", expanded=(agent_name == "deployer")):
                    st.code(output, language="")

            elif agent_name == "cost_estimator":
                _display_cost_estimator_output(output)


def _parse_cost_breakdown(lines: List[str]) -> List[Dict[str, str]]:
    """Parse cost breakdown table from cost report lines."""
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
    
    return breakdown_data


def _display_cost_estimator_output(cost_output: str) -> None:
    """Display cost estimator output with formatting."""
    st.markdown("**Deployed Resource Cost Analysis:**")

    if "Cost estimation unavailable" in cost_output:
        st.info(cost_output)
        return

    # Parse cost data
    lines = cost_output.split('\n')

    # Extract total cost
    total_cost = "N/A"
    for line in lines:
        if "ESTIMATED MONTHLY COST:" in line:
            total_cost = line.split("$")[1].strip() if "$" in line else "N/A"
            break

    # Display total with metric
    st.metric("💰 Estimated Monthly Cost", f"${total_cost}")

    # Parse and display cost breakdown table
    breakdown_data = _parse_cost_breakdown(lines)
    if breakdown_data:
        st.markdown("#### 📊 Cost Breakdown")
        import pandas as pd
        df = pd.DataFrame(breakdown_data)
        st.dataframe(df, width="stretch", hide_index=True)

    # Extract and display suggestions
    suggestions = _extract_numbered_list(lines, "💡 COST OPTIMIZATION SUGGESTIONS:", "📊 GENERAL RECOMMENDATIONS:")
    if suggestions:
        st.markdown("#### 💡 Cost Optimization Suggestions")
        for suggestion in suggestions:
            st.markdown(f"- {suggestion}")

    # Extract and display general recommendations
    recommendations = _extract_bullet_list(lines, "📊 GENERAL RECOMMENDATIONS:")
    if recommendations:
        st.markdown("#### 📋 General Recommendations")
        for rec in recommendations:
            st.markdown(f"- {rec}")

    # Show warning if cost is high
    try:
        cost_value = float(total_cost)
        if cost_value > 100:
            st.warning(
                f"⚠️ Monthly cost exceeds $100. "
                f"Review your architecture for optimization opportunities."
            )
    except ValueError:
        pass


def _extract_numbered_list(lines: List[str], start_marker: str, end_marker: str) -> List[str]:
    """Extract numbered list items between two markers."""
    items = []
    in_section = False
    for line in lines:
        if start_marker in line:
            in_section = True
            continue
        if end_marker in line:
            break
        if in_section and line.strip() and line[0].isdigit():
            # Remove numbering
            item = line.split(".", 1)[1].strip() if "." in line else line.strip()
            items.append(item)
    return items


def _extract_bullet_list(lines: List[str], start_marker: str) -> List[str]:
    """Extract bullet list items after a marker."""
    items = []
    in_section = False
    for line in lines:
        if start_marker in line:
            in_section = True
            continue
        if in_section and line.strip().startswith("•"):
            items.append(line.strip()[1:].strip())
    return items


if st.session_state.process_complete:
    st.divider()

    # Show prominent security warning if issues were detected
    if st.session_state.get("security_warning", False):
        st.warning("""
        ⚠️ **Security Warning: Potential Security Issues Detected**
        
        The security scan (tfsec) detected potential security issues in the generated infrastructure.
        The deployment proceeded anyway, but please review the Security Scanner report below.
        
        **Common issues for development/testing:**
        - Public IP addresses assigned to EC2 instances
        - Open SSH access (0.0.0.0/0)
        - Public access to resources
        
        **Recommendation:** Review the security report and harden the infrastructure for production use.
        """)
        st.divider()

    # Time taken in small corner
    st.markdown(
        f'<div style="text-align: right; font-size: 0.9rem; color: #666;">'
        f'Time taken: {st.session_state.elapsed_time:.1f} sec</div>',
        unsafe_allow_html=True
    )

    # Display workflow outputs (including retries)
    for idx, workflow_run in enumerate(st.session_state.workflow_outputs):
        retry_num = workflow_run["retry"]
        agents = workflow_run["agents"]

        # Show retry header if this is a retry
        if retry_num > 0:
            st.markdown(f"### 🔄 Retry {retry_num}")

        # Display each agent's output
        is_last_run = (idx == len(st.session_state.workflow_outputs) - 1)
        
        _display_agent_output("planner", "Planner Agent", agents["planner"], expanded=is_last_run)
        _display_agent_output("code_generator", "Code Generator Agent", agents["code_generator"])
        _display_agent_output("code_validator", "Code Validator Agent", agents["code_validator"])
        
        # Show error analyzer and targeted fixer if they ran
        if agents["error_analyzer"]["status"] == "complete":
            _display_agent_output("error_analyzer", "Error Analyzer Agent", agents["error_analyzer"], expanded=True)
        
        if agents["targeted_fixer"]["status"] == "complete":
            _display_agent_output("targeted_fixer", "Targeted Fix Agent", agents["targeted_fixer"], expanded=True)
        
        _display_agent_output("security_scanner", "Security Scanner Agent", agents["security_scanner"])
        _display_agent_output("deployer", "Deployer Agent", agents["deployer"])
        _display_agent_output("cost_estimator", "Cost Estimator Agent", agents["cost_estimator"], expanded=True)

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

        if st.button("💾 Save to Disk", width="stretch"):
            success, message = save_files_to_disk(
                project_name, st.session_state.generated_files
            )
            if success:
                st.success(message)
            else:
                st.error(message)

    # Destroy resources section - only show if deployment was successful
    if st.session_state.deployment_passed:
        st.divider()
        st.markdown("### Destroy Resources:")
        st.warning(
            "⚠️ This will permanently delete all deployed AWS resources. "
            "This action cannot be undone."
        )

        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            destroy_key = f"destroy_btn_{st.session_state.thread_id}"
            if st.button(
                "🗑️ Destroy All Resources",
                type="secondary",
                width="stretch",
                key=destroy_key
            ):
                with st.spinner("Destroying resources..."):
                    try:
                        destroy_result = terraform_destroy_tool.invoke({})

                        if "Terraform destroy successful" in destroy_result:
                            st.success("✅ All resources have been successfully destroyed!")
                            
                            with st.expander("Show destroy output", expanded=False):
                                st.code(destroy_result, language="")

                            # Update session state to reflect destruction
                            st.session_state.deployment_passed = False
                            st.session_state["resources_destroyed"] = True
                        else:
                            st.error("❌ Failed to destroy resources")
                            st.code(destroy_result, language="")
                    except Exception as e:
                        st.error(f"❌ Error during destroy: {str(e)}")
    
    # Show confirmation after resources are destroyed
    elif st.session_state.get("resources_destroyed", False):
        st.divider()
        st.markdown("### Destroy Resources:")
        st.info("✅ Resources have been destroyed. The infrastructure no longer exists in AWS.")


