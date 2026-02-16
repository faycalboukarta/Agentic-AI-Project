from typing import TypedDict, Annotated, List, Union
from typing_extensions import TypedDict
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from langchain_ollama import OllamaLLM
from langchain_community.utilities import SQLDatabase
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from langgraph.graph import StateGraph, END
import json
import pandas as pd
import plotly.express as px
import plotly.io as pio

# --- Configuration ---
# Get the directory where this script is located
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Database path relative to script location
DB_PATH = f"sqlite:///{os.path.join(SCRIPT_DIR, 'ecommerce.db')}"
# Using Ollama with qwen2.5-coder - Optimized for code generation!
OLLAMA_MODEL = "qwen2.5-coder:7b"  # Better for SQL and visualization code

# Initialize Database
db = SQLDatabase.from_uri(DB_PATH)

# Initialize LLM with Ollama (local)
llm = OllamaLLM(
    model=OLLAMA_MODEL,
    temperature=0.1,
    num_predict=1024,  # Increased for complete responses
)

# --- State Definition ---
class AgentState(TypedDict):
    question: str
    sql_query: str
    query_result: str
    error: str
    iteration: int
    needs_graph: bool
    graph_type: str
    graph_json: str
    final_answer: str
    is_in_scope: bool

# --- Nodes ---

def guardrail_agent(state: AgentState):
    """Checks if the question is in scope or a greeting."""
    print("--- Entered guardrail_agent ---")
    question = state["question"]
    
    system = """You are a helpful assistant for an E-commerce database.
    Determine if the user's question is:
    1. A greeting (e.g., "hi", "hello") -> Return "GREETING"
    2. A valid question about e-commerce data (orders, products, customers, etc.) -> Return "IN_SCOPE"
    3. Out of scope (e.g., "who is the president", "weather") -> Return "OUT_OF_SCOPE"
    
    Only return one of these three strings.
    """
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", system),
        ("user", "{question}")
    ])
    
    chain = prompt | llm | StrOutputParser()
    result = chain.invoke({"question": question}).strip()
    print(f"Guardrail Result: {result}")
    
    if result == "GREETING":
        return {"is_in_scope": False, "final_answer": "Hello! I can help you analyze your e-commerce data. Ask me about orders, products, or customers."}
    elif result == "OUT_OF_SCOPE":
        return {"is_in_scope": False, "final_answer": "I can only answer questions about the e-commerce database. Please ask about orders, sales, or products."}
    else:
        return {"is_in_scope": True}

def sql_agent(state: AgentState):
    """Generates SQL query from natural language."""
    print("--- Entered sql_agent ---")
    question = state["question"]
    schema = db.get_table_info()
    
    system = f"""You are an expert SQLite data analyst. 
    Given the following database schema, generate a valid SQLite query to answer the user's question.
    
    Schema:
    {schema}
    
    Rules:
    1. Return ONLY the SQL query. No markdown, no explanations.
    2. If the query might return many rows, limit it to 10.
    3. Use valid SQLite syntax.
    """
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", system),
        ("user", "{question}")
    ])
    
    chain = prompt | llm | StrOutputParser()
    query = chain.invoke({"question": question}).strip()
    
    # Clean up markdown if present
    query = query.replace("```sql", "").replace("```", "").strip()
    print(f"Generated Query: {query}")
    
    return {"sql_query": query, "iteration": state.get("iteration", 0) + 1}

def execute_sql(state: AgentState):
    """Executes the SQL query."""
    print("--- Entered execute_sql ---")
    query = state["sql_query"]
    try:
        result = db.run(query)
        print(f"Query Result: {str(result)[:100]}...")
        return {"query_result": str(result), "error": ""}
    except Exception as e:
        print(f"Query Error: {e}")
        return {"error": str(e), "query_result": ""}

def error_agent(state: AgentState):
    """Fixes SQL query based on error."""
    print("--- Entered error_agent ---")
    question = state["question"]
    query = state["sql_query"]
    error = state["error"]
    
    system = f"""You are fixing a broken SQL query.
    Question: {question}
    Original Query: {query}
    Error: {error}
    
    Database Schema:
    {db.get_table_info()}
    
    Return the corrected SQL query ONLY. No markdown.
    """
    
    prompt = ChatPromptTemplate.from_messages([("system", system), ("user", "Fix the query.")])
    chain = prompt | llm | StrOutputParser()
    new_query = chain.invoke({}).strip()
    new_query = new_query.replace("```sql", "").replace("```", "").strip()
    print(f"Corrected Query: {new_query}")
    
    return {"sql_query": new_query, "iteration": state["iteration"] + 1}

def analysis_agent(state: AgentState):
    """Explains the results in natural language."""
    print("--- Entered analysis_agent ---")
    question = state["question"]
    query = state["sql_query"]
    result = state["query_result"]
    
    system = f"""You are a data analyst. Explain the following database results in natural language to the user.
    User Question: {question}
    SQL Query: {query}
    Result: {result}
    
    Provide a clear, concise answer. If the result is a list, summarize it.
    """
    
    prompt = ChatPromptTemplate.from_messages([("system", system), ("user", "Provide the analysis.")])
    chain = prompt | llm | StrOutputParser()
    answer = chain.invoke({})
    print("Generated Answer")
    
    return {"final_answer": answer}

def decide_graph_need(state: AgentState) -> AgentState:
    """Decides if a graph visualization is needed."""
    print("--- Entered decide_graph_need ---")
    question = state["question"]
    result = state["query_result"]
    
    system = """You are a data visualization expert. Analyze if a visualization would be helpful.

IMPORTANT: Return ONLY valid JSON, nothing else. No explanations, no markdown.

Format:
{{"needs_graph": true, "graph_type": "bar"}}

Rules:
- Use "bar" for comparisons (top 10, rankings, categories)
- Use "line" for trends over time (yearly, monthly)
- Use "pie" for proportions (percentages, shares)
- Use "scatter" for correlations
- If single number or simple text: {{"needs_graph": false, "graph_type": "none"}}

Examples:
Question: "Top 10 customers by spending" → {{"needs_graph": true, "graph_type": "bar"}}
Question: "Yearly revenue" → {{"needs_graph": true, "graph_type": "line"}}
Question: "How many orders?" → {{"needs_graph": false, "graph_type": "none"}}
"""
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", system),
        ("user", f"Question: {question}\nResult: {result}\n\nReturn JSON:")
    ])
    
    chain = prompt | llm | StrOutputParser()
    response = chain.invoke({}).strip()
    
    print(f"Raw LLM Response: {response}")
    
    try:
        # Clean response - remove markdown if present
        if "```json" in response:
            response = response.split("```json")[1].split("```")[0].strip()
        elif "```" in response:
            response = response.split("```")[1].split("```")[0].strip()
        
        decision = json.loads(response)
        print(f"Graph Decision: {decision}")
        return {"needs_graph": decision.get("needs_graph", False), "graph_type": decision.get("graph_type", "none")}
    except Exception as e:
        print(f"Error parsing decision: {e}, Response was: {response}")
        # Default to showing graph for list results
        if isinstance(result, list) and len(result) > 1:
            return {"needs_graph": True, "graph_type": "bar"}
        return {"needs_graph": False, "graph_type": "none"}

def viz_agent(state: AgentState) -> AgentState:
    """
    Generates Python code using Plotly to visualize the data.
    
    Args:
        state: Current agent state with result and graph_type
        
    Returns:
        Updated state with visualization code
    """
    result = state["query_result"] # Keep original state key
    graph_type = state["graph_type"]
    
    # Build prompt without f-string to avoid template conflicts
    system = """You are a data visualization expert. Generate clean, working Python code using Plotly Express.

DATA: """ + str(result) + """
GRAPH TYPE: """ + str(graph_type) + """

REQUIREMENTS:
1. Import: pandas as pd, plotly.express as px
2. Parse the data into a DataFrame with proper column names
3. Create a """ + str(graph_type) + """ chart using px.""" + str(graph_type) + """()
4. Add a descriptive title
5. Return ONLY executable Python code, no explanations

Generate the code now."""
    
    prompt = ChatPromptTemplate.from_messages([("system", system), ("user", "Generate the visualization code.")])
    chain = prompt | llm | StrOutputParser()
    code = chain.invoke({}).strip()
    
    # Clean up code - remove markdown formatting if present
    if "```python" in code:
        code = code.split("```python")[1].split("```")[0].strip()
    elif "```" in code:
        code = code.split("```")[1].split("```")[0].strip()
    
    # Execute code to get 'fig' object
    local_vars = {}
    try:
        exec(code, {'pd': pd, 'px': px}, local_vars) # Pass pd and px to exec scope
        fig = local_vars.get('fig')
        if fig:
            return {"graph_json": pio.to_json(fig)}
    except Exception as e:
        print(f"Viz Error: {e}")
    
    return {"graph_json": ""}

# --- Graph Construction ---

def check_scope(state: AgentState):
    if state.get("is_in_scope"):
        return "sql_agent"
    return END

def should_retry(state: AgentState):
    if state["error"] and state["iteration"] < 3:
        return "error_agent"
    return "analysis_agent"

def should_generate_graph(state: AgentState):
    if state.get("needs_graph"):
        return "viz_agent"
    return END

workflow = StateGraph(AgentState)

workflow.add_node("guardrail_agent", guardrail_agent)
workflow.add_node("sql_agent", sql_agent)
workflow.add_node("execute_sql", execute_sql)
workflow.add_node("error_agent", error_agent)
workflow.add_node("analysis_agent", analysis_agent)
workflow.add_node("decide_graph_need", decide_graph_need)
workflow.add_node("viz_agent", viz_agent)

workflow.set_entry_point("guardrail_agent")

workflow.add_conditional_edges(
    "guardrail_agent",
    check_scope,
    {
        "sql_agent": "sql_agent",
        END: END
    }
)

workflow.add_edge("sql_agent", "execute_sql")

workflow.add_conditional_edges(
    "execute_sql",
    should_retry,
    {
        "error_agent": "error_agent",
        "analysis_agent": "analysis_agent"
    }
)

workflow.add_edge("error_agent", "execute_sql")
workflow.add_edge("analysis_agent", "decide_graph_need")

workflow.add_conditional_edges(
    "decide_graph_need",
    should_generate_graph,
    {
        "viz_agent": "viz_agent",
        END: END
    }
)

workflow.add_edge("viz_agent", END)

app_graph = workflow.compile()
