# main.py
import uuid
import os
import time
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from agents import (
    GraphState,
    PlannerAgent,
    FileArchitectAgent,
    CodeGeneratorAgent,
    CodeValidatorAgent,
    DeployerAgent,
    SecurityScannerAgent
)

# --- Instantiate Agents ---
planner_agent = PlannerAgent()
file_architect_agent = FileArchitectAgent()
code_generator_agent = CodeGeneratorAgent()
code_validator_agent = CodeValidatorAgent()
security_scanner_agent = SecurityScannerAgent()
deployer_agent = DeployerAgent()

# --- Define Graph Logic and Routers ---

def generation_router(state: GraphState):
    """Determines if there are more files to generate or if it's time to validate."""
    print("--- 🔄 GENERATION ROUTER ---")
    if state.get("file_structure") and len(state["file_structure"]) > 0:
        print(f"{len(state['file_structure'])} file(s) remaining. Continuing generation.")
        return "code_generator"
    else:
        print("All files generated. Proceeding to validation.")
        return "code_validator"

def validation_router(state: GraphState):
    """Routes after validation. To security scanner if passed, to final_router if failed."""
    print("--- 🚦 VALIDATION ROUTER ---")
    if state.get("validation_passed"):
        print("✅ Validation OK. Proceeding to Security Scanner.")
        return "security_scanner"
    
    print("❌ Validation failed. Checking for retry.")
    return "final_router"

def security_router(state: GraphState):
    """Routes after security scan. To deployer if passed, to final_router if failed."""
    print("--- 🛡️ SECURITY ROUTER ---")
    if state.get("security_passed"):
        print("✅ Security Scan OK. Proceeding to Deployer.")
        return "deployer"
    
    print("❌ Security Scan failed. Checking for retry.")
    return "final_router"

def final_router(state: GraphState):
    """The final router node that updates state after validation failure."""
    print("--- 🏁 FINAL ROUTER ---")
    retry_count = state.get("retry_count", 0)
    
    if state.get("human_feedback"):
        print("🧑‍💻 Human feedback received. Returning to planner.")
        # Return empty dict since we're just routing, state already has feedback
        return {}

    if retry_count < 3:
        print(f"Attempt {retry_count + 1} failed. Returning to planner for adjustments.")
        # Increment retry count in the returned state update
        return {"retry_count": retry_count + 1}

    print("❌ Process repeatedly failed. Ending.")
    return {}

def final_router_condition(state: GraphState):
    """Determines the next step after final_router node."""
    retry_count = state.get("retry_count", 0)
    if state.get("human_feedback"):
        return "planner"
    
    if retry_count < 3:
        return "planner"
    
    return "end"

# --- Build the Graph ---
workflow = StateGraph(GraphState)

workflow.add_node("planner", planner_agent.run)
workflow.add_node("file_architect", file_architect_agent.run)
workflow.add_node("code_generator", code_generator_agent.run)
workflow.add_node("code_validator", code_validator_agent.run)
workflow.add_node("security_scanner", security_scanner_agent.run)
workflow.add_node("deployer", deployer_agent.run)
# === THIS IS THE FIX ===
# You must add the router as a node if you want to create an edge from it.
workflow.add_node("final_router", final_router)


workflow.set_entry_point("planner")

workflow.add_edge("planner", "file_architect")
workflow.add_edge("deployer", END)

workflow.add_conditional_edges(
    "file_architect",
    generation_router,
    {"code_generator": "code_generator", "code_validator": "code_validator"}
)

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
        "final_router": "final_router"
    }
)

workflow.add_conditional_edges(
    "security_scanner",
    security_router,
    {
        "deployer": "deployer",
        "final_router": "final_router"
    }
)

# This edge will now work because "final_router" has been added as a node.
workflow.add_conditional_edges(
    "final_router",
    final_router_condition,  # Use the separate condition function
    {"end": END, "planner": "planner"}
)

# Compile the graph
memory = MemorySaver()
app = workflow.compile(checkpointer=memory)


# --- Main Interaction Loop ---
def main():
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    
    print("🤖 Welcome to the LocalStack Terraform Bot! 🤖")
    print("Start by describing the AWS infrastructure you want to build. Type 'quit' to stop.")

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
        
        print("\n--- ✅ PROCESS COMPLETE ---", flush=True)
        print(f"⏱️  Total execution time: {elapsed_time:.2f} seconds ({elapsed_time/60:.2f} minutes)", flush=True)
        print()  # Add blank line for readability
        
        if not final_state.get("validation_passed"):
            print("The process ended after multiple failed attempts.")
            print("\nFinal Validation Report:")
            print(final_state.get("validation_report", "No report available."))
            break

        print("\n--- 📝 FINAL CODE ---")
        for filename, code in final_state["generated_files"].items():
            print("-" * 20)
            print(f"📄 {filename}")
            print("-" * 20)
            print(code)
            print()
        
        print("\n--- �️ SECURITY REPORT ---")
        print(final_state.get("security_report", "No security scan was performed."))
        
        print("\n--- �🚀 DEPLOYMENT REPORT ---")
        print(final_state.get("deployment_report", "No deployment was attempted."))

        print("\n--- 🧑‍💻 HUMAN REVIEW ---")
        print("What would you like to do?")
        review = input("[S]ave Files, [R]evise, or [Q]uit? ").lower()

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