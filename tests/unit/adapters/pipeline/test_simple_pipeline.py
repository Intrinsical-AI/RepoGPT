from pathlib import Path
import uuid

from repogpt.adapters.pipeline.simple_pipeline import SimplePipeline, Processor
from repogpt.models import AnalysisConf, CodeNode, ParserInput


class MockParser:
    def parse(self, parser_input: ParserInput) -> CodeNode:
        # Devuelve siempre un nodo raíz muy básico
        return CodeNode(
            id=str(uuid.uuid4()),
            type="module",
            name="test",
            language="py",
            path=str(parser_input.file_path),
            start_line=1,
            end_line=1,
            children=[],
        )


class MockProcessor(Processor[CodeNode]):
    def __call__(self, node: CodeNode) -> CodeNode:
        node.name = "processed"
        return node


def test_process_success(tmp_path: Path) -> None:
    # Creo un archivo de prueba
    fp = tmp_path / "test.py"
    contenido = "print('hola')"
    fp.write_text(contenido, encoding="utf-8")

    parser = MockParser()
    processor: Processor[CodeNode] = MockProcessor()
    pipeline = SimplePipeline(parsers={"py": parser}, processors={"py": processor})
    conf = AnalysisConf(repo_path=tmp_path)

    result = pipeline.process(fp, conf)

    assert result.path == fp
    assert result.language == "py"
    assert result.file_info["size"] == len(contenido)
    assert isinstance(result.file_info.get("sha256"), str)
    assert result.content == contenido
    assert result.root is not None
    assert result.root.name == "processed"
    assert result.error is None


def test_process_no_parser(tmp_path: Path) -> None:
    fp = tmp_path / "test.py"
    fp.write_text("x=1", encoding="utf-8")

    pipeline = SimplePipeline(parsers={}, processors={})
    conf = AnalysisConf(repo_path=tmp_path)
    result = pipeline.process(fp, conf)

    assert result.path == fp
    assert result.language == "py"
    assert result.root is None
    assert result.error == "no parser"


def test_process_parser_error(tmp_path: Path) -> None:
    class ErrorParser:
        def parse(self, parser_input: ParserInput) -> CodeNode:
            raise ValueError("test error")

    fp = tmp_path / "boom.py"
    fp.write_text("x=1", encoding="utf-8")

    pipeline = SimplePipeline(parsers={"py": ErrorParser()}, processors={})
    conf = AnalysisConf(repo_path=tmp_path)
    result = pipeline.process(fp, conf)

    assert result.path == fp
    assert result.language == "py"
    assert result.root is None
    assert result.error is not None
    assert "test error" in result.error


def test_process_passes_prefetched_content_to_parser(tmp_path: Path) -> None:
    seen_content: str | None = None

    class ContentParser:
        def parse(self, parser_input: ParserInput) -> CodeNode:
            nonlocal seen_content
            seen_content = parser_input.content
            return CodeNode(
                id="node-1",
                type="module",
                name="content",
                language="py",
                path=str(parser_input.file_path),
                start_line=1,
                end_line=1,
                children=[],
            )

    fp = tmp_path / "content.py"
    contenido = "print('hola')\n"
    fp.write_text(contenido, encoding="utf-8")

    pipeline = SimplePipeline(parsers={"py": ContentParser()}, processors={})
    result = pipeline.process(fp, AnalysisConf(repo_path=tmp_path))

    assert seen_content == contenido
    assert result.content == contenido


def test_process_no_processors(tmp_path: Path) -> None:
    fp = tmp_path / "plain.py"
    fp.write_text("x=2", encoding="utf-8")

    parser = MockParser()
    pipeline = SimplePipeline(parsers={"py": parser}, processors={})
    conf = AnalysisConf(repo_path=tmp_path)
    result = pipeline.process(fp, conf)

    assert result.root is not None
    assert result.root.name == "test"
    assert result.error is None


def test_process_only_applies_processor_for_matching_extension(tmp_path: Path) -> None:
    fp = tmp_path / "plain.py"
    fp.write_text("x=2", encoding="utf-8")

    parser = MockParser()
    processor: Processor[CodeNode] = MockProcessor()

    class WrongProcessor(Processor[CodeNode]):
        def __call__(self, node: CodeNode) -> CodeNode:
            node.tags.append("wrong-processor")
            return node

    pipeline = SimplePipeline(
        parsers={"py": parser},
        processors={"py": processor, "md": WrongProcessor()},
    )
    conf = AnalysisConf(repo_path=tmp_path)

    result = pipeline.process(fp, conf)

    assert result.root is not None
    assert result.root.name == "processed"
    assert result.root.tags == []
