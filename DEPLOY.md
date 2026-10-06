# Go-live checklist

Run from the repo root. Nothing here is automated: you run the final step.

1. Build the clean `public/` dir: `py build_site.py`
2. Safety check (must print `OK`, exits 1 on any problem): `py predeploy_check.py`
3. Preview locally: `py -m http.server -d public`, then open
   http://localhost:8000/ (new site) and http://localhost:8000/classic/ (old page).
   Check that grants load and the cross-links work.
4. Deploy: `cd public; npx vercel --prod`
5. Verify the live URL: `/`, `/classic/`, `/report.html` and `/grants.json` all load; no `.env`/`.py` reachable.
6. Rollback if wrong: `npx vercel rollback` (or Vercel dashboard > Deployments >
   previous deployment > Promote to Production).

Note: `weekly.py` deploys via `grants_lib.deploy()`, which runs build + check itself and aborts on problems.
