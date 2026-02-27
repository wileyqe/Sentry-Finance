import json

with open(r"raw_exports\chase\chase_page_diagnostics.json", encoding="utf-8") as f:
    d = json.load(f)

text = d.get("body_text_preview", "")
print(f"Total body text length: {len(text)}")
print()

# Print the full body text in chunks so we can see all account tiles
chunk = 300
for i in range(0, min(len(text), 6000), chunk):
    print(f"--- [{i}:{i+chunk}] ---")
    print(text[i:i+chunk])
    print()
