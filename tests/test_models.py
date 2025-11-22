"""Tests for Pydantic models."""

import pytest
from datetime import datetime
from pathlib import Path

from alignment_map.models import (
    LineRange,
    Block,
    FileMapping,
    AlignmentMap,
    OverlapError,
    BlockNotFoundError,
)


class TestLineRange:
    def test_parse_from_string(self):
        lr = LineRange.model_validate("10-50")
        assert lr.start == 10
        assert lr.end == 50

    def test_parse_from_dict(self):
        lr = LineRange.model_validate({"start": 5, "end": 15})
        assert lr.start == 5
        assert lr.end == 15

    def test_from_string_method(self):
        lr = LineRange.from_string("20-30")
        assert lr.start == 20
        assert lr.end == 30

    def test_invalid_range(self):
        with pytest.raises(ValueError):
            LineRange(start=50, end=10)

    def test_invalid_format(self):
        with pytest.raises(ValueError):
            LineRange.model_validate("invalid")

    def test_contains(self):
        lr = LineRange(start=10, end=20)
        assert lr.contains(10)
        assert lr.contains(15)
        assert lr.contains(20)
        assert not lr.contains(5)
        assert not lr.contains(25)

    def test_overlaps(self):
        lr1 = LineRange(start=10, end=20)
        lr2 = LineRange(start=15, end=25)
        lr3 = LineRange(start=25, end=35)
        lr4 = LineRange(start=1, end=9)

        assert lr1.overlaps(lr2)
        assert lr2.overlaps(lr1)
        assert not lr1.overlaps(lr3)
        assert not lr1.overlaps(lr4)

    def test_adjacent_ranges_do_not_overlap(self):
        lr1 = LineRange(start=10, end=20)
        lr2 = LineRange(start=21, end=30)
        assert not lr1.overlaps(lr2)

    def test_str_representation(self):
        lr = LineRange(start=10, end=50)
        assert str(lr) == "10-50"


class TestBlock:
    def test_overlaps_with(self):
        b1 = Block(name="A", lines=LineRange(start=1, end=10))
        b2 = Block(name="B", lines=LineRange(start=5, end=15))
        b3 = Block(name="C", lines=LineRange(start=20, end=30))

        assert b1.overlaps_with(b2)
        assert b2.overlaps_with(b1)
        assert not b1.overlaps_with(b3)

    def test_contains_line(self):
        block = Block(name="Test", lines=LineRange(start=10, end=20))
        assert block.contains_line(10)
        assert block.contains_line(15)
        assert block.contains_line(20)
        assert not block.contains_line(5)
        assert not block.contains_line(25)

    def test_block_with_aligned_with(self):
        block = Block(
            name="Test",
            lines=LineRange(start=1, end=10),
            aligned_with=["docs/README.md#section"]
        )
        assert len(block.aligned_with) == 1
        assert "docs/README.md#section" in block.aligned_with

    def test_block_with_datetime(self):
        now = datetime.now()
        block = Block(
            name="Test",
            lines=LineRange(start=1, end=10),
            last_updated=now,
            last_update_comment="Initial"
        )
        assert block.last_updated == now
        assert block.last_update_comment == "Initial"


class TestFileMapping:
    def test_add_block_success(self):
        fm = FileMapping(file=Path("test.py"), blocks=[])
        block = Block(name="A", lines=LineRange(start=1, end=10))
        fm.add_block(block)
        assert len(fm.blocks) == 1

    def test_add_block_overlap_error(self):
        fm = FileMapping(
            file=Path("test.py"),
            blocks=[Block(name="A", lines=LineRange(start=1, end=10))]
        )
        with pytest.raises(OverlapError):
            fm.add_block(Block(name="B", lines=LineRange(start=5, end=15)))

    def test_add_multiple_blocks_no_overlap(self):
        fm = FileMapping(file=Path("test.py"), blocks=[])
        fm.add_block(Block(name="A", lines=LineRange(start=1, end=10)))
        fm.add_block(Block(name="B", lines=LineRange(start=20, end=30)))
        assert len(fm.blocks) == 2

    def test_get_block(self):
        block = Block(name="A", lines=LineRange(start=1, end=10))
        fm = FileMapping(file=Path("test.py"), blocks=[block])
        assert fm.get_block("A") == block
        assert fm.get_block("B") is None

    def test_find_block_for_line(self):
        block = Block(name="A", lines=LineRange(start=10, end=20))
        fm = FileMapping(file=Path("test.py"), blocks=[block])
        assert fm.find_block_for_line(15) == block
        assert fm.find_block_for_line(5) is None

    def test_update_block_lines(self):
        fm = FileMapping(
            file=Path("test.py"),
            blocks=[Block(name="A", lines=LineRange(start=1, end=10))]
        )
        fm.update_block_lines("A", LineRange(start=5, end=15), "Moved")
        assert fm.blocks[0].lines.start == 5
        assert fm.blocks[0].lines.end == 15
        assert fm.blocks[0].last_update_comment == "Moved"
        assert fm.blocks[0].last_updated is not None

    def test_update_block_lines_not_found(self):
        fm = FileMapping(file=Path("test.py"), blocks=[])
        with pytest.raises(BlockNotFoundError):
            fm.update_block_lines("A", LineRange(start=1, end=10))

    def test_update_block_lines_overlap_error(self):
        fm = FileMapping(
            file=Path("test.py"),
            blocks=[
                Block(name="A", lines=LineRange(start=1, end=10)),
                Block(name="B", lines=LineRange(start=20, end=30)),
            ]
        )
        with pytest.raises(OverlapError):
            fm.update_block_lines("A", LineRange(start=1, end=25))

    def test_remove_block(self):
        fm = FileMapping(
            file=Path("test.py"),
            blocks=[Block(name="A", lines=LineRange(start=1, end=10))]
        )
        removed = fm.remove_block("A")
        assert removed.name == "A"
        assert len(fm.blocks) == 0

    def test_remove_block_not_found(self):
        fm = FileMapping(file=Path("test.py"), blocks=[])
        with pytest.raises(BlockNotFoundError):
            fm.remove_block("A")

    def test_check_overlaps(self):
        fm = FileMapping(
            file=Path("test.py"),
            blocks=[
                Block(name="A", lines=LineRange(start=1, end=15)),
                Block(name="B", lines=LineRange(start=10, end=20)),
                Block(name="C", lines=LineRange(start=30, end=40)),
            ]
        )
        overlaps = fm.check_overlaps()
        assert len(overlaps) == 1
        assert overlaps[0][0].name == "A"
        assert overlaps[0][1].name == "B"


class TestAlignmentMap:
    def test_load_and_save(self, temp_git_repo: Path):
        # Create a map file
        content = """version: 1
hierarchy:
  requires_human: []
  technical: []
mappings: []
"""
        map_path = temp_git_repo / ".alignment-map.yaml"
        map_path.write_text(content)

        # Load it
        am = AlignmentMap.load(map_path)
        assert am.version == 1
        assert am._project_root == temp_git_repo

        # Modify and save
        am.mappings.append(
            FileMapping(
                file=Path("test.py"),
                blocks=[Block(name="Test", lines=LineRange(start=1, end=10))]
            )
        )
        am.save(map_path)

        # Reload and verify
        am2 = AlignmentMap.load(map_path)
        assert len(am2.mappings) == 1

    def test_load_with_blocks(self, temp_git_repo: Path):
        content = """version: 1
hierarchy:
  requires_human:
    - docs/IDENTITY.md
  technical:
    - docs/**/*.md
mappings:
  - file: src/module.py
    blocks:
      - name: MyClass
        lines: 1-20
        last_updated: 2024-01-15T10:00:00
        aligned_with:
          - docs/ARCHITECTURE.md#my-class
"""
        map_path = temp_git_repo / ".alignment-map.yaml"
        map_path.write_text(content)

        am = AlignmentMap.load(map_path)
        assert am.version == 1
        assert len(am.mappings) == 1
        assert am.mappings[0].file == Path("src/module.py")
        assert len(am.mappings[0].blocks) == 1
        assert am.mappings[0].blocks[0].name == "MyClass"
        assert am.mappings[0].blocks[0].lines.start == 1
        assert am.mappings[0].blocks[0].lines.end == 20

    def test_get_file_mapping(self):
        am = AlignmentMap(
            version=1,
            mappings=[
                FileMapping(
                    file=Path("a.py"),
                    blocks=[Block(name="A", lines=LineRange(start=1, end=10))]
                )
            ]
        )
        assert am.get_file_mapping(Path("a.py")) is not None
        assert am.get_file_mapping(Path("b.py")) is None

    def test_is_human_required(self):
        am = AlignmentMap(
            version=1,
            hierarchy={"requires_human": ["docs/IDENTITY.md", "docs/DESIGN*.md"], "technical": []},
            mappings=[]
        )
        assert am.is_human_required("docs/IDENTITY.md")
        assert am.is_human_required("docs/DESIGN-principles.md")
        assert not am.is_human_required("docs/ARCHITECTURE.md")

    def test_get_all_references_to(self):
        am = AlignmentMap(
            version=1,
            mappings=[
                FileMapping(
                    file=Path("a.py"),
                    blocks=[
                        Block(
                            name="A",
                            lines=LineRange(start=1, end=10),
                            aligned_with=["docs/foo.md"]
                        )
                    ]
                ),
                FileMapping(
                    file=Path("b.py"),
                    blocks=[
                        Block(
                            name="B",
                            lines=LineRange(start=1, end=10),
                            aligned_with=["docs/foo.md#section"]
                        )
                    ]
                )
            ]
        )

        refs = am.get_all_references_to("docs/foo.md")
        assert len(refs) == 2

    def test_add_file_mapping(self):
        am = AlignmentMap(version=1, mappings=[])
        fm = FileMapping(
            file=Path("test.py"),
            blocks=[Block(name="A", lines=LineRange(start=1, end=10))]
        )
        am.add_file_mapping(fm)
        assert len(am.mappings) == 1

    def test_add_file_mapping_duplicate(self):
        am = AlignmentMap(
            version=1,
            mappings=[
                FileMapping(file=Path("test.py"), blocks=[])
            ]
        )
        with pytest.raises(ValueError):
            am.add_file_mapping(FileMapping(file=Path("test.py"), blocks=[]))

    def test_remove_file_mapping(self):
        am = AlignmentMap(
            version=1,
            mappings=[
                FileMapping(
                    file=Path("a.py"),
                    blocks=[Block(name="A", lines=LineRange(start=1, end=10))]
                )
            ]
        )
        removed, refs = am.remove_file_mapping(Path("a.py"))
        assert removed.file == Path("a.py")
        assert len(am.mappings) == 0

    def test_remove_file_mapping_not_found(self):
        am = AlignmentMap(version=1, mappings=[])
        with pytest.raises(ValueError):
            am.remove_file_mapping(Path("nonexistent.py"))

    def test_project_root_not_set(self):
        am = AlignmentMap(version=1, mappings=[])
        with pytest.raises(ValueError):
            _ = am.project_root

    def test_set_project_root(self, temp_git_repo: Path):
        am = AlignmentMap(version=1, mappings=[])
        am.set_project_root(temp_git_repo)
        assert am._project_root == temp_git_repo
        assert am.project_root == temp_git_repo

    def test_lint_missing_file(self, temp_git_repo: Path):
        content = """version: 1
hierarchy:
  requires_human: []
  technical: []
mappings:
  - file: nonexistent.py
    blocks:
      - name: Test
        lines: 1-10
        aligned_with: []
"""
        map_path = temp_git_repo / ".alignment-map.yaml"
        map_path.write_text(content)

        am = AlignmentMap.load(map_path)
        issues = am.lint()
        assert len(issues) == 1
        assert issues[0]["issue"] == "missing_file"

    def test_lint_invalid_lines(self, temp_git_repo: Path):
        # Create a short file
        (temp_git_repo / "short.py").write_text("line 1\nline 2\n")

        content = """version: 1
hierarchy:
  requires_human: []
  technical: []
mappings:
  - file: short.py
    blocks:
      - name: Test
        lines: 1-100
        aligned_with: []
"""
        map_path = temp_git_repo / ".alignment-map.yaml"
        map_path.write_text(content)

        am = AlignmentMap.load(map_path)
        issues = am.lint()
        assert len(issues) == 1
        assert issues[0]["issue"] == "invalid_lines"
