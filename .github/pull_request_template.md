## What and why

<!-- What does this change, and what problem does it solve? Link issues with "Fixes #123". -->

## How it was tested

<!-- Commands you ran and anything you checked by hand (themes, mobile width, keyboard). -->

- [ ] `npm run ci` passes (web build, ruff, mypy, migration check, pytest)
- [ ] `npm run typecheck:web` passes
- [ ] New behaviour has tests; providers are mocked and tests don't use the network

## Checklist

- [ ] No keys, `api/.env` contents, databases, generated media or private project content
- [ ] Nothing paid starts without an explicit user action
- [ ] Models changed? Migration added (`npm run manage -- makemigrations`)
- [ ] Commands, settings or endpoints changed? README updated
- [ ] New bundled assets? Source and licence added to `THIRD_PARTY_NOTICES.md`
