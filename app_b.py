"""Lab application B: independently running peer of application A."""
from lab_app import main

if __name__ == "__main__":
    raise SystemExit(main(default_node="node-b"))
