# Domain Documentation

This repository uses a single-context domain documentation layout.

## Layout

- Glossary: `GLOSSARY.md` at the repository root
- Architecture Decision Records: `docs/adr/`

## Read before exploration

When exploring the codebase, engineering skills should first read:

- `GLOSSARY.md` at the repository root, when it exists
- Relevant ADRs in `docs/adr/`, when they exist

If these files do not exist, continue silently. Their absence alone is not a reason to recommend creating them in advance.

## Use glossary vocabulary

When naming domain concepts in output, use the terms defined in `GLOSSARY.md`. Do not use synonyms explicitly excluded by the glossary.

If a needed concept is not in the glossary, reconsider whether the project uses that concept. If the gap is real, record it for domain-modeling work.

## Flag ADR conflicts

If output conflicts with an existing ADR, explicitly identify the conflicting ADR instead of silently overriding it.
