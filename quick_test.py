"""
Quick test to verify the optimized agent works
"""
from text2sql_agent import app_graph

# Test with a simple query
test_state = {
    "question": "How many orders do we have?",
    "iteration": 0,
    "is_in_scope": True,
    "error": "",
    "sql_query": "",
    "query_result": "",
    "needs_graph": False,
    "graph_json": ""
}

print("Testing optimized agent...")
print("=" * 60)

try:
    result = app_graph.invoke(test_state)
    print("✅ SUCCESS!")
    print(f"\nSQL Query: {result.get('sql_query', 'None')}")
    print(f"\nFinal Answer: {result.get('final_answer', 'None')[:200]}...")
    print(f"\nNeeds Graph: {result.get('needs_graph', False)}")
except Exception as e:
    print(f"❌ ERROR: {e}")
    import traceback
    traceback.print_exc()
