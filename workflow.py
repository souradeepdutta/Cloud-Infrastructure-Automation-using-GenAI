"""
Shared workflow logic for the AWS Infrastructure Generator.
Contains the LangGraph workflow definition and routing logic.
"""

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

# --- Configuration ---
MAX_RETRIES = 3

# --- Singleton Agent Instances ---
_agents = None


def get_agents():
    """Get or create singleton agent instances."""
    global _agents
    if _agents is None:
        _agents = {
            "planner": PlannerArchitectAgent(),
            "generator": CodeGeneratorAgent(),
            "validator": CodeValidatorAgent(),
            "security": SecurityScannerAgent(),
            "deployer": DeployerAgent()
        }
    return _agents


# --- Router Functions ---

def code_generation_router(state: GraphState):
    """Route code generator: loop until all files generated, then validate."""
    if state.get("file_structure"):
        return "code_generator"
    return "code_validator"


def validation_router(state: GraphState):
    """Route after validation: to security scanner or retry/end."""
    if state.get("validation_passed"):
        return "security_scanner"
    return _retry_or_end_router(state)


def security_router(state: GraphState):
    """Route after security scan: to deployer or retry/end."""
    if state.get("security_passed"):
        return "deployer"
    return _retry_or_end_router(state)


def deployment_router(state: GraphState):
    """Route after deployment: check if deployment succeeded or needs retry."""
    if state.get("deployment_passed"):
        return "end"
    return _retry_or_end_router(state)


def _retry_or_end_router(state: GraphState):
    """Determine whether to retry or end based on retry count and feedback."""
    retry_count = state.get("retry_count", 0)
    if state.get("human_feedback") or retry_count < MAX_RETRIES:
        return "planner_architect"
    return "end"


# --- Workflow Builder ---

def build_workflow():
    """Build and compile the LangGraph workflow with all agent nodes and routing logic."""
    agents = get_agents()
    
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
    
    workflow.add_conditional_edges(
        "deployer",
        deployment_router,
        {
            "end": END,
            "planner_architect": "planner_architect"
        }
    )

    memory = MemorySaver()
    return workflow.compile(checkpointer=memory)
