import { InvestigationView } from "@/features/InvestigationView";

export default function InvestigationPage({ params }: { params: { id: string } }) {
  return <InvestigationView id={params.id} />;
}
