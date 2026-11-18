# CasePilot repository instructions

- Work in `E:\casepilot` on Windows and preserve the existing workspace materials.
- Work one checkpoint at a time. Update [the progress log](docs/PROGRESS.md) with the scope, verification results, limitations and next decision. Stop for review at each checkpoint.
- Commit working slices and push them to the private repository. Before every push, run `& '.\scripts\check-before-push.ps1'` from `E:\casepilot` and resolve build or test failures. When the Vercel project is linked, also run its local `vercel build` with the matching project settings before pushing Vercel configuration or runtime changes.
- GitHub is the sole deployment trigger. Never deploy, redeploy, promote, or roll back directly through Vercel. Use Vercel to check the deployment for the pushed commit. Keep the hosted demo protected and read-only until its release and persistence have been reviewed. Complete the acceptance and publication review before making the repository public.
- Use fictional fixtures and local sandbox actions. Keep secrets, personal files, local databases and build outputs outside Git.
- Before pushing, check the staged files and existing commit history for personal documents, credentials and ZIP archives. If private content is already committed or published, stop and tell the product owner before taking corrective action.
