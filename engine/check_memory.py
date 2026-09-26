"""Manual check that Atlas Vector Search returns semantically related failures.

    python -m engine.check_memory "Find the five highest-rated Nolan films"
"""
from __future__ import annotations

import sys

from engine import memory


def main() -> None:
    query = " ".join(sys.argv[1:]) or "Find the five highest-rated Nolan films."
    print(f"query: {query}\n")
    for row in memory.similar_failures(query, 5):
        print(f"{row['score']:.3f}  [{row['failure_type']}] gen {row.get('generation')}  {row['question']}")
    lessons = memory.similar_lessons(query, 3)
    if lessons:
        print("\nlessons:")
        for row in lessons:
            print(f"{row['score']:.3f}  {row['lesson']}")


if __name__ == "__main__":
    main()
