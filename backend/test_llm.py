import os
from dotenv import load_dotenv
from groq import Groq

load_dotenv()
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

try:
    chat_completion = client.chat.completions.create(
        messages=[{"role": "user", "content": "Return {\"test\": 123} in JSON"}],
        model="openai/gpt-oss-20b",
        response_format={"type": "json_object"}
    )
    print("gpt-oss-20b response:", chat_completion.choices[0].message.content)
except Exception as e:
    print(f"gpt-oss-20b error: {e}")

