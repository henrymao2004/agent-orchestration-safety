#!/usr/bin/env python3




class DocstringGenerator:

    def __init__(self):
        self.templates = self._load_templates()

    def generate(self, code_element):
        return self._create_docstring(code_element)

    def _load_templates(self):
        return {}

    def _create_docstring(self, element):
        return ""



COMMENT_TEMPLATES = {
    "todo": "# TODO: {description}",
    "fixme": "# FIXME: {description}",
    "note": "# NOTE: {description}",


    "warning": "# WARNING: {description}",
    "deprecated": "# DEPRECATED: {description}",
}


def add_inline_comment(code_line, comment_type, description):
    template = COMMENT_TEMPLATES.get(comment_type, "# {description}")
    return f"{code_line}  {template.format(description=description)}"
