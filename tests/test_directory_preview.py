from glue.bio_inspector import inspect_bio_file


def make_directory(tmp_path, files):
    directory = tmp_path / "reports"
    directory.mkdir()
    for name in files:
        (directory / name).write_text("x")
    return directory


def test_directory_preview_zero(tmp_path):
    directory = make_directory(tmp_path, [f"f{i}.txt" for i in range(10)])
    result = inspect_bio_file(str(directory), preview_n=0)
    assert result.valid and result.format == "DIRECTORY"
    assert result.preview == []
    assert result.stats["sampled_entries"] == 10


def test_directory_preview_above_five(tmp_path):
    directory = make_directory(tmp_path, [f"f{i}.txt" for i in range(10)])
    result = inspect_bio_file(str(directory), preview_n=8)
    assert result.valid
    assert len(result.preview) == 8
    assert result.preview == sorted(f"f{i}.txt" for i in range(10))[:8]
    assert result.stats["sampled_entries"] == 10


def test_directory_preview_bounded_scan(tmp_path):
    directory = make_directory(tmp_path, [f"f{i}.txt" for i in range(60)])
    result = inspect_bio_file(str(directory), preview_n=100)
    assert len(result.preview) == 50
    assert result.stats["sampled_entries"] == 50


def test_directory_preview_below_entry_count(tmp_path):
    directory = make_directory(tmp_path, ["a.html", "b.html"])
    result = inspect_bio_file(str(directory), preview_n=5)
    assert result.preview == ["a.html", "b.html"]
    assert result.stats["sampled_entries"] == 2
