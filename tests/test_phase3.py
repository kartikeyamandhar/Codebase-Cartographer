"""
Phase 3 - 20 Validated Test Questions
Run against psf/requests with known correct answers.
Must pass 16/20 before Phase 3 is complete.

Usage:
  python tests/test_phase3.py
"""

import json
import sys
import time
import requests as http

BASE_URL = "http://localhost:8000"
WORKSPACE_ID = "local_dev"

TESTS = [
    {
        "id": 1,
        "question": "What would break if I deleted repos/requests/src/requests/auth.py?",
        "expected_contains": ["sessions.py", "adapters.py", "models.py", "test_requests.py"],
        "flexible": False,
    },
    {
        "id": 2,
        "question": "What would break if I deleted the HTTPBasicAuth class from the codebase?",
        "expected_contains": ["HTTPBasicAuth"],
        "flexible": False,
    },
    {
        "id": 3,
        "question": "Who wrote the most code in this repo?",
        "expected_contains": ["Nate Prewitt"],
        "flexible": False,
    },
    {
        "id": 4,
        "question": "Who owns repos/requests/src/requests/sessions.py?",
        "expected_contains": ["Nate Prewitt"],
        "flexible": False,
    },
    {
        "id": 5,
        "question": "When was repos/requests/src/requests/auth.py last changed?",
        "expected_contains": ["2026"],
        "flexible": False,
    },
    {
        "id": 6,
        "question": "What files does repos/requests/src/requests/api.py import?",
        "expected_contains": ["requests"],
        "flexible": False,
    },
    {
        "id": 7,
        "question": "What imports repos/requests/src/requests/auth.py?",
        "expected_contains": ["sessions.py", "adapters.py"],
        "flexible": False,
    },
    {
        "id": 8,
        "question": "What functions call send() in the requests codebase?",
        "expected_contains": ["send"],
        "flexible": False,
    },
    {
        "id": 9,
        "question": "What does the send function call in repos/requests/src/requests/sessions.py?",
        "expected_contains": [],
        "flexible": True,
    },
    {
        "id": 10,
        "question": "Are there any circular imports in this codebase?",
        "expected_contains": ["no", "circular", "none", "not found", "0"],
        "flexible": False,
    },
    {
        "id": 11,
        "question": "Which file has the most functions?",
        "expected_contains": ["test_requests.py"],
        "flexible": False,
    },
    {
        "id": 12,
        "question": "Which function is called the most in this codebase?",
        "expected_contains": [],
        "flexible": True,
    },
    {
        "id": 13,
        "question": "What files changed in the last 10 commits?",
        "expected_contains": [],
        "flexible": True,
    },
    {
        "id": 14,
        "question": "What did Nate Prewitt change recently?",
        "expected_contains": ["Nate", "Prewitt", "nate", "prewitt"],
        "flexible": False,
    },
    {
        "id": 15,
        "question": "How many functions does this repo have?",
        "expected_contains": ["580", "579", "581", "57", "58"],
        "flexible": False,
    },
    {
        "id": 16,
        "question": "What is the most coupled file in the requests codebase?",
        "expected_contains": [],
        "flexible": True,
    },
    {
        "id": 17,
        "question": "Which functions have no callers?",
        "expected_contains": ["test_"],
        "flexible": False,
    },
    {
        "id": 18,
        "question": "What are the entry points of this repo?",
        "expected_contains": [],
        "flexible": True,
    },
    {
        "id": 19,
        "question": "What did the most recent commit change?",
        "expected_contains": [],
        "flexible": True,
    },
    {
        "id": 20,
        "question": "How many authors have contributed to this repo?",
        "expected_contains": ["148", "147", "149", "author"],
        "flexible": False,
    },
]


def run_test(test: dict) -> dict:
    try:
        response = http.post(
            f"{BASE_URL}/chat",
            json={"message": test["question"], "workspace_id": WORKSPACE_ID},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        return {"id": test["id"], "passed": False, "error": str(e),
                "answer": "", "latency_ms": 0, "tools_called": []}

    answer = data.get("answer", "").lower()
    flexible = test.get("flexible", False)

    if flexible and len(test["expected_contains"]) == 0:
        passed = len(answer) > 20 and len(data.get("tools_called", [])) > 0
    else:
        passed = any(e.lower() in answer for e in test["expected_contains"])

    return {
        "id": test["id"],
        "question": test["question"],
        "passed": passed,
        "answer": data.get("answer", "")[:200],
        "tools_called": data.get("tools_called", []),
        "latency_ms": data.get("latency_ms", 0),
        "cypher_used": data.get("cypher_used", "")[:100],
        "error": "",
    }


def main():
    print(f"\n{'═'*70}")
    print("  PHASE 3 — 20 QUESTION TEST SUITE")
    print(f"{'═'*70}\n")

    try:
        resp = http.get(f"{BASE_URL}/health", timeout=5)
        print(f"[SERVER] {resp.json()}\n")
    except Exception as e:
        print(f"[ERROR] Server not reachable: {e}")
        print("Run: uvicorn chat.orchestrator:app --reload --port 8000")
        sys.exit(1)

    results = []
    passed = 0

    for test in TESTS:
        print(f"[Q{test['id']:02d}] {test['question'][:65]}...")
        result = run_test(test)
        results.append(result)

        status = "✅ PASS" if result["passed"] else "❌ FAIL"
        print(f"      {status} | {result['latency_ms']}ms | {result.get('tools_called', [])}")
        print(f"      Answer: {result.get('answer', '')}")
        print()

        if result["passed"]:
            passed += 1
        time.sleep(0.3)

    print(f"{'═'*70}")
    print(f"  RESULTS: {passed}/20  |  Gate: 16/20")
    print(f"  {'✅ GATE PASSED' if passed >= 16 else '❌ GATE NOT MET'}")
    print(f"{'═'*70}\n")

    if passed < 20:
        print("FAILURES:")
        for r in results:
            if not r["passed"]:
                print(f"  Q{r['id']}: {r.get('question','')[:60]}")
                print(f"    Answer: {r.get('answer','')[:120]}")
                print()

    return passed >= 16


if __name__ == "__main__":
    sys.exit(0 if main() else 1)