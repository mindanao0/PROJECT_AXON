"""MCP stdio server started by the agent CLI inside its sandbox.

Forwards tool calls to the attempt's Unix socket; that socket is the attempt's identity.
Run as a script (stdlib only) because agent CLIs may not pass PYTHONPATH to MCP servers.
"""

import json
import socket
import sys

TOOLS = [
    {"name": "report_result",
     "description": "Finish the task. status is done or failed.",
     "inputSchema": {"type": "object", "required": ["status", "summary"], "properties": {
         "status": {"type": "string", "enum": ["done", "failed"]},
         "summary": {"type": "string"}}}},
    {"name": "ask_user",
     "description": "Ask the user, then end your turn. The task resumes with the answers. For several things, send them all at once as "
                    "questions: each has its own options (the user picks one with a click, or types their own). "
                    "For a single question use question (and options).",
     "inputSchema": {"type": "object", "properties": {
         "question": {"type": "string"},
         "options": {"type": "array", "maxItems": 6, "items": {"type": "string"}},
         "questions": {"type": "array", "maxItems": 8, "items": {"type": "object", "required": ["question"], "properties": {
             "question": {"type": "string"},
             "options": {"type": "array", "maxItems": 6, "items": {"type": "string"}}}}}}}},
    {"name": "delegate",
     "description": "Queue follow-up work as a separate task that starts after you finish, from your result. "
                    "scope must stay inside yours. Limited in number; delegated tasks cannot delegate.",
     "inputSchema": {"type": "object", "required": ["title", "spec", "scope"], "properties": {
         "title": {"type": "string"}, "spec": {"type": "string"},
         "scope": {"type": "array", "items": {"type": "string"}}}}},
    {"name": "ask_peer",
     "description": "Ask the other agent (Claude asks Codex, Codex asks Claude) a question and get its answer. It is read-only "
                    "and sees the project as it was when you started, not your edits, so put the code in the question. "
                    "Waits for the answer; limited in number.",
     "inputSchema": {"type": "object", "required": ["question"], "properties": {
         "question": {"type": "string"}}}},
    {"name": "delete_file",
     "description": "Delete a file inside your scope (there is no shell). Only Claude can; other agents must ask first.",
     "inputSchema": {"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}}}},
    {"name": "move_file",
     "description": "Move or rename a file inside your scope; the destination must not exist. Only Claude can; other agents must ask first.",
     "inputSchema": {"type": "object", "required": ["from", "to"], "properties": {
         "from": {"type": "string"}, "to": {"type": "string"}}}},
    {"name": "run_check",
     "description": "Run a project check (tests, lint) in a sandbox without network. "
                    "Returns the exit code and the end of the output.",
     "inputSchema": {"type": "object", "required": ["name"], "properties": {
         "name": {"type": "string"}}}},
]


def call(sock_path, tool, args):
    with socket.socket(socket.AF_UNIX) as s:
        s.connect(sock_path)
        s.sendall((json.dumps({"tool": tool, "args": args}) + "\n").encode())
        return json.loads(s.makefile().readline())


def reply(mid, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": mid}
    msg.update({"error": error} if error else {"result": result})
    print(json.dumps(msg), flush=True)


def main(sock_path):
    for line in sys.stdin:
        if not line.strip():
            continue
        msg = json.loads(line)
        mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
        if mid is None:
            continue  # notification
        if method == "initialize":
            reply(mid, {"protocolVersion": params.get("protocolVersion", "2025-06-18"),
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "axon", "version": "0.1.0"}})
        elif method == "tools/list":
            reply(mid, {"tools": TOOLS})
        elif method == "tools/call":
            try:
                r = call(sock_path, params.get("name"), params.get("arguments") or {})
            except OSError as e:
                r = {"ok": False, "text": f"axon runtime unreachable: {e}"}
            reply(mid, {"content": [{"type": "text", "text": r["text"]}], "isError": not r["ok"]})
        elif method == "ping":
            reply(mid, {})
        else:
            reply(mid, error={"code": -32601, "message": f"unknown method {method}"})


if __name__ == "__main__":
    main(sys.argv[1])
