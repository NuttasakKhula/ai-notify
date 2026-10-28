# GitHub upload

Use this directory's contents as the repository root. Do not upload the original working project or its parent, which may contain live credentials and backups.

Create an empty GitHub repository, then run here:

```sh
git init -b main
git add .
git status --short
git commit -m "Initial sanitized Ai Notify source"
git remote add origin https://github.com/YOUR_ACCOUNT/YOUR_REPOSITORY.git
git push -u origin main
```

Replace the remote URL. Review staged files: no live environment files, keys, database dumps, logs, dependencies or build outputs. Include example templates.

Alternatively extract the release ZIP and upload the project contents through GitHub's web interface. Choose visibility deliberately. No project-wide open-source license is granted; the owner can add one when ready to grant reuse rights.
