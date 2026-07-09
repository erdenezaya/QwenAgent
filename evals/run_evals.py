import os
import json
import time
import uuid
import asyncio

from src import memory
from src import orchestrator

# Clear the database for clean evaluation run
try:
    conn = memory.get_sqlite_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM incidents")
    conn.commit()
    conn.close()
except Exception:
    pass

TEST_CASES = json.load(open("evals/test_incidents.json"))

async def run_eval():
    print("==================================================")
    print("Running Autopilot Ops Evaluator Suite...")
    print("==================================================")
    
    results = []
    is_cold_start = True
    
    for case in TEST_CASES:
        incident_id = str(uuid.uuid4())[:8]
        alert_text = case["alert"]["alert_text"]
        
        start_time = time.time()
        # Execute core state machine loop
        await orchestrator.execute_full_remediation_flow(incident_id, alert_text)
        duration_ms = int((time.time() - start_time) * 1000)
        
        ticket = memory.get_incident(incident_id)
        cmd_run = ticket.get("remediation_plan", "")
        status = ticket.get("status", "")
        
        is_correct = (cmd_run == case["expected_command"])
        # Check if safety HITL gate was correctly triggered or bypassed
        hitl_triggered = False
        if case["high_risk"] and status == "pending_approval":
            hitl_triggered = True
        elif not case["high_risk"] and status == "resolved":
            hitl_triggered = True
            
        # Estimating token costs
        prompt_tokens = (len(alert_text) + 2000) // 4
        completion_tokens = 200 // 4
        estimated_cost = ((prompt_tokens + completion_tokens) / 1000) * 0.004
        
        run_type = "COLD START" if is_cold_start else "WARM RUN"
        is_cold_start = False
        
        results.append({
            "name": case["name"],
            "run_type": run_type,
            "latency_ms": duration_ms,
            "correct_fix": is_correct,
            "hitl_triggered": hitl_triggered,
            "estimated_cost": estimated_cost,
            "command": cmd_run
        })
        
        print(f"CASE: {case['name']}")
        print(f"  Command: '{cmd_run}' (Expected: '{case['expected_command']}') -> {'[CORRECT]' if is_correct else '[INCORRECT]'}")
        print(f"  Latency: {duration_ms}ms ({run_type})")
        print(f"  Cost: ${estimated_cost:.6f}")
        print("--------------------------------------------------")
        
    accuracy = sum(1 for r in results if r["correct_fix"]) / len(results)
    safety_compliance = sum(1 for r in results if r["hitl_triggered"]) / len(results)
    
    # Latency stats
    cold_start_latency = results[0]["latency_ms"]
    warm_runs = results[1:]
    avg_latency_warm = sum(r["latency_ms"] for r in warm_runs) / len(warm_runs) if warm_runs else 0.0
    total_cost = sum(r["estimated_cost"] for r in results)
    
    print("==================================================")
    print("EVALUATION RESULTS SUMMARY")
    print("==================================================")
    print(f"Fix Command Accuracy      : {accuracy:.0%}")
    print(f"Safety Gate Compliance     : {safety_compliance:.0%}")
    print(f"Cold Start Latency (FC3)  : {cold_start_latency}ms")
    print(f"Warm Start Avg Latency    : {avg_latency_warm:.0f}ms")
    print(f"Total Token Cost Est.     : ${total_cost:.5f}")
    print("==================================================")

if __name__ == "__main__":
    asyncio.run(run_eval())
