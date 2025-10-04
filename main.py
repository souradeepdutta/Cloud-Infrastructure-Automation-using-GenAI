# main.py
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

# --- Instantiate Agents ---
planner_architect_agent = PlannerArchitectAgent()
code_generator_agent = CodeGeneratorAgent()
code_validator_agent = CodeValidatorAgent()
security_scanner_agent = SecurityScannerAgent()
deployer_agent = DeployerAgent()

# --- Define Graph Logic and Routers ---

def generation_router(state: GraphState):
    """Determines if there are more files to generate or if it's time to validate."""
    if state.get("file_structure"):
        return "code_generator"
    else:
        return "code_validator"

def validation_router(state: GraphState):
    """Routes after validation. To security scanner if passed, else use final_router logic."""
    if state.get("validation_passed"):
        return "security_scanner"
    # Increment retry and route
    state["retry_count"] = state.get("retry_count", 0) + 1
    return final_router(state)

def security_router(state: GraphState):
    """Routes after security scan. To deployer if passed, else use final_router logic."""
    if state.get("security_passed"):
        return "deployer"
    # Increment retry and route
    state["retry_count"] = state.get("retry_count", 0) + 1
    return final_router(state)

def final_router(state: GraphState):
    """Routes after failure. Retries or ends based on retry count."""
    retry_count = state.get("retry_count", 0)
    
    if state.get("human_feedback"):
        return "planner_architect"

    if retry_count < MAX_RETRIES:
        print(f"\n⚠️ Attempt {retry_count} failed. Retrying with improvements...")
        return "planner_architect"

    print("\n❌ Maximum retries reached.")
    return "end"

# --- Build the Graph ---
workflow = StateGraph(GraphState)

workflow.add_node("planner_architect", planner_architect_agent.run)
workflow.add_node("code_generator", code_generator_agent.run)
workflow.add_node("code_validator", code_validator_agent.run)
workflow.add_node("security_scanner", security_scanner_agent.run)
workflow.add_node("deployer", deployer_agent.run)


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

# Compile the graph
memory = MemorySaver()
app = workflow.compile(checkpointer=memory)


# --- Main Interaction Loop ---
def main():
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    
    print("="*60)
    print("🤖 AWS Infrastructure Generator (LocalStack)")
    print("="*60)
    print("Describe the infrastructure you want to build.")
    print("Type 'quit' to exit.\n")

    initial_request = input("You: ")
    if initial_request.lower() in ["quit", "exit"]:
        print("Goodbye!")
        return
        
    inputs = {
        "initial_request": initial_request,
        "human_feedback": "",
        "retry_count": 0,
    }

    while True:
        # Start timing the process
        start_time = time.time()
        
        events = app.stream(inputs, config, stream_mode="values")
        final_state = None
        for event in events:
            final_state = event

        # End timing the process
        end_time = time.time()
        elapsed_time = end_time - start_time
        
        print("\n" + "="*60)
        print("✅ PROCESS COMPLETE")
        print("="*60)
        print(f"⏱️  Time: {elapsed_time:.1f}s ({elapsed_time/60:.1f}m)\n")
        
        if not final_state.get("validation_passed"):
            print("❌ Failed after multiple attempts.\n")
            print("📄 Error Report:")
            print("-" * 60)
            print(final_state.get("validation_report", "No report available."))
            print("-" * 60)
            break

        print("� GENERATED CODE")
        print("="*60)
        for filename, code in final_state["generated_files"].items():
            print(f"\n📄 {filename}")
            print("-" * 60)
            print(code)
        print("="*60)
        
        print("\n--- �️ SECURITY REPORT ---")
        print(final_state.get("security_report", "No security scan was performed."))
        
        print("\n--- �🚀 DEPLOYMENT REPORT ---")
        print(final_state.get("deployment_report", "No deployment was attempted."))

        print("\n--- 🧑‍💻 HUMAN REVIEW ---")
        print("="*60)
        review = input("[S]ave | [R]evise | [Q]uit: ").lower()

        if review == 's':
            project_name = input("Enter a directory name for this project (e.g., 's3-bucket-project'): ")
            if not project_name: project_name = f"tf-project-{uuid.uuid4().hex[:6]}"
            
            try:
                os.makedirs(project_name, exist_ok=True)
                for filename, code in final_state["generated_files"].items():
                    with open(os.path.join(project_name, filename), "w") as f:
                        f.write(code)
                print(f"\n✨ Files saved to './{project_name}/'")
            except Exception as e:
                print(f"❌ Error saving files: {e}")
            
            print("\nStarting a new request. What would you like to build next?")
            thread_id = str(uuid.uuid4())
            config = {"configurable": {"thread_id": thread_id}}
            new_request = input("You: ")
            if new_request.lower() in ["quit", "exit"]:
                print("Goodbye!")
                break
            inputs = {"initial_request": new_request, "human_feedback": "", "retry_count": 0}

        elif review == 'r':
            feedback = input("Please provide your feedback for revision: ")
            inputs = {"human_feedback": feedback}

        elif review == 'q':
            print("Goodbye!")
            break
        
        else:
            print("Invalid option. The current session will end.")
            break

if __name__ == "__main__":
    main()