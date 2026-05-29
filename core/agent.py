import json

from core.config import MAX_ITERATIONS
from core.llm import chat
from core.parser import extract_tool_call
from core.prompts import SYSTEM_PROMPT
from tools.files import read_file, write_file
from tools.shell import run_shell

# Tool registry
TOOLS = {
    "read_file": read_file,
    "write_file": write_file,
    "run_shell": run_shell,
}


# Tool schemas exposed to model
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write to a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": "Run terminal command",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
]


def run_agent(task):
    """
    Main agent loop.
    """

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]

    for _ in range(MAX_ITERATIONS):
        # Ask model what to do
        response = chat(messages, TOOL_SCHEMAS)

        message = response.choices[0].message

        # Check if model wants a tool
        tool_call = extract_tool_call(response)

        # Final answer
        if not tool_call:
            print("\nFinal Answer:\n")
            print(message.content)
            return

        tool_name = tool_call["name"]
        tool_args = json.loads(tool_call["args"])

        print(f"\n[TOOL] {tool_name}")

        # Execute tool
        tool_function = TOOLS[tool_name]

        result = tool_function(**tool_args)

        print(result)

        # Save assistant message
        messages.append(message)

        # Save tool result
        messages.append(
            {
                "role": "tool",
                "tool_call_id": message.tool_calls[0].id,
                "content": str(result),
            }
        )

    print("Max iterations reached.")
