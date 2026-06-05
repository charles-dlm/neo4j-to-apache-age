import json

# Define the input file (your single-line JSON) and the output file
input_filename = "graph.json"
output_filename = "graph_format.json"

print(f"Reading '{input_filename}'...")

# Open the compact JSON file and load its content
with open(input_filename, "r", encoding="utf-8") as f:
    data = json.load(f)

print(f"File loaded successfully. Writing beautified JSON to '{output_filename}'...")

# Write the data back with proper indentation and formatting
with open(output_filename, "w", encoding="utf-8") as f:
    # indent=4 adds spaces for structural hierarchy
    # ensure_ascii=False keeps human-readable characters instead of \uXXXX codes
    json.dump(data, f, indent=4, ensure_ascii=False)

print("Process completed! Your JSON is now perfectly formatted.")