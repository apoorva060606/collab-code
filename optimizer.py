"""
Hand-in Code Optimizer Engine.
Analyzes code for performance bottlenecks, algorithmic inefficiencies, and anti-patterns.
Provides Big-O complexity comparison, educational explanations, and one-click
applicable optimized refactored code. Supports Python, JavaScript, and optional Gemini LLM fallback.
"""

import ast
import re
import os
import urllib.request
import json
from typing import List, Dict, Any, Optional

def analyze_code_for_optimizations(code: str, language: str = "python") -> Dict[str, Any]:
    """
    Main entry point for hand-in code optimization suggestions.
    Returns a dictionary with summary, overall complexity score, and individual suggestions.
    """
    code = code.strip()
    if not code:
        return {
            "has_suggestions": False,
            "overall_status": "Clean",
            "message": "No code provided to analyze.",
            "suggestions": []
        }

    suggestions: List[Dict[str, Any]] = []

    # If Gemini API Key is configured in environment, attempt AI enhancement first or combine
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        ai_suggestions = _query_gemini_optimizer(code, language, gemini_key)
        if ai_suggestions:
            suggestions.extend(ai_suggestions)

    if language.lower() in ("python", "py"):
        py_suggestions = _analyze_python_ast_and_patterns(code)
        suggestions.extend(py_suggestions)
    elif language.lower() in ("javascript", "js", "typescript", "ts"):
        js_suggestions = _analyze_javascript_patterns(code)
        suggestions.extend(js_suggestions)
    else:
        generic_suggestions = _analyze_generic_patterns(code)
        suggestions.extend(generic_suggestions)

    # Deduplicate suggestions by title
    seen_titles = set()
    unique_suggestions = []
    for s in suggestions:
        if s["title"] not in seen_titles:
            seen_titles.add(s["title"])
            unique_suggestions.append(s)

    # If no specific bottlenecks found, provide positive reinforcement or clean style note
    if not unique_suggestions:
        return {
            "has_suggestions": False,
            "overall_status": "Optimal",
            "message": "Great job! No major algorithmic bottlenecks or quadratic patterns were detected in this snippet.",
            "suggestions": []
        }

    return {
        "has_suggestions": True,
        "overall_status": "Optimization Recommended",
        "message": f"Found {len(unique_suggestions)} optimization suggestion(s) to improve runtime complexity and performance.",
        "suggestions": unique_suggestions
    }


def _analyze_python_ast_and_patterns(code: str) -> List[Dict[str, Any]]:
    suggestions = []

    # 1. Unmemoized Naive Recursive Fibonacci / Exponential Recursion
    if re.search(r"def\s+(\w+)\s*\((.*?)\):.*?\1\s*\([^)]*-\s*1\).*?\1\s*\([^)]*-\s*2\)", code, re.DOTALL):
        func_match = re.search(r"def\s+(\w+)\s*\(", code)
        func_name = func_match.group(1) if func_match else "fib"
        suggestions.append({
            "title": f"Exponential Recursive Calls in '{func_name}' (O(2^N) to O(N))",
            "category": "Time Complexity / Algorithm",
            "complexity_before": "O(2^N) Time, O(N) Call Stack",
            "complexity_after": "O(N) Time, O(1) Auxiliary Space",
            "explanation": (
                f"The function `{func_name}` makes branching recursive calls `(n-1)` and `(n-2)` without caching results. "
                "This leads to an exponential call tree that recomputes identical subproblems millions of times. "
                "By using an iterative approach or `@functools.lru_cache`, time complexity drops dramatically from exponential O(2^N) to linear O(N)."
            ),
            "optimized_code": (
                f"# [Optimized] Linear O(N) iterative implementation\n"
                f"def {func_name}(n: int) -> int:\n"
                f"    if n <= 1:\n"
                f"        return n\n"
                f"    prev, curr = 0, 1\n"
                f"    for _ in range(2, n + 1):\n"
                f"        prev, curr = curr, prev + curr\n"
                f"    return curr\n"
            )
        })

    # 2. Nested Loops with 'in' membership check on lists (O(N^2) -> O(N))
    nested_in_match = re.search(r"for\s+(\w+)\s+in\s+(\w+):.*?for\s+(\w+)\s+in\s+(\w+):", code, re.DOTALL)
    in_lookup_match = re.search(r"for\s+(\w+)\s+in\s+(\w+):.*?if\s+(\w+)\s+in\s+(\w+):", code, re.DOTALL)

    if in_lookup_match and "set(" not in code:
        item_var, loop_collection, search_item, target_collection = in_lookup_match.groups()
        suggestions.append({
            "title": f"Linear Membership Search in Loop on '{target_collection}' (O(N*M) to O(N+M))",
            "category": "Time Complexity / Data Structure",
            "complexity_before": "O(N * M) Time (Linear Scan per iteration)",
            "complexity_after": "O(N + M) Time (O(1) Hash Set Lookups)",
            "explanation": (
                f"Checking `if {search_item} in {target_collection}` inside a loop forces Python to linearly scan "
                f"`{target_collection}` on every iteration (O(M)). "
                f"Converting `{target_collection}` into a `set` beforehand gives O(1) average lookup time, "
                f"reducing total execution time from quadratic O(N * M) down to linear O(N + M)."
            ),
            "optimized_code": (
                f"# [Optimized] Precompute a hash set for O(1) membership lookups\n"
                f"{target_collection}_set = set({target_collection})\n"
                f"results = [item for item in {loop_collection} if item in {target_collection}_set]\n"
            )
        })

    # 3. Two-Sum / Nested Brute-Force Loops (O(N^2) -> O(N))
    two_sum_match = re.search(r"for\s+i\s+in\s+range\s*\(.*?len\((\w+)\).*?\):.*?for\s+j\s+in\s+range\s*\(.*?i\s*\+\s*1", code, re.DOTALL)
    if two_sum_match:
        arr_name = two_sum_match.group(1)
        suggestions.append({
            "title": f"Nested Quadratic Pair Search on '{arr_name}' (O(N^2) to O(N))",
            "category": "Time Complexity / Hash Map",
            "complexity_before": "O(N^2) Time",
            "complexity_after": "O(N) Time, O(N) Space",
            "explanation": (
                f"The nested loop inspects every pair of elements in `{arr_name}` resulting in O(N^2) comparisons. "
                "Using a dictionary / hash map to store previously seen values and their indices allows checking complements in single-pass O(N) time."
            ),
            "optimized_code": (
                f"# [Optimized] Single-pass Hash Map approach (O(N) Time)\n"
                f"def two_sum_optimized(nums, target):\n"
                f"    seen = {{}}\n"
                f"    for i, num in enumerate(nums):\n"
                f"        complement = target - num\n"
                f"        if complement in seen:\n"
                f"            return [seen[complement], i]\n"
                f"        seen[num] = i\n"
                f"    return []\n"
            )
        })

    # 4. Inefficient String Concatenation in Loop (s += x)
    concat_match = re.search(r"(\w+)\s*=\s*['\"].*?for\s+.*?:\s*.*?\1\s*\+=", code, re.DOTALL)
    if concat_match:
        str_var = concat_match.group(1)
        suggestions.append({
            "title": f"Inefficient String Concatenation in Loop on '{str_var}' (O(N^2) to O(N))",
            "category": "Memory & Performance",
            "complexity_before": "O(N^2) Time (Repeated string allocations)",
            "complexity_after": "O(N) Time, O(N) Space",
            "explanation": (
                f"In Python, strings are immutable. Repeatedly doing `{str_var} += ...` in a loop allocates a new string buffer "
                "and copies all preceding characters every time, degrading performance to O(N^2). "
                "Accumulating pieces in a list and joining with `''.join(...)` runs in linear O(N) time with minimal memory overhead."
            ),
            "optimized_code": (
                f"# [Optimized] Accumulate in a list and use str.join()\n"
                f"chunks = []\n"
                f"# inside your loop: chunks.append(item)\n"
                f"{str_var} = ''.join(chunks)\n"
            )
        })

    # 5. Parsing AST to detect range(len(...)) anti-pattern
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.For):
                if isinstance(node.iter, ast.Call) and getattr(node.iter.func, 'id', '') == 'range':
                    if len(node.iter.args) == 1 and isinstance(node.iter.args[0], ast.Call):
                        inner = node.iter.args[0]
                        if getattr(inner.func, 'id', '') == 'len' and inner.args:
                            target_arr = getattr(inner.args[0], 'id', 'items')
                            suggestions.append({
                                "title": f"Unidiomatic Index Iteration 'range(len({target_arr}))'",
                                "category": "Code Quality & Micro-optimization",
                                "complexity_before": "O(N) (Extra indexing lookups)",
                                "complexity_after": "O(N) (Direct C-level iteration)",
                                "explanation": (
                                    f"Iterating using `for i in range(len({target_arr})):` requires repetitive index lookups `{target_arr}[i]`. "
                                    f"Use `for item in {target_arr}:` or `for i, item in enumerate({target_arr}):` for cleaner, faster direct access."
                                ),
                                "optimized_code": (
                                    f"# [Optimized] Direct enumeration\n"
                                    f"for i, item in enumerate({target_arr}):\n"
                                    f"    # use `item` directly without {target_arr}[i]\n"
                                    f"    pass\n"
                                )
                            })
                            break
    except Exception:
        pass

    # 6. Bubble Sort / Naive Sort detection
    if re.search(r"for\s+i\s+in\s+range.*?for\s+j\s+in\s+range.*?if.*?\[j\].*?>.*?\[j\s*\+\s*1\]:.*?\[j\].*?,.*?\[j\s*\+\s*1\]\s*=", code, re.DOTALL):
        suggestions.append({
            "title": "Manual Quadratic Sorting (Bubble Sort) (O(N^2) to O(N log N))",
            "category": "Algorithm Complexity",
            "complexity_before": "O(N^2) Comparisons & Swaps",
            "complexity_after": "O(N log N) (Timsort)",
            "explanation": (
                "Manual nested-loop bubble sort runs in O(N^2) time. Python's built-in `.sort()` or `sorted()` "
                "uses Timsort, implemented in optimized C with O(N log N) worst-case and O(N) best-case performance."
            ),
            "optimized_code": (
                "# [Optimized] Built-in Timsort (O(N log N))\n"
                "items.sort()  # In-place, highly optimized\n"
            )
        })

    return suggestions


def _analyze_javascript_patterns(code: str) -> List[Dict[str, Any]]:
    suggestions = []

    # 1. Array.includes() or Array.indexOf() inside loop
    if re.search(r"(for\s*\(.*?\)|\.forEach|\.map|\.filter).*?(\.indexOf\(|\.includes\()", code, re.DOTALL):
        suggestions.append({
            "title": "Array Linear Search (.includes / .indexOf) inside Loop (O(N*M) to O(N+M))",
            "category": "Time Complexity / JavaScript Engine",
            "complexity_before": "O(N * M) Time (Repeated Array Scans)",
            "complexity_after": "O(N + M) Time (Set.prototype.has)",
            "explanation": (
                "Calling `array.includes()` or `array.indexOf()` inside a loop performs a linear scan on every iteration. "
                "Constructing a `new Set(array)` beforehand and using `set.has()` performs instant O(1) hash lookups."
            ),
            "optimized_code": (
                "// [Optimized] Precompute Set for O(1) lookups\n"
                "const lookupSet = new Set(targetArray);\n"
                "const filtered = sourceArray.filter(item => lookupSet.has(item));\n"
            )
        })

    # 2. String concatenation in loop
    if re.search(r"(for\s*\(.*?\)|\.forEach).*?\+\s*=", code, re.DOTALL):
        suggestions.append({
            "title": "String Concatenation in Loop (V8 Memory Overhead)",
            "category": "Memory / GC Overhead",
            "complexity_before": "High Garbage Collection pressure & string re-allocation",
            "complexity_after": "Single allocation via Array.join()",
            "explanation": (
                "Repeated string concatenation inside loops triggers frequent V8 engine memory re-allocations and GC sweeps. "
                "Pushing tokens to an array and using `.join('')` is significantly faster on large inputs."
            ),
            "optimized_code": (
                "// [Optimized] Array push and join\n"
                "const buffer = [];\n"
                "for (const item of items) {\n"
                "    buffer.push(item);\n"
                "}\n"
                "const result = buffer.join('');\n"
            )
        })

    # 3. Recursive Fibonacci in JS
    if re.search(r"function\s+(\w+)\s*\((.*?)\).*?\1\s*\([^)]*-\s*1\).*?\1\s*\([^)]*-\s*2\)", code, re.DOTALL):
        func_match = re.search(r"function\s+(\w+)\s*\(", code)
        func_name = func_match.group(1) if func_match else "fib"
        suggestions.append({
            "title": f"Exponential Call Stack in '{func_name}' (O(2^N) to O(N))",
            "category": "Time Complexity",
            "complexity_before": "O(2^N) Time, Potential Maximum Call Stack Size Exceeded",
            "complexity_after": "O(N) Time, O(1) Space",
            "explanation": (
                f"`{func_name}` causes exponential duplicate calculations and risks stack overflow for larger inputs. "
                "An iterative loop computes Fibonacci numbers in O(N) time with constant O(1) memory."
            ),
            "optimized_code": (
                f"// [Optimized] Iterative O(N) time, O(1) space\n"
                f"function {func_name}(n) {{\n"
                f"    if (n <= 1) return n;\n"
                f"    let prev = 0, curr = 1;\n"
                f"    for (let i = 2; i <= n; i++) {{\n"
                f"        const next = prev + curr;\n"
                f"        prev = curr;\n"
                f"        curr = next;\n"
                f"    }}\n"
                f"    return curr;\n"
                f"}}\n"
            )
        })

    return suggestions


def _analyze_generic_patterns(code: str) -> List[Dict[str, Any]]:
    suggestions = []
    # Nested loops generic detection
    nested_for = re.findall(r"for\b", code)
    if len(nested_for) >= 2:
        suggestions.append({
            "title": "Multiple Loops / Potential Polynomial Complexity",
            "category": "Algorithmic Inspection",
            "complexity_before": "Potential O(N^2) or higher",
            "complexity_after": "O(N) or O(N log N) with Hash Map / Divide & Conquer",
            "explanation": (
                "Multiple loops detected in the snippet. Check if inner loops can be eliminated "
                "using hash maps, frequency tables, prefix sums, or sorting."
            ),
            "optimized_code": "// Consider pre-indexing data in a Map or Hash Table to avoid nested lookups."
        })
    return suggestions


def _query_gemini_optimizer(code: str, language: str, api_key: str) -> List[Dict[str, Any]]:
    """Query Google Gemini API for deep AI optimization if API key is supplied."""
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
        prompt = (
            f"You are a master algorithms and code performance optimization expert. Analyze this {language} code for optimization:\n\n"
            f"```\n{code}\n```\n\n"
            "Respond ONLY with valid JSON in this exact schema without markdown fences:\n"
            "[\n"
            "  {\n"
            '    "title": "Short title",\n'
            '    "category": "Complexity / Algorithm",\n'
            '    "complexity_before": "e.g. O(N^2)",\n'
            '    "complexity_after": "e.g. O(N)",\n'
            '    "explanation": "Clear explanation of inefficiency and fix",\n'
            '    "optimized_code": "Complete refactored code ready to replace in editor"\n'
            "  }\n"
            "]"
        )
        req_data = {
            "contents": [{"parts": [{"text": prompt}]}]
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(req_data).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            result = json.loads(response.read().decode("utf-8"))
            content = result["candidates"][0]["content"]["parts"][0]["text"].strip()
            # Clean possible markdown wrapping
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            data = json.loads(content.strip())
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []
