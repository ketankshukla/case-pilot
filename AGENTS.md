# CasePilot repository instructions

- Work in `E:\casepilot` on Windows and preserve the existing workspace materials.
- Work one checkpoint at a time. Update [the progress log](docs/PROGRESS.md) with the scope, verification results, limitations and next decision. Stop for review at each checkpoint.
- Commit working slices and push them to GitHub. Before every push, run `& '.\scripts\check-before-push.ps1'` from `E:\casepilot` and resolve build or test failures. For linked Vercel configuration or runtime changes, run local `vercel build` where the host supports packaging. On Windows hosts with the documented symlink restriction, use the production build and verify the Git-triggered Vercel build.
- GitHub is the sole deployment trigger. Never deploy, redeploy, promote, or roll back directly through Vercel. Use Vercel to check the deployment for the pushed commit. Keep the hosted demo protected and read-only until its release and persistence have been reviewed.
- Use fictional fixtures and local sandbox actions. Keep secrets, personal files, local databases and build outputs outside Git.
- Before pushing, check the staged files and existing commit history for personal documents, credentials and ZIP archives. If private content is already committed or published, stop and tell the product owner before taking corrective action.
