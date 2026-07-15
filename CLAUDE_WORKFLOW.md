# EMG™ Claude Engineering Workflow

## Repository

Always work directly inside this repository.

Repository Root:

```
/Users/mak/Documents/GitHub/emg-platform
```

Never create duplicate project folders.

Never create ZIP or TAR archives.

Never create packaged copies of the repository.

---

## Git Rules

Current workflow:

```
main
  ↓
develop
  ↓
feature/*
```

Always work only inside the current feature branch.

Never modify:

- main
- develop

Never:

- commit
- push
- merge
- delete branches

Those actions require user approval.

---

## Engineering Rules

Before starting work:

- verify current branch
- inspect git status
- inspect git diff

Allowed:

- create files
- modify files
- delete obsolete files
- refactor
- add tests
- update documentation

Not allowed:

- architecture redesign
- changing frozen ADRs
- changing completed Sprint scope
- changing approved interfaces

---

## Quality Gates

Before declaring any Sprint complete:

Run:

- Unit Tests
- Integration Tests (where applicable)
- Ruff
- MyPy
- YAML validation

Report:

- tests passed
- lint passed
- type checking passed

---

## Deliverables

At Sprint completion provide:

- modified files list
- created files list
- deleted files list
- git diff summary
- suggested commit message
- suggested Pull Request title
- suggested Pull Request description

Stop and wait for approval.

---

## Forbidden

Never create:

- emg-platform 2
- emg-platform 3
- emg-platform 4
- emg-platform 5
- \*.zip
- \*.tar
- \*.tar.gz

Never duplicate the repository.

Never package the repository.

Work only inside the existing Git repository.

---

## EMG Engineering Principle

Architecture is frozen.

Engineering implements the approved architecture.

Never redesign.

Never invent missing requirements.

If uncertainty exists:

**STOP**

Ask for clarification.

Never guess.
