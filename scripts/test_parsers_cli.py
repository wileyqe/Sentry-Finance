import os
from pathlib import Path
from dal.document_drop import get_parser, parse_document

def run_tests():
    test_dir = Path("raw_exports/test_docs")
    if not test_dir.exists():
        print(f"Directory {test_dir} does not exist.")
        return

    files = [f for f in test_dir.iterdir() if f.is_file()]
    if not files:
        print(f"No files found in {test_dir}.")
        return

    print(f"Discovered {len(files)} files for testing...\n")

    for f in files:
        print(f"--- Testing File: {f.name} ---")
        try:
            content = f.read_bytes()
            parser = get_parser(f.name, content)
            
            if parser is None:
                print("[X] No matching parser found.")
                continue
                
            print(f"[OK] Matched Parser: {parser.parser_type}")
            
            result = parser.parse(content)
            
            print("Preview:")
            for k, v in result.preview.items():
                print(f"  {k}: {v}")
                
            if result.warnings:
                print("Warnings:")
                for w in result.warnings:
                    print(f"  - {w}")
            else:
                print("[OK] No warnings.")
                
            print("\n")
        except Exception as e:
            print(f"[X] Error testing {f.name}: {e}\n")

if __name__ == "__main__":
    run_tests()
