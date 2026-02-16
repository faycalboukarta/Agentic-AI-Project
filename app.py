import asyncio
import os
import sys

# Windows Event Loop Fix
if sys.platform == "win32":
    if sys.version_info >= (3, 13) and sys.version_info < (3, 15):
        print(f"WARNING: You are running Python {sys.version}. This version has known compatibility issues with Chainlit/AnyIO on Windows.", file=sys.stderr)
        print("RECOMMENDATION: Please use Python 3.11 via Anaconda as described in verify_agent.py or README.md.", file=sys.stderr)
        # Try to force the legacy selector loop which is sometimes more compatible
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    else:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import chainlit as cl
from text2sql_agent import app_graph
import plotly.io as pio
import json
import nest_asyncio

nest_asyncio.apply()

@cl.on_chat_start
async def on_chat_start():
    cl.user_session.set("graph", app_graph)
    await cl.Message(content="Welcome to the E-commerce Data Assistant! Ask me anything about your orders, products, or customers.").send()

@cl.on_message
async def on_message(message: cl.Message):
    graph = cl.user_session.get("graph")
    
    # Initialize state
    initial_state = {
        "question": message.content,
        "iteration": 0,
        "is_in_scope": True,
        "error": "",
        "sql_query": "",
        "query_result": "",
        "needs_graph": False,
        "graph_json": ""
    }
    
    # Run the graph
    res = await graph.ainvoke(initial_state)
    
    # Send the SQL query if available
    if res.get("sql_query"):
        await cl.Message(content=f"**Generated SQL:**\n```sql\n{res['sql_query']}\n```").send()
    
    # Send the final answer
    if res.get("final_answer"):
        await cl.Message(content=res["final_answer"]).send()
    
    # Send the graph if available
    if res.get("graph_json"):
        try:
            fig = pio.from_json(res["graph_json"])
            await cl.Message(content="**Visualization:**", elements=[cl.Plotly(name="chart", figure=fig, display="inline")]).send()
        except Exception as e:
            await cl.Message(content=f"Error displaying graph: {e}").send()
