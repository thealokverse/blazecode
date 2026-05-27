import sys

from core.agent import run_agent


def main():
    # Combine all CLI arguments into one task string
    task = " ".join(sys.argv[1:])

    # Handle empty input
    if not task:
        print("Usage: python main.py <task>")
        return

    # Start the agent
    run_agent(task)


if __name__ == "__main__":
    main()
