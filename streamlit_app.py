# streamlit_app.py
import logging
import os
import time
import uuid
from typing import Any, Dict, Optional, Tuple

import streamlit as st
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from agents import (
    CodeGeneratorAgent,
    CodeValidatorAgent,
    DeployerAgent,
    GraphState,
    PlannerArchitectAgent,
    SecurityScannerAgent,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Configuration ---
MAX_RETRIES = 3
PROGRESS_STEP = 15  # Progress bar increment per step
MAX_PROGRESS = 90   # Maximum progress before completion

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
        font-family: 'Inter', sans-serif;
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
        font-weight: 400;
    }
    .success-box {
        padding: 1rem;
        border-radius: 0.5rem;
        background-color: #d4edda;
        border: 1px solid #c3e6cb;
        color: #155724;
    }
    .error-box {
        padding: 1rem;
        border-radius: 0.5rem;
        background-color: #f8d7da;
        border: 1px solid #f5c6cb;
        color: #721c24;
    }
    .info-box {
        padding: 1rem;
        border-radius: 0.5rem;
        background-color: #d1ecf1;
        border: 1px solid #bee5eb;
        color: #0c5460;
    }
    
    /* Button styling with reduced padding */
    .stButton>button {
        width: 100%;
        font-weight: 500;
    }
    
    /* Specifically reduce padding for buttons */
    button[kind="primary"],
    button[kind="secondary"] {
        padding-left: 0.5rem !important;
        padding-right: 0.5rem !important;
    }
    
    div[data-testid="column"] .stButton>button {
        padding-left: 0.5rem !important;
        padding-right: 0.5rem !important;
    }
    
    /* Increase tab heading text size and center */
    .stTabs [data-baseweb="tab-list"] button {
        justify-content: center;
    }
    
    .stTabs [data-baseweb="tab-list"] button [data-testid="stMarkdownContainer"] p {
        font-size: 1.1em;
        font-weight: 500;
        text-align: center;
        padding-right: 0.2rem;
    }
    
    /* Centered question text */
    .centered-question {
        text-align: center;
        font-size: 1.6rem;
        font-weight: 500;
        margin-bottom: 1rem;
        margin-top: 2rem;
    }
    
    /* Metric container styling */
    [data-testid="stMetric"] {
        background-color: transparent;
        text-align: center;
        display: flex;
        flex-direction: column;
        align-items: center;
    }
    
    /* Metric label styling - more specific selectors */
    [data-testid="stMetricLabel"] {
        display: flex;
        justify-content: center;
        width: 100%;
    }
    
    [data-testid="stMetricLabel"] > div {
        font-size: 1.2rem !important;
        font-weight: 500 !important;
        text-align: center !important;
        justify-content: center !important;
        display: flex !important;
        margin-bottom: 0.4rem;
    }
    
    [data-testid="stMetricLabel"] > div > p {
        font-size: 1.25rem !important;
        font-weight: 500 !important;
        text-align: center !important;
        margin: 0 auto !important;
        margin-bottom: 0.4rem;
    }
    
    [data-testid="stMetricLabel"] p {
        font-size: 1.25rem !important;
        font-weight: 500 !important;
        margin-bottom: 0.4rem;
    }
    
    /* Metric value styling */
    [data-testid="stMetricValue"] {
        font-weight: 400 !important;
        font-size: 1.25rem !important;
        text-align: center !important;
        justify-content: center !important;
        display: flex !important;
        width: 100%;
    }
    
    [data-testid="stMetricValue"] > div {
        font-size: 1.2rem !important;
        font-weight: 400 !important;
        text-align: center !important;
        margin: 0 auto !important;
    }
    
    /* Reduce h4 font weight */
    .element-container h4 {
        font-weight: 400 !important;
    }
            
    /* Reduce h3 font weight */
    .element-container h3 {
        font-weight: 500 !important;
        
    }
    
    /* Style text area with max width and rounded corners */
    .stTextArea textarea {
        max-width: 850px;
        margin: 0 auto;
        resize: none !important;
    }
    
    .stTextArea > div {
        max-width: 800px;
        margin: 0 auto;
    }
    
    /* Hide the "Press Ctrl+Enter to apply" instruction text */
    .stTextArea [data-testid="InputInstructions"] {
        display: none !important;
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
        "validation_report": "",
        "security_report": "",
        "deployment_report": "",
        "process_complete": False,
        "elapsed_time": 0,
        "plan": "",
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    
    # Set config after thread_id is initialized
    if "config" not in st.session_state:
        st.session_state.config = {"configurable": {"thread_id": st.session_state.thread_id}}

initialize_session_state()

# --- Test Mode Function ---
def load_test_data():
    """Load mock data for UI testing without running the full pipeline."""
    st.session_state.generated_files = {
        "main.tf": '''resource "aws_s3_bucket" "user_uploads" {
  bucket = "user-uploads-bucket"
  
  tags = {
    Name        = "User Uploads"
    Environment = "Production"
  }
}

resource "aws_s3_bucket_versioning" "user_uploads_versioning" {
  bucket = aws_s3_bucket.user_uploads.id
  
  versioning_configuration {
    status = "Enabled"
  }
}''',
        "provider.tf": '''terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"
  
  endpoints {
    s3 = "http://localhost:4566"
  }
  
  access_key = "test"
  secret_key = "test"
  skip_credentials_validation = true
  skip_requesting_account_id = true
}'''
    }
    st.session_state.validation_passed = True
    st.session_state.security_passed = True
    st.session_state.validation_report = "✅ All syntax checks passed successfully!"
    st.session_state.security_report = "✅ No security issues found. All checks passed!"
    st.session_state.deployment_report = """Apply complete! Resources: 2 added, 0 changed, 0 destroyed.

Outputs:

bucket_name = "user-uploads-bucket"
bucket_arn = "arn:aws:s3:::user-uploads-bucket"
"""
    st.session_state.process_complete = True
    st.session_state.elapsed_time = 36.7
    st.session_state.plan = """Architecture Plan:
1. S3 Bucket for user uploads
2. Enable versioning on the bucket
3. Configure LocalStack provider
4. Add appropriate tags"""


# --- Instantiate Agents ---
@st.cache_resource
def get_agents():
    return {
        "planner": PlannerArchitectAgent(),
        "generator": CodeGeneratorAgent(),
        "validator": CodeValidatorAgent(),
        "security": SecurityScannerAgent(),
        "deployer": DeployerAgent()
    }

agents = get_agents()

# --- Build the Graph ---
@st.cache_resource
def build_workflow():
    """Build the LangGraph workflow with all agent nodes and routing logic."""
    
    def code_generation_router(state: GraphState):
        """Route code generator: loop until all files generated, then validate."""
        if state.get("file_structure"):
            return "code_generator"
        return "code_validator"
    
    def validation_router(state: GraphState):
        """Route after validation: to security scanner or retry/end."""
        if state.get("validation_passed"):
            return "security_scanner"
        # Don't mutate state here - routers should be pure functions
        return _retry_or_end_router(state)

    def security_router(state: GraphState):
        """Route after security scan: to deployer or retry/end."""
        if state.get("security_passed"):
            return "deployer"
        # Don't mutate state here - routers should be pure functions
        return _retry_or_end_router(state)

    def _retry_or_end_router(state: GraphState):
        """Determine whether to retry or end based on retry count and feedback."""
        retry_count = state.get("retry_count", 0)
        if state.get("human_feedback") or retry_count < MAX_RETRIES:
            return "planner_architect"
        return "end"

    workflow = StateGraph(GraphState)
    
    # Add all agent nodes
    workflow.add_node("planner_architect", agents["planner"].run)
    workflow.add_node("code_generator", agents["generator"].run)
    workflow.add_node("code_validator", agents["validator"].run)
    workflow.add_node("security_scanner", agents["security"].run)
    workflow.add_node("deployer", agents["deployer"].run)

    # Set entry point and simple edges
    workflow.set_entry_point("planner_architect")
    workflow.add_edge("planner_architect", "code_generator")
    workflow.add_edge("deployer", END)

    # Add conditional routing edges
    workflow.add_conditional_edges(
        "code_generator",
        code_generation_router,
        {"code_generator": "code_generator", "code_validator": "code_validator"}
    )
    
    workflow.add_conditional_edges(
        "code_validator",
        validation_router,
        {
            "security_scanner": "security_scanner",
            "end": END,
            "planner_architect": "planner_architect"
        }
    )

    workflow.add_conditional_edges(
        "security_scanner",
        security_router,
        {
            "deployer": "deployer",
            "end": END,
            "planner_architect": "planner_architect"
        }
    )

    memory = MemorySaver()
    return workflow.compile(checkpointer=memory)

app = build_workflow()


# --- UI Layout ---
st.markdown('<div class="main-header">AWS Infrastructure Generator</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">LocalStack-powered Infrastructure as Code</div>', unsafe_allow_html=True)

# --- Sidebar ---
with st.sidebar:
    st.header("📋 About")
    st.info("""
    This tool generates Terraform code for AWS infrastructure and deploys it to LocalStack.
    
    **Features:**
    - 🧠 AI-powered architecture planning
    - 💻 Terraform code generation
    - 🔍 Syntax validation
    - 🛡️ Security scanning (tfsec)
    - 🚀 LocalStack deployment
    """)
    
    st.header("⚙️ Settings")
    st.metric("Max Retries", MAX_RETRIES)
    st.metric("Session ID", st.session_state.thread_id[:8] + "...")
    
    st.divider()
    
    # Test mode button
    if st.button("🧪 Load Test Data", use_container_width=True):
        load_test_data()
        st.success("✅ Test data loaded!")
        st.rerun()
    
    if st.button("🔄 Reset Session", use_container_width=True):
        # Clear all session state
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()


# --- Helper Functions for Processing ---
def update_progress_status(final_state: Optional[Dict[str, Any]], status_text: Any) -> None:
    """Update status text based on current workflow state."""
    if not final_state:
        return
        
    if final_state.get("plan"):
        status_text.text("💻 Generating code...")
    elif final_state.get("generated_files"):
        status_text.text("🔍 Validating code...")
    elif final_state.get("validation_passed"):
        status_text.text("🛡️ Running security scan...")
    elif final_state.get("security_passed"):
        status_text.text("🚀 Deploying to LocalStack...")


def run_workflow_with_progress(inputs: Dict[str, Any], is_revision: bool = False) -> Tuple[Optional[Dict[str, Any]], float]:
    """
    Execute the workflow and update progress bar.
    
    Args:
        inputs: Input dictionary for the workflow
        is_revision: Whether this is a revision request
        
    Returns:
        tuple: (final_state, elapsed_time) or (None, 0) on error
    """
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    initial_message = "🔄 Processing revision..." if is_revision else "🧠 Planning architecture..."
    status_text.text(initial_message)
    progress_bar.progress(10)
    
    start_time = time.time()
    
    try:
        events = app.stream(inputs, st.session_state.config, stream_mode="values")
        final_state = None
        
        step = 0
        for event in events:
            final_state = event
            step += 1
            progress = min(10 + (step * PROGRESS_STEP), MAX_PROGRESS)
            progress_bar.progress(progress)
            update_progress_status(final_state, status_text)
        
        elapsed_time = time.time() - start_time
        
        progress_bar.progress(100)
        completion_message = "✅ Revision complete!" if is_revision else "✅ Process complete!"
        status_text.text(completion_message)
        
        time.sleep(1)
        return final_state, elapsed_time
        
    except Exception as e:
        logger.exception("Workflow execution failed")
        status_text.text("❌ Error occurred!")
        st.error(f"An error occurred: {type(e).__name__}: {str(e)}")
        progress_bar.empty()
        return None, 0


def update_session_state_from_workflow(final_state: Optional[Dict[str, Any]], elapsed_time: float) -> None:
    """Update session state with workflow results."""
    if final_state:
        st.session_state.generated_files = final_state.get("generated_files", {})
        st.session_state.validation_passed = final_state.get("validation_passed", False)
        st.session_state.security_passed = final_state.get("security_passed", False)
        st.session_state.validation_report = final_state.get("validation_report", "")
        st.session_state.security_report = final_state.get("security_report", "")
        st.session_state.deployment_report = final_state.get("deployment_report", "")
        st.session_state.plan = final_state.get("plan", "")
        st.session_state.process_complete = True
        st.session_state.elapsed_time = elapsed_time


def save_files_to_disk(project_name: str, files: Dict[str, str]) -> bool:
    """
    Save generated files to a project directory.
    
    Args:
        project_name: Name of the project directory
        files: Dictionary of filename -> content
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        os.makedirs(project_name, exist_ok=True)
        for filename, code in files.items():
            filepath = os.path.join(project_name, filename)
            with open(filepath, "w") as f:
                f.write(code)
        return True
    except Exception as e:
        st.error(f"❌ Error saving files: {e}")
        return False


# --- Main Content ---
tab1, tab2, tab3 = st.tabs(["📝 Generate", "📄 Code", "📊 Reports"])

with tab1:
    st.markdown('<div class="centered-question">What would you like to build?</div>', unsafe_allow_html=True)
    
    user_input = st.text_area(
        "What would you like to build?",
        height=100,
        placeholder="Example: Create an S3 bucket for storing user uploads with versioning enabled",
        key="user_input",
        label_visibility="collapsed"
    )
    
    # Center the generate button
    col1, col2, col3 = st.columns([2, 1, 2])
    with col2:
        generate_btn = st.button("Generate Infrastructure", type="primary", use_container_width=True)
    
    # Show revise button after generation
    revise_btn = st.button("✏️ Revise", use_container_width=True) if st.session_state.process_complete else False
    
    # --- Process Generation ---
    if generate_btn and user_input:
        st.session_state.process_complete = False
        
        inputs = {
            "initial_request": user_input,
            "human_feedback": "",
            "retry_count": 0,
        }
        
        final_state, elapsed_time = run_workflow_with_progress(inputs)
        if final_state is not None:
            update_session_state_from_workflow(final_state, elapsed_time)
            st.rerun()
        else:
            st.session_state.process_complete = False
            st.warning("Workflow failed. Please try again or revise your request.")
    
    # --- Process Revision ---
    if revise_btn:
        feedback = st.text_input("Provide feedback for revision:", key="revision_feedback")
        if st.button("Submit Revision") and feedback:
            st.session_state.process_complete = False
            
            inputs = {"human_feedback": feedback}
            
            final_state, elapsed_time = run_workflow_with_progress(inputs, is_revision=True)
            if final_state is not None:
                update_session_state_from_workflow(final_state, elapsed_time)
                st.rerun()
            else:
                st.session_state.process_complete = False
                st.warning("Revision failed. Please try again with different feedback.")
    
    # --- Display Results ---
    if st.session_state.process_complete:
        st.divider()
        
        # Metrics row
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("⏱️ Time Taken", f"{st.session_state.elapsed_time:.1f}s")
        
        with col2:
            validation_status = "✅ Passed" if st.session_state.validation_passed else "❌ Failed"
            st.metric("🔍 Validation", validation_status)
        
        with col3:
            security_status = "✅ Passed" if st.session_state.security_passed else "❌ Failed"
            st.metric("🛡️ Security", security_status)
        
        # Display architecture plan
        if st.session_state.plan:
            st.subheader("📋 Architecture Plan")
            st.markdown(f"```\n{st.session_state.plan}\n```")
        
        # Save option
        if st.session_state.validation_passed:
            st.divider()
            st.subheader("💾 Save Generated Files")
            
            project_name = st.text_input(
                "Project directory name:",
                value=f"tf-project-{uuid.uuid4().hex[:6]}",
                key="project_name"
            )
            
            if st.button("💾 Save to Disk", use_container_width=True):
                if save_files_to_disk(project_name, st.session_state.generated_files):
                    st.success(f"✨ Files saved to './{project_name}/'")


with tab2:
    st.subheader("📄 Generated Terraform Code")
    st.markdown('<div style="margin-top: 0.5rem;"></div>', unsafe_allow_html=True)
    
    if st.session_state.generated_files:
        for filename, code in st.session_state.generated_files.items():
            with st.expander(f"📄 {filename}", expanded=True):
                st.code(code, language="hcl")
    else:
        st.info("No code generated yet. Go to the Generate tab to create infrastructure.")

with tab3:
    st.subheader("📊 Validation & Security Reports")
    st.markdown('<div style="margin-top: 0.5rem;"></div>', unsafe_allow_html=True)
    
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### 🔍 Validation Report")
        if st.session_state.validation_report:
            css_class = "success-box" if st.session_state.validation_passed else "error-box"
            st.markdown(f'<div class="{css_class}">{st.session_state.validation_report}</div>', unsafe_allow_html=True)
        else:
            st.info("No validation report available.")
    
    with col2:
        st.markdown("#### 🛡️ Security Report")
        if st.session_state.security_report:
            css_class = "success-box" if st.session_state.security_passed else "error-box"
            st.markdown(f'<div class="{css_class}">{st.session_state.security_report}</div>', unsafe_allow_html=True)
        else:
            st.info("No security report available.")
    
    st.divider()
    
    st.markdown("#### 🚀 Deployment Report")
    if st.session_state.deployment_report:
        st.markdown(f'<div class="info-box"><pre>{st.session_state.deployment_report}</pre></div>', unsafe_allow_html=True)
    else:
        st.info("No deployment report available.")


