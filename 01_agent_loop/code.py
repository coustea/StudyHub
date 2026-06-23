import subprocess

from openai import OpenAI
import dotenv
import os
dotenv.load_dotenv()


llm = OpenAI(
    api_key=os.getenv("API_KEY"),
    base_url=os.getenv("BASE_URL"),
)

SYSTEM=f"你是一个ai编程助手，这是当前的{os.getcwd()},使用bash解决任务，解决问题，不要只是解释。"

TOOLS = [{
    "type": "function",
    "function": {
        "name": "bash",
        "description": "Run a shell command.",
        "parameters": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
}]

def run_bash(command: str) -> str:
    """Run a shell command."""
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(command, shell=True, cwd=os.getcwd(),
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
    except (FileNotFoundError, OSError) as e:
        return f"Error: {e}"


# ── The core pattern: a while loop that calls tools until the model stops ──
def agent_loop(messages: list):
    while True:
        response = llm.chat.completions.create(
            model=os.getenv("MODEL"),
            messages=messages,
            tools=TOOLS, max_tokens=8000,
        )

        # Get the assistant's message
        msg = response.choices[0].message

        # Append assistant turn
        messages.append({"role": "assistant", "content": msg.content, "tool_calls": msg.tool_calls})

        # If the model didn't call a tool, we're done
        if not msg.tool_calls:
            return

        # Execute each tool call, collect results
        results = []
        for tool_call in msg.tool_calls:
            if tool_call.function.name == "bash":
                import json
                args = json.loads(tool_call.function.arguments)
                print(f"\033[33m$ {args['command']}\033[0m")
                output = run_bash(args["command"])
                print(output[:200])
                results.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "content": output,
                })

        # Feed tool results back, loop continues
        messages.extend(results)


# ── Entry point ──────────────────────────────────────────
if __name__ == "__main__":
    print("s01: Agent Loop")
    print("输入问题，回车发送。输入 q 退出。\n")

    history = []
    while True:
        try:
            query = input("\033[36ms01 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append(
            {
                "role": "system",
                "content": SYSTEM,
            }
        )
        history.append(
            {
                "role": "user",
                "content": query
            },
        )

        agent_loop(history)
        # Print the model's final text response
        if history[-1].get("content"):
            print(history[-1]["content"])
        print()
















