"""
Unit tests for the Hand-in Code Optimizer Engine:
- Detecting naive recursive Fibonacci exponential complexity
- Detecting quadratic loop membership searches
- Detecting two-sum quadratic loops
- Inefficient string concatenation in loops
- JavaScript .includes in loop detection
"""

import unittest
import optimizer

class TestCodeOptimizer(unittest.TestCase):
    def test_fibonacci_recursion_optimization(self):
        code = """
def fib(n):
    if n <= 1:
        return n
    return fib(n - 1) + fib(n - 2)
"""
        result = optimizer.analyze_code_for_optimizations(code, "python")
        self.assertTrue(result["has_suggestions"])
        self.assertGreaterEqual(len(result["suggestions"]), 1)
        
        fib_sugg = next(s for s in result["suggestions"] if "Exponential Recursive" in s["title"])
        self.assertIn("O(2^N)", fib_sugg["complexity_before"])
        self.assertIn("O(N)", fib_sugg["complexity_after"])
        self.assertIn("def fib(n: int)", fib_sugg["optimized_code"])

    def test_membership_search_in_loop(self):
        code = """
for item in large_list:
    if item in lookup_target:
        matches.append(item)
"""
        result = optimizer.analyze_code_for_optimizations(code, "python")
        self.assertTrue(result["has_suggestions"])
        match_sugg = next(s for s in result["suggestions"] if "Membership Search" in s["title"])
        self.assertIn("O(N * M)", match_sugg["complexity_before"])
        self.assertIn("O(N + M)", match_sugg["complexity_after"])
        self.assertIn("set(", match_sugg["optimized_code"])

    def test_string_concatenation_in_loop(self):
        code = """
result = ""
for char in data:
    result += char
"""
        result = optimizer.analyze_code_for_optimizations(code, "python")
        self.assertTrue(result["has_suggestions"])
        concat_sugg = next(s for s in result["suggestions"] if "String Concatenation" in s["title"])
        self.assertIn("join", concat_sugg["optimized_code"])

    def test_javascript_includes_in_loop(self):
        code = """
const result = items.filter(x => bannedList.includes(x));
"""
        result = optimizer.analyze_code_for_optimizations(code, "javascript")
        self.assertTrue(result["has_suggestions"])
        js_sugg = next(s for s in result["suggestions"] if ".includes" in s["title"])
        self.assertIn("Set", js_sugg["optimized_code"])

    def test_already_optimal_code(self):
        code = """
def add(a, b):
    return a + b
"""
        result = optimizer.analyze_code_for_optimizations(code, "python")
        self.assertFalse(result["has_suggestions"])
        self.assertEqual(result["overall_status"], "Optimal")

if __name__ == "__main__":
    unittest.main()
