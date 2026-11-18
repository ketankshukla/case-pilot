import { CaseDesk, DeskHeader } from "./case-desk";
import { readWorkspace } from "./workspace";

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
            <p>Start the local Python service and check that both services use the same demo token. The project README has the setup commands.</p>
            <a className="retry-link" href="/">Reload case desk</a>
          </section>
        </main>
      </>
    );
  }

  const currentCase = workspace.cases.find((item) => item.case_id === params.case)
    ?? workspace.cases.find((item) => item.scenario_id === "SC01")
    ?? workspace.cases[0];

  return <CaseDesk workspace={workspace} currentCase={currentCase} />;
}
