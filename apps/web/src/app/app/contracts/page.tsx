import { ApplyContractButton } from "@/components/apply-contract-button";
import { ContractUpload } from "@/components/contract-upload";
import { serverApi } from "@/lib/api/server";
import type { ContractRecord, Customer, ItemList } from "@/lib/api/types";

export const instant = false;

export default async function ContractsPage() {
  const [contracts, customers] = await Promise.all([
    serverApi<ItemList<ContractRecord>>("/api/v1/contracts"),
    serverApi<ItemList<Customer>>("/api/v1/customers"),
  ]);
  return (
    <section className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Contracts</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          This extraction is not legally verified. The extracted fields cannot be edited in place.
          The supported review action is to create a project from an extraction that has no blocking findings.
        </p>
      </div>
      <ContractUpload customers={customers?.items ?? []} />
      <ul className="flex flex-col gap-3">
        {(contracts?.items ?? []).map((contract) => (
          <li key={contract.id} className="flex flex-col gap-3 rounded-xl border px-4 py-3">
            <div>
              <p className="font-medium">{contract.filename}</p>
              <p className="text-sm text-muted-foreground">
                {contract.provider_label} · {contract.status}
              </p>
              <p className="text-sm text-muted-foreground">{contract.disclaimer}</p>
            </div>
            <dl className="grid gap-2 text-sm sm:grid-cols-2">
              <div>
                <dt className="text-muted-foreground">Parties</dt>
                <dd>{(contract.extraction.parties ?? []).join("; ") || "Not read"}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Payment total</dt>
                <dd>
                  {contract.extraction.currency_code ?? "Currency not read"}{" "}
                  {contract.extraction.total_amount ?? "no total"}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Scope</dt>
                <dd>{contract.extraction.scope || "Not read"}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Deliverables</dt>
                <dd>{contract.extraction.deliverables || "Not read"}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Acceptance</dt>
                <dd>{contract.extraction.acceptance_conditions || "Not read"}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Contractor obligations</dt>
                <dd>{contract.extraction.contractor_obligations || "Not read"}</dd>
              </div>
            </dl>
            {(contract.extraction.milestones ?? []).length > 0 ? (
              <ul className="text-sm">
                {(contract.extraction.milestones ?? []).map((milestone) => (
                  <li key={`${milestone.name}-${milestone.due_on}`}>
                    {milestone.name}: {milestone.currency_code} {milestone.amount} due {milestone.due_on}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">No payment milestones were read.</p>
            )}
            {contract.findings.length > 0 ? (
              <ul className="text-sm text-muted-foreground">
                {contract.findings.map((finding) => (
                  <li key={finding}>{finding}</li>
                ))}
              </ul>
            ) : null}
            <ApplyContractButton
              contractId={contract.id}
              findings={contract.findings}
              projectId={contract.project_id}
              customers={customers?.items ?? []}
            />
          </li>
        ))}
      </ul>
    </section>
  );
}
