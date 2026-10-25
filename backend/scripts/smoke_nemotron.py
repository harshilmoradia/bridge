import os, sys
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(
    base_url="https://api.tokenfactory.nebius.com/v1/",
    api_key=os.environ["NEBIUS_API_KEY"],
)

# 1) list every Nemotron model the account can see
ids = sorted(m.id for m in client.models.list().data if "nemotron" in m.id.lower())
print("\n".join(ids))

# 2) call one (pass an ID as argv[1], else the first one found)
model = sys.argv[1] if len(sys.argv) > 1 else ids[0]
r = client.chat.completions.create(
    model=model,
    messages=[{"role": "user", "content": "Reply with exactly: bridge-ok"}],
    max_tokens=500,  # reasoning models may spend tokens thinking first
)
print(model, "->", r.choices[0].message.content)