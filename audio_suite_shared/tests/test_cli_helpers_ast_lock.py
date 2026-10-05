class TestCliHelpersArgparseCleanup:
    """AST lock: prevent reintroduction of removed dead argparse names."""

    def test_dead_argparse_names_absent(self) -> None:
        import ast
        import inspect

        from audio_suite_shared import cli_helpers

        source = inspect.getsourcefile(cli_helpers) or ""
        with open(source, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=source)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        dead = {
            "parse_cli_args",
            "build_arg_parser",
            "stage_flags_from_args",
            "get_default_values",
            "dump_defaults",
            "configure_logging",
        }
        assert dead.isdisjoint(names)
