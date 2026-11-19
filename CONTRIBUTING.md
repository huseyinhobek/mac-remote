# Contributing

Thanks for helping. Issues and pull requests are welcome. Every pull request is reviewed by the maintainer before it is merged.

## Ground rules

These keep the project small and safe, and every change is reviewed against them.

- **The AI only picks a tool.** It never writes commands, scripts or file paths that run as-is. New tools take typed arguments that the code validates.
- **No shell.** Run programs with argument lists. Never use `shell=True` or string-built commands with user input.
- **Ask before anything that sends, deletes or restarts.** Use the confirm button for actions like that.
- **One dependency.** Use the standard library or macOS's own tools. A new dependency needs a strong reason.
- **Nothing personal in the repo.** Paths, ids and tokens belong in `config.toml` and `.env`, which git ignores.

## Workflow

1. Fork the repository and create a branch.
2. Make your change and add a check to `test_mac_remote.py` for any new logic.
3. Run `python test_mac_remote.py`.
4. Open a pull request and describe how you tested it on a real Mac.

For larger changes, open an issue first so we can agree on the approach.
