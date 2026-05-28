from openai import OpenAI

from core.config import MODEL, OPENAI_API_KEY

# Create client
client = OpenAI(api_key=OPENAI_API_KEY)


def chat(messages, tools=None):

    response = client.chat.completions.create(
        model=MODEL, messages=messages, tools=tools
    )

    return response
