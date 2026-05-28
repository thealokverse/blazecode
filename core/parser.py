def extract_tool_call(response):

    message = response.choices[0].message

    if not message.tool_calls:
        return None

    tool_call = message.tool_calls[0]

    return {"name": tool_call.function.name, "args": tool_call.function.arguments}
