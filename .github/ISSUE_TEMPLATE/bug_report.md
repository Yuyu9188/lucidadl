---
name: Bug report
about: Something doesn't work as expected
title: "[bug] "
labels: bug
---

**What happened**
A clear description of the bug.

**Steps to reproduce**
The exact command(s), e.g.:
```
lucida album "Artist - Album" --to mp3 --bitrate 320k -j 8
```

**Expected vs actual**
What you expected, and what happened instead.

**Logs**
Relevant output, and the tail of the run log (`lucida config` prints its path; it lives
in the app-data dir). Please redact anything private.

**Environment**
- OS:
- Python version (`python --version`):
- lucidadl version (`lucida --version`):
- Output of `lucida doctor`:

**Checklist**
- [ ] I ran `lucida setup` successfully at least once.
- [ ] `playwright install chromium` has been run.
- [ ] `mutagen` is installed in the same Python that runs `lucida` (else files go to "Unknown").
