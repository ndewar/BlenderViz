# Architectural Context Protocol

You are an expert AI software engineer operating within the HighTide Engine codebase. 
This repository is highly interconnected. To avoid hallucinating APIs or breaking downstream dependencies, you MUST follow this protocol before making any structural changes:

1. **Mandatory Context Gathering:** Whenever you are asked to modify a function, refactor a module, or trace a bug, you must FIRST call the `get_architecture_context` MCP tool.
2. **Input:** Pass the name of the target function or a natural language description of the area you need to edit.
3. **Review:** The tool will return an XML `<context>` block containing the target function's full code, its incoming callers, outgoing dependencies, and database schemas. 
4. **Action:** Read this XML carefully. Ensure your proposed edits do not break the signatures expected by the `incoming_calls` or misuse the `outgoing_calls`.

**Rule:** NEVER edit a core function without pulling its graph context via the MCP tool first.