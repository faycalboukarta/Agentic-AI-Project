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

# Import configuration
from config import (
    DB_PATH,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    LLM_TEMPERATURE,
    LLM_NUM_PREDICT,
    MAX_RETRIES,
    HAS_GPU
)

# Initialize Database
db = SQLDatabase.from_uri(f"sqlite:///{DB_PATH}")

# Initialize LLM with Ollama (local) - OPTIMIZED FOR SPEED
llm = OllamaLLM(
    model=OLLAMA_MODEL,
    base_url=OLLAMA_BASE_URL,
    temperature=LLM_TEMPERATURE,
    num_predict=LLM_NUM_PREDICT,
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
    
    CRITICAL Rules:
    1. Use EXACT column names from the schema above - do NOT invent column names
    2. For order_payments table, use 'payment_value' NOT 'price'
    3. For customer queries, include customer_city or customer_state for readable labels
    4. Return ONLY the SQL query. No markdown, no explanations.
    5. If the query might return many rows, limit it to 10.
    6. Use valid SQLite syntax.
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
        # Store raw result for visualization, but keep string version for analysis
        return {"query_result": result, "error": ""}
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
        print(f"Error parsing graph decision: {e}")
        return {"needs_graph": False, "graph_type": "none"}

# PARALLEL EXECUTION OPTIMIZATION
# This node runs analysis_agent and decide_graph_need in parallel for 15-25% speedup
async def parallel_analysis_and_graph_decision(state: AgentState) -> AgentState:
    """Runs analysis and graph decision in parallel to save time."""
    print("--- Entered parallel_analysis_and_graph_decision ---")
    
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    
    # Create executor for running sync functions in parallel
    executor = ThreadPoolExecutor(max_workers=2)
    loop = asyncio.get_event_loop()
    
    # Run both functions in parallel
    analysis_future = loop.run_in_executor(executor, analysis_agent, state)
    graph_future = loop.run_in_executor(executor, decide_graph_need, state)
    
    # Wait for both to complete
    analysis_result, graph_result = await asyncio.gather(analysis_future, graph_future)
    
    # Merge results
    merged = {**analysis_result, **graph_result}
    print(f"Parallel execution complete: analysis={bool(analysis_result)}, graph={bool(graph_result)}")
    
    return merged

# Wrapper for sync context
def parallel_analysis_and_graph_decision_sync(state: AgentState) -> AgentState:
    """Synchronous wrapper for parallel execution."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If loop is already running (e.g., in Chainlit), create a new one
            import nest_asyncio
            nest_asyncio.apply()
            return asyncio.run(parallel_analysis_and_graph_decision(state))
        else:
            return loop.run_until_complete(parallel_analysis_and_graph_decision(state))
    except RuntimeError:
        # Fallback to creating new event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(parallel_analysis_and_graph_decision(state))
        finally:
            loop.close()

def viz_agent(state: AgentState) -> AgentState:
    """
    Creates visualizations directly without LLM code generation.
    """
    print("--- Entered viz_agent ---")
    result = state["query_result"]
    graph_type = state["graph_type"]
    question = state.get("question", "")
    
    try:
        # Handle string result format from db.run()
        if isinstance(result, str):
            # Parse string result back to list of tuples
            import ast
            try:
                result = ast.literal_eval(result)
            except:
                print(f"Could not parse result string: {result[:100]}")
                return {"graph_json": ""}
        
        # Convert result to DataFrame
        if not result or len(result) == 0:
            return {"graph_json": ""}
        
        # Determine number of columns
        first_row = result[0]
        num_cols = len(first_row) if isinstance(first_row, (tuple, list)) else 1
        
        # Create column names
        if num_cols == 1:
            columns = ['value']
        elif num_cols == 2:
            columns = ['label', 'value']
        elif num_cols == 3:
            columns = ['id', 'label', 'value']
        else:
            columns = [f'col{i}' for i in range(num_cols)]
        
        # Create DataFrame
        df = pd.DataFrame(result, columns=columns)
        
        # Create readable labels if we have hash IDs
        if 'label' in df.columns:
            # Check if labels are long hashes (more than 20 characters)
            if df['label'].astype(str).str.len().mean() > 20:
                df['display_label'] = [f'Customer {i+1}' for i in range(len(df))]
                x_col = 'display_label'
            else:
                x_col = 'label'
        elif 'id' in df.columns:
            # If we have id column, create readable labels
            if df['id'].astype(str).str.len().mean() > 20:
                df['display_label'] = [f'Item {i+1}' for i in range(len(df))]
                x_col = 'display_label'
            else:
                x_col = 'id'
        else:
            # Create generic labels
            df['display_label'] = [f'Item {i+1}' for i in range(len(df))]
            x_col = 'display_label'
        
        # Determine y column (usually the last numeric column)
        y_col = 'value' if 'value' in df.columns else df.columns[-1]
        
        # Create appropriate chart based on graph_type
        if graph_type == "bar":
            fig = px.bar(df, x=x_col, y=y_col, title=f"Bar Chart: {question[:50]}...")
        elif graph_type == "line":
            fig = px.line(df, x=x_col, y=y_col, title=f"Line Chart: {question[:50]}...")
        elif graph_type == "pie":
            fig = px.pie(df, names=x_col, values=y_col, title=f"Pie Chart: {question[:50]}...")
        elif graph_type == "scatter":
            fig = px.scatter(df, x=x_col, y=y_col, title=f"Scatter Plot: {question[:50]}...")
        else:
            # Default to bar chart
            fig = px.bar(df, x=x_col, y=y_col, title=f"Chart: {question[:50]}...")
        
        print(f"Created {graph_type} chart successfully")
        return {"graph_json": pio.to_json(fig)}
        
    except Exception as e:
        print(f"Viz Error: {e}")
        import traceback
        traceback.print_exc()
        return {"graph_json": ""}

# --- Graph Construction ---

def check_scope(state: AgentState):
    if state.get("is_in_scope"):
        return "sql_agent"
    return END

def should_retry(state: AgentState):
    if state["error"] and state["iteration"] < 3:
        return "error_agent"
    return "parallel_analysis"  # Updated to use parallel execution node

def should_generate_graph(state: AgentState):
    if state.get("needs_graph"):
        return "viz_agent"
    return END

workflow = StateGraph(AgentState)

workflow.add_node("guardrail_agent", guardrail_agent)
workflow.add_node("sql_agent", sql_agent)
workflow.add_node("execute_sql", execute_sql)
workflow.add_node("error_agent", error_agent)
# PARALLEL OPTIMIZATION: Combined node runs analysis + graph decision concurrently
workflow.add_node("parallel_analysis", parallel_analysis_and_graph_decision_sync)
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
        "parallel_analysis": "parallel_analysis"  # Go to parallel node instead of analysis_agent
    }
)

workflow.add_edge("error_agent", "sql_agent")

# After parallel execution, check if graph is needed
workflow.add_conditional_edges(
    "parallel_analysis",
    should_generate_graph,
    {
        "viz_agent": "viz_agent",
        END: END
    }
)

workflow.add_edge("viz_agent", END)

app_graph = workflow.compile()
