import os
from typing import TypedDict
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END

# Load environment variables
load_dotenv()

app = FastAPI(title="AI Bug Report Analyzer")
templates = Jinja2Templates(directory="templates")

# Pydantic model for incoming request
class BugRequest(BaseModel):
    description: str

# 1. Define the State Structure
class BugReportState(TypedDict):
    raw_description: str
    title: str
    affected_feature: str
    summary: str
    severity: str
    root_cause: str
    final_report: str

# Initialize the Gemini model
llm = ChatGoogleGenerativeAI(model="gemini-3.8-flash", temperature=0.2)

# Helper function to extract text
def get_content_string(response_content) -> str:
    if isinstance(response_content, str):
        return response_content
    if isinstance(response_content, list):
        text_parts = []
        for item in response_content:
            if isinstance(item, dict) and "text" in item:
                text_parts.append(str(item["text"]))
            else:
                text_parts.append(str(item))
        return "".join(text_parts)
    if isinstance(response_content, dict) and "text" in response_content:
        return str(response_content["text"])
    return str(response_content)

# 2. Define Workflow Nodes
def node_bug_analysis(state: BugReportState):
    prompt = f"""
    Analyze the following bug description and provide:
    1. A short, descriptive bug title.
    2. The affected feature/module.
    3. A concise issue summary.

    Bug Description: {state['raw_description']}

    Format your response strictly as:
    Title: <title>
    Feature: <feature>
    Summary: <summary>
    """
    raw_response = llm.invoke(prompt).content
    response = get_content_string(raw_response)
    
    lines = response.strip().split("\n")
    title = lines[0].replace("Title:", "").strip() if len(lines) > 0 else "Unknown Bug"
    feature = lines[1].replace("Feature:", "").strip() if len(lines) > 1 else "Unknown Feature"
    summary = lines[2].replace("Summary:", "").strip() if len(lines) > 2 else state['raw_description']

    return {"title": title, "affected_feature": feature, "summary": summary}


def node_severity_detection(state: BugReportState):
    prompt = f"""
    Classify the severity of this bug into exactly one of these categories: Critical, High, Medium, Low.
    Summary: {state['summary']}
    Output ONLY the severity level word (e.g., High).
    """
    raw_response = llm.invoke(prompt).content
    severity = get_content_string(raw_response).strip()
    return {"severity": severity}


def node_root_cause_suggestion(state: BugReportState):
    prompt = f"""
    Based on the bug summary and affected feature, suggest 2-3 potential technical root causes for this issue.
    Feature: {state['affected_feature']}
    Summary: {state['summary']}
    Provide brief, actionable bullet points.
    """
    raw_response = llm.invoke(prompt).content
    root_cause = get_content_string(raw_response).strip()
    return {"root_cause": root_cause}


def node_format_report(state: BugReportState):
    report = f"""
========================================
           STRUCTURED BUG REPORT        
========================================
**Bug Title:** {state['title']}
**Affected Feature:** {state['affected_feature']}
**Severity Level:** {state['severity']}

---
### Issue Summary
{state['summary']}

---
### Suggested Root Causes
{state['root_cause']}
========================================
    """
    return {"final_report": report.strip()}

# 3. Build LangGraph Workflow
workflow = StateGraph(BugReportState)
workflow.add_node("bug_analysis", node_bug_analysis)
workflow.add_node("severity_detection", node_severity_detection)
workflow.add_node("root_cause_suggestion", node_root_cause_suggestion)
workflow.add_node("format_report", node_format_report)

workflow.set_entry_point("bug_analysis")
workflow.add_edge("bug_analysis", "severity_detection")
workflow.add_edge("severity_detection", "root_cause_suggestion")
workflow.add_edge("root_cause_suggestion", "format_report")
workflow.add_edge("format_report", END)

app_graph = workflow.compile()

# FastAPI Routes (Fixed TemplateResponse format)
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(request, "index.html", {})

@app.post("/analyze")
async def analyze_bug(payload: BugRequest):
    if not payload.description.strip():
        raise HTTPException(status_code=400, detail="Bug description cannot be empty")
    
    try:
        initial_state = {"raw_description": payload.description}
        result = app_graph.invoke(initial_state)
        
        final_report = result["final_report"]
        
        # Save to Markdown file automatically
        with open("bug_report.md", "w", encoding="utf-8") as f:
            f.write(final_report)
            
        return {"report": final_report}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))