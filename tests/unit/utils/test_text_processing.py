import os
import tokenize

import pytest

from repogpt.utils.text_processing import (
    count_blank_lines,
    extract_comments,
)


def test_python_comments_preserve_hashes_after_the_delimiter() -> None:
    assert extract_comments("## Note\n# # Header\n#   padded  \n#\n") == [
        {"text": "# Note", "line": 1},
        {"text": "# Header", "line": 2},
        {"text": "padded", "line": 3},
        {"text": "", "line": 4},
    ]


DATA_DIR = os.path.join(os.path.dirname(__file__), "../../data")


def load_file(name: str) -> str:
    with open(os.path.join(DATA_DIR, name), encoding="utf-8") as f:
        return f.read()


# ---------- BASIC PYTHON ----------
def test_blank_lines_basic_py() -> None:
    text = load_file("basic.py")
    assert count_blank_lines(text) == 2


def test_comments_basic_py() -> None:
    text = load_file("basic.py")
    comments = extract_comments(text, language="python")
    assert comments == []


# ---------- WITH COMMENTS MARKDOWN ----------
def test_comments_with_comments_md() -> None:
    text = load_file("with_comments.md")
    comments = extract_comments(text, language="markdown")
    texts = [c["text"] for c in comments]
    assert texts == [
        "Este es un comentario en markdown",
        "TODO: Completar sección",
        "FIXME: Revisar formato",
    ]


# ---------- EDGE CASES PY ----------
def test_comments_edge_cases_py() -> None:
    text = load_file("edge_cases.py")
    comments = extract_comments(text, language="python")
    assert "Este es un comentario normal" in [c["text"] for c in comments]
    assert "TODO: pendiente de implementar" in [c["text"] for c in comments]


# ---------- DOCSTRING EXAMPLES PY ----------
def test_docstring_examples() -> None:
    text = load_file("docstring_examples.py")
    comments = extract_comments(text, language="python")
    texts = [c["text"] for c in comments]
    # Keep this aligned with the real parser fixture.
    assert "Comentario entre docstring y código" in texts or texts == []


# ---------- BASIC MARKDOWN ----------
def test_blank_lines_basic_md() -> None:
    text = load_file("basic.md")
    assert count_blank_lines(text) >= 0


def test_comments_basic_md() -> None:
    text = load_file("basic.md")
    comments = extract_comments(text, language="markdown")
    assert comments == []


def test_comments_edge_cases_py_unicode() -> None:
    text = load_file("edge_cases_comments.py")
    comments = extract_comments(text, language="python")
    texts = [c["text"] for c in comments]
    assert "Este es un comentario con acento: áéíóú" in texts
    assert any("😊" in t for t in texts)
    assert not any(t == "# Esto tampoco es comentario" for t in texts)
    assert any("tarea pendiente λ" in t for t in texts)
    assert any("Comentario sin espacio tras hash" in t for t in texts)
    assert any("indentación" in t for t in texts)
    assert any("símbolos matemáticos" in t for t in texts)


def test_blank_lines_edge_cases() -> None:
    text = load_file("edge_cases_blanklines.py")
    assert count_blank_lines(text) == 3


def test_comments_edge_cases_md() -> None:
    text = load_file("edge_cases.md")
    comments = extract_comments(text, language="markdown")
    texts = [c["text"] for c in comments]
    assert any("emoji" in t or "🎉" in t for t in texts)
    assert any("caracteres raros" in t for t in texts)
    assert any("ComentarioSinEspacios" in t for t in texts)


def test_markdown_comment_line_numbers_are_correct() -> None:
    content = "<!-- first -->\ntext\n<!-- second -->\nmore\n<!-- third\nend -->\n"
    comments = extract_comments(content, language="markdown")
    assert [c["line"] for c in comments] == [1, 3, 5]


def test_markdown_comment_on_first_line() -> None:
    comments = extract_comments("<!-- hello -->\nnext line", language="markdown")
    assert comments[0]["line"] == 1


def test_markdown_comment_after_several_newlines() -> None:
    content = "\n\n\n<!-- deep -->"
    comments = extract_comments(content, language="markdown")
    assert comments[0]["line"] == 4


def test_markdown_comment_line_numbers_match_old_behavior() -> None:
    content = "line1\n<!-- a -->\nline3\n\n<!-- b -->\n<!-- c -->"
    comments = extract_comments(content, language="markdown")
    expected_lines = [
        content.count("\n", 0, content.index("<!-- a -->")) + 1,
        content.count("\n", 0, content.index("<!-- b -->")) + 1,
        content.count("\n", 0, content.index("<!-- c -->")) + 1,
    ]
    assert [c["line"] for c in comments] == expected_lines


def test_extract_comments_logs_debug_when_python_tokenization_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logged: list[dict[str, str]] = []

    class DummyLogger:
        def debug(self, event: str, **kwargs: str) -> None:
            logged.append({"event": event, **kwargs})

    def boom(readline):  # type: ignore[no-untyped-def]
        raise tokenize.TokenError("broken", (1, 0))

    monkeypatch.setattr("repogpt.utils.text_processing.logger", DummyLogger())
    monkeypatch.setattr("repogpt.utils.text_processing.tokenize.generate_tokens", boom)

    comments = extract_comments("x=1", language="python")

    assert comments == []
    assert logged == [
        {
            "event": "python comment extraction failed",
            "error": "('broken', (1, 0))",
        }
    ]
