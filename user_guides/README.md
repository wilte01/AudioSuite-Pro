# AudioSuite-Pro user documentation

The single documentation index is [docs/index.md](../docs/index.md). It lists
every tool with its launcher and its generated user guide, plus the suite-wide
guides, the CLI reference and the developer documentation.

This folder holds the files, not the index:

| Path | What it is |
|---|---|
| `individual_programs/<tool>/` | one folder per tool: the `.md` user guide source and the `.docx` rendered from it by `utilities/build_user_guides.py` |
| `reference/CLI_Commands_Reference.md` | every `audiosuite` command, its flags, and the headless/scripting section |
| `reference/AudioSuite_Message_Guide.docx` | every user-facing message and what to do about it |
| `suite_overview/` | suite-level material: the logging guide and the new-user presentation |

The security guide moved to [docs/user/security.md](../docs/user/security.md):
encrypted API keys and how to recover them, safe file selection, and what each
security message means. The threat model and reporting route stay in
[SECURITY.md](../SECURITY.md).

Do not add a second hand-written tool list here. The table in
`docs/index.md` is generated from the tool manifest by
`utilities/generate_docs_index.py`, and `tests/test_docs_index.py` fails if it
is stale or if any path it names does not exist.
