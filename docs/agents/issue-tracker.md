# Issue Tracker: GitHub

Issues and specifications for this repository live in GitHub Issues. Use the `gh` CLI for all issue operations.

## Conventions

- **Create an issue**: `gh issue create --title "..." --body "..."`
- **Read an issue**: `gh issue view <number> --json number,title,body,labels,comments`
- **List issues**: use `gh issue list`, filtering with `--label` and `--state` as appropriate.
- **Comment on an issue**: `gh issue comment <number> --body "..."`
- **Apply or remove labels**: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **Close an issue**: `gh issue close <number> --comment "..."`

The repository is inferred from the Git remote as `suhongbo2017/alpha-radar`.

## Pull Requests as a Triage Surface

**No.** Pull requests are not treated as a triage request surface by this configuration.

## When a skill says to publish to the issue tracker

Create a GitHub issue.

## When a skill says to fetch a related ticket

Use `gh issue view` or `gh issue list` to retrieve related issues.
