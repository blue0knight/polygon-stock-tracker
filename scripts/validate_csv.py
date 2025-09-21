import sys
import json
import pandas as pd
from jsonschema import validate, ValidationError

def validate_csv(csv_file, schema_file):
    with open(schema_file) as f:
        schema = json.load(f)

    df = pd.read_csv(csv_file)
    for i, row in df.iterrows():
        record = row.to_dict()
        try:
            validate(instance=record, schema=schema)
        except ValidationError as e:
            print(f"Row {i} failed validation: {e.message}")
            return False
    print(f"{csv_file} passed validation ✅")
    return True

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python validate_csv.py <csv_file> <schema_file>")
        sys.exit(1)
    validate_csv(sys.argv[1], sys.argv[2])
