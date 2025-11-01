"""
Workflow definition for AWS Infrastructure Generator.
Contains the LangGraph workflow definition and routing logic for agent orchestration.
"""
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from agents import (
    CodeGeneratorAgent,
    CodeValidatorAgent,
    CostEstimatorAgent,
    DeployerAgent,
    ErrorAnalyzerAgent,
    GraphState,
    PlannerArchitectAgent,
    SecurityScannerAgent,
    TargetedFixAgent,
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
            "cost": CostEstimatorAgent(),
            "deployer": DeployerAgent(),
            "error_analyzer": ErrorAnalyzerAgent(),
            "targeted_fixer": TargetedFixAgent()
        }
    return _agents


# --- Router Functions ---

def code_generation_router(state: GraphState) -> str:
    """Route code generator: loop until all files generated, then validate."""
    if state.get("file_structure"):
        return "code_generator"
    return "code_validator"


def validation_router(state: GraphState) -> str:
    """Route after validation: to security scanner, error analyzer, or end."""
    if state.get("validation_passed"):
        return "security_scanner"
    # Use error analyzer for smart recovery
    return "error_analyzer"


def error_analysis_router(state: GraphState) -> str:
    """Route after error analysis: to targeted fixer or full retry."""
    if state.get("needs_full_retry"):
        return _retry_or_end_router(state)
    # Fixable error - use targeted fix
    return "targeted_fixer"


def targeted_fix_router(state: GraphState) -> str:
    """Route after targeted fix: back to validator to verify fix."""
    return "code_validator"


def security_router(state: GraphState) -> str:
    """Route after security scan: to deployer, error analyzer, or end."""
    if state.get("security_passed"):
        return "deployer"
    # Use error analyzer for smart recovery
    return "error_analyzer"


def deployment_router(state: GraphState) -> str:
    """Route after deployment: to cost estimator, error analyzer, or end."""
    if state.get("deployment_passed", False):
        return "cost_estimator"
    # Use error analyzer for smart recovery
    return "error_analyzer"


def cost_router(state: GraphState) -> str:
    """Route after cost estimation: always end (cost is final step)."""
    return "end"


def _retry_or_end_router(state: GraphState) -> str:
    """Determine whether to retry or end based on retry count and feedback."""
    retry_count = state.get("retry_count", 0)
    if state.get("human_feedback") or retry_count < MAX_RETRIES:
        return "planner_architect"
    return "end"



# --- Workflow Builder ---

def build_workflow():
    """
    Build and compile the LangGraph workflow with all agent nodes and routing logic.

    Returns:
        Compiled LangGraph workflow with memory checkpointing
    """
    agents = get_agents()

    workflow = StateGraph(GraphState)

    # Add all agent nodes
    workflow.add_node("planner_architect", agents["planner"].run)
    workflow.add_node("code_generator", agents["generator"].run)
    workflow.add_node("code_validator", agents["validator"].run)
    workflow.add_node("security_scanner", agents["security"].run)
    workflow.add_node("cost_estimator", agents["cost"].run)
    workflow.add_node("deployer", agents["deployer"].run)
    workflow.add_node("error_analyzer", agents["error_analyzer"].run)
    workflow.add_node("targeted_fixer", agents["targeted_fixer"].run)

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
            "error_analyzer": "error_analyzer",
            "end": END,
            "planner_architect": "planner_architect"
        }
    )
    
    workflow.add_conditional_edges(
        "error_analyzer",
        error_analysis_router,
        {
            "targeted_fixer": "targeted_fixer",
            "end": END,
            "planner_architect": "planner_architect"
        }
    )
    
    workflow.add_conditional_edges(
        "targeted_fixer",
        targeted_fix_router,
        {"code_validator": "code_validator"}
    )

    workflow.add_conditional_edges(
        "security_scanner",
        security_router,
        {
            "deployer": "deployer",
            "error_analyzer": "error_analyzer",
            "end": END,
            "planner_architect": "planner_architect"
        }
    )

    workflow.add_conditional_edges(
        "deployer",
        deployment_router,
        {
            "cost_estimator": "cost_estimator",
            "error_analyzer": "error_analyzer",
            "end": END,
            "planner_architect": "planner_architect"
        }
    )

    workflow.add_conditional_edges(
        "cost_estimator",
        cost_router,
        {"end": END}
    )

    memory = MemorySaver()
    return workflow.compile(checkpointer=memory)

