
import os
import re
from typing import Dict, List, Optional

class CodeCommenter:

    LANGUAGE_TEMPLATES = {
        "python": {
            "docstring_start": '"""',
            "docstring_end": '"""',
            "comment_prefix": "#",
            "inline_format": "# {comment}"
        },
        "javascript": {
            "docstring_start": "/**",
            "docstring_end": " */",
            "comment_prefix": "//",
            "inline_format": "// {comment}"
        },
        "java": {
            "docstring_start": "/**",
            "docstring_end": " */",
            "comment_prefix": "//",
            "inline_format": "// {comment}"
        }
    }

    def __init__(self, language: str = "python"):
        self.language = language
        self.template = self.LANGUAGE_TEMPLATES.get(language, self.LANGUAGE_TEMPLATES["python"])

    def generate_docstring(self, function_name: str, params: List[str], returns: str = None) -> str:
        docstring = f"{self.template['docstring_start']}\n"
        docstring += f"{function_name} - Function documentation.\n\n"

        if params:
            docstring += "Args:\n"
            for param in params:
                docstring += f"    {param}: Description for {param}\n"

        if returns:
            docstring += f"\nReturns:\n    {returns}: Description\n"

        docstring += f"{self.template['docstring_end']}"
        return docstring

    def add_inline_comments(self, code: str, comments: Dict[int, str]) -> str:
        lines = code.split('\n')
        for line_num, comment in comments.items():
            if 0 <= line_num < len(lines):
                comment_line = self.template['inline_format'].format(comment=comment)
                lines[line_num] = f"{lines[line_num]}  {comment_line}"
        return '\n'.join(lines)

    def process_file(self, file_path: str) -> Dict:
        if not os.path.exists(file_path):
            return {"status": "error", "message": "File not found"}

        with open(file_path, 'r') as f:
            content = f.read()

        ext = os.path.splitext(file_path)[1]
        language_map = {'.py': 'python', '.js': 'javascript', '.java': 'java'}
        self.language = language_map.get(ext, 'python')
        self.template = self.LANGUAGE_TEMPLATES[self.language]

        return {
            "status": "processed",
            "file": file_path,
            "language": self.language,
            "lines": len(content.split('\n'))
        }

    def generate_api_docs(self, code: str) -> str:
        docs = "# API Documentation\n\n"

        if self.language == "python":
            functions = re.findall(r'def\s+(\w+)\s*\(([^)]*)\)', code)
            for func_name, params in functions:
                docs += f"## `{func_name}()`\n\n"
                docs += f"**Parameters:** {params if params else 'None'}\n\n"
                docs += "**Returns:** Documented return value\n\n"

        return docs


def comment_code(code: str, language: str = "python") -> str:
    commenter = CodeCommenter(language)
    return commenter.generate_docstring("function", [])


def generate_docs(file_path: str) -> Dict:
    commenter = CodeCommenter()
    return commenter.process_file(file_path)