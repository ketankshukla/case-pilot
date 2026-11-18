import { CaseDesk, DeskHeader } from "./case-desk";
import { readInvestigation, readWorkspace } from "./workspace";

export const dynamic = "force-dynamic";

export default async function Home({ searchParams }: {
  searchParams: Promise<{ case?: string | string[] }>;
}) {
  const [workspace, params] = await Promise.all([readWorkspace(), searchParams]);

  if (!workspace) {
    return (
      <>
        <DeskHeader />
        <main className="page-shell" id="main-content" tabIndex={-1}>
          <section className="panel setup-panel">
            <h1>Case desk unavailable</h1>
            <p>Check the Python service and the shared demo token. The project README covers local setup and the protected Vercel preview.</p>
            <a className="retry-link" href="/">Reload case desk</a>
          </section>
        </main>
      </>
    );
  }

  const selectedCase = workspace.cases.find((item) => item.case_id === params.case)
    ?? workspace.cases.find((item) => item.scenario_id === "SC01")
    ?? workspace.cases[0];
  const investigation = selectedCase ? await readInvestigation(selectedCase.case_id) : null;

  return <CaseDesk workspace={workspace} selectedCase={selectedCase} investigation={investigation} />;
}
