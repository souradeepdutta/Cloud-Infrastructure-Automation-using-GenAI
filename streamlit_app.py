# streamlit_app.py
import streamlit as st
import uuid
import os
import time
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from agents import (
    GraphState,
    PlannerArchitectAgent,
    CodeGeneratorAgent,
    CodeValidatorAgent,
    DeployerAgent,
    SecurityScannerAgent
)

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
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())
    st.session_state.config = {"configurable": {"thread_id": st.session_state.thread_id}}

if "generated_files" not in st.session_state:
    st.session_state.generated_files = {}

if "validation_passed" not in st.session_state:
    st.session_state.validation_passed = False

if "security_passed" not in st.session_state:
    st.session_state.security_passed = False

if "validation_report" not in st.session_state:
    st.session_state.validation_report = ""

if "security_report" not in st.session_state:
    st.session_state.security_report = ""

if "deployment_report" not in st.session_state:
    st.session_state.deployment_report = ""

if "process_complete" not in st.session_state:
    st.session_state.process_complete = False

if "elapsed_time" not in st.session_state:
    st.session_state.elapsed_time = 0

if "plan" not in st.session_state:
    st.session_state.plan = ""

# --- Test Mode Function ---
def load_test_data():
    """Load mock data for UI testing without running the full pipeline"""
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
    def generation_router(state: GraphState):
        if state.get("file_structure"):
            return "code_generator"
        else:
            return "code_validator"

    def validation_router(state: GraphState):
        if state.get("validation_passed"):
            return "security_scanner"
        state["retry_count"] = state.get("retry_count", 0) + 1
        return final_router(state)

    def security_router(state: GraphState):
        if state.get("security_passed"):
            return "deployer"
        state["retry_count"] = state.get("retry_count", 0) + 1
        return final_router(state)

    def final_router(state: GraphState):
        retry_count = state.get("retry_count", 0)
        if state.get("human_feedback"):
            return "planner_architect"
        if retry_count < MAX_RETRIES:
            return "planner_architect"
        return "end"

    workflow = StateGraph(GraphState)
    
    workflow.add_node("planner_architect", agents["planner"].run)
    workflow.add_node("code_generator", agents["generator"].run)
    workflow.add_node("code_validator", agents["validator"].run)
    workflow.add_node("security_scanner", agents["security"].run)
    workflow.add_node("deployer", agents["deployer"].run)

    workflow.set_entry_point("planner_architect")
    workflow.add_edge("planner_architect", "code_generator")
    workflow.add_edge("deployer", END)

    workflow.add_conditional_edges(
        "code_generator",
        generation_router,
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
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

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
    
    # Center the generate button with minimal width
    col1, col2, col3 = st.columns([2, 1, 2])
    
    with col2:
        generate_btn = st.button("Generate Infrastructure", type="primary", use_container_width=True)
    
    # Revise button (shown after generation)
    if st.session_state.process_complete:
        revise_btn = st.button("✏️ Revise", use_container_width=True)
    else:
        revise_btn = False
    
    # --- Process Generation ---
    if generate_btn and user_input:
        st.session_state.process_complete = False
        
        inputs = {
            "initial_request": user_input,
            "human_feedback": "",
            "retry_count": 0,
        }
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        start_time = time.time()
        
        try:
            status_text.text("🧠 Planning architecture...")
            progress_bar.progress(10)
            
            events = app.stream(inputs, st.session_state.config, stream_mode="values")
            final_state = None
            
            step = 0
            for event in events:
                final_state = event
                step += 1
                progress = min(10 + (step * 15), 90)
                progress_bar.progress(progress)
                
                # Update status based on the current state
                if final_state.get("plan"):
                    status_text.text("💻 Generating code...")
                if final_state.get("generated_files"):
                    status_text.text("🔍 Validating code...")
                if final_state.get("validation_passed"):
                    status_text.text("🛡️ Running security scan...")
                if final_state.get("security_passed"):
                    status_text.text("🚀 Deploying to LocalStack...")
            
            end_time = time.time()
            st.session_state.elapsed_time = end_time - start_time
            
            progress_bar.progress(100)
            status_text.text("✅ Process complete!")
            
            # Update session state with results
            if final_state:
                st.session_state.generated_files = final_state.get("generated_files", {})
                st.session_state.validation_passed = final_state.get("validation_passed", False)
                st.session_state.security_passed = final_state.get("security_passed", False)
                st.session_state.validation_report = final_state.get("validation_report", "")
                st.session_state.security_report = final_state.get("security_report", "")
                st.session_state.deployment_report = final_state.get("deployment_report", "")
                st.session_state.plan = final_state.get("plan", "")
                st.session_state.process_complete = True
            
            time.sleep(1)
            st.rerun()
            
        except Exception as e:
            status_text.text("❌ Error occurred!")
            st.error(f"An error occurred: {str(e)}")
            progress_bar.empty()
    
    # --- Process Revision ---
    if revise_btn:
        feedback = st.text_input("Provide feedback for revision:", key="revision_feedback")
        if st.button("Submit Revision") and feedback:
            st.session_state.process_complete = False
            
            inputs = {
                "human_feedback": feedback,
            }
            
            progress_bar = st.progress(0)
            status_text = st.empty()
            start_time = time.time()
            
            try:
                status_text.text("🔄 Processing revision...")
                progress_bar.progress(10)
                
                events = app.stream(inputs, st.session_state.config, stream_mode="values")
                final_state = None
                
                step = 0
                for event in events:
                    final_state = event
                    step += 1
                    progress = min(10 + (step * 15), 90)
                    progress_bar.progress(progress)
                
                end_time = time.time()
                st.session_state.elapsed_time = end_time - start_time
                
                progress_bar.progress(100)
                status_text.text("✅ Revision complete!")
                
                # Update session state
                if final_state:
                    st.session_state.generated_files = final_state.get("generated_files", {})
                    st.session_state.validation_passed = final_state.get("validation_passed", False)
                    st.session_state.security_passed = final_state.get("security_passed", False)
                    st.session_state.validation_report = final_state.get("validation_report", "")
                    st.session_state.security_report = final_state.get("security_report", "")
                    st.session_state.deployment_report = final_state.get("deployment_report", "")
                    st.session_state.plan = final_state.get("plan", "")
                    st.session_state.process_complete = True
                
                time.sleep(1)
                st.rerun()
                
            except Exception as e:
                status_text.text("❌ Error occurred!")
                st.error(f"An error occurred: {str(e)}")
                progress_bar.empty()
    
    # --- Display Results ---
    if st.session_state.process_complete:
        st.divider()
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("⏱️ Time Taken", f"{st.session_state.elapsed_time:.1f}s")
        
        with col2:
            if st.session_state.validation_passed:
                st.metric("🔍 Validation", "✅ Passed")
            else:
                st.metric("🔍 Validation", "❌ Failed")
        
        with col3:
            if st.session_state.security_passed:
                st.metric("🛡️ Security", "✅ Passed")
            else:
                st.metric("🛡️ Security", "❌ Failed")
        
        # Plan display
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
                try:
                    os.makedirs(project_name, exist_ok=True)
                    for filename, code in st.session_state.generated_files.items():
                        with open(os.path.join(project_name, filename), "w") as f:
                            f.write(code)
                    st.success(f"✨ Files saved to './{project_name}/'")
                except Exception as e:
                    st.error(f"❌ Error saving files: {e}")

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
            if st.session_state.validation_passed:
                st.markdown(f'<div class="success-box">{st.session_state.validation_report}</div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="error-box">{st.session_state.validation_report}</div>', unsafe_allow_html=True)
        else:
            st.info("No validation report available.")
    
    with col2:
        st.markdown("#### 🛡️ Security Report")
        if st.session_state.security_report:
            if st.session_state.security_passed:
                st.markdown(f'<div class="success-box">{st.session_state.security_report}</div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="error-box">{st.session_state.security_report}</div>', unsafe_allow_html=True)
        else:
            st.info("No security report available.")
    
    st.divider()
    
    st.markdown("#### 🚀 Deployment Report")
    if st.session_state.deployment_report:
        st.markdown(f'<div class="info-box"><pre>{st.session_state.deployment_report}</pre></div>', unsafe_allow_html=True)
    else:
        st.info("No deployment report available.")

