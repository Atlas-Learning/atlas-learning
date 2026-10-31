"use client";

import { AppShell } from "@/components/AppShell";
import { CurriculaWorkbench } from "@/components/CurriculaWorkbench";

// O3 · Mapping d'un curriculum (refonte C3) — super admin.
// Référence visuelle : docs/refonte/maquettes/Admin-curriculum.dc.html (reconstruite, pas copiée).
export default function CurriculumPage({ params }: { params: { frameworkId: string } }) {
  return (
    <AppShell>
      <CurriculaWorkbench frameworkId={params.frameworkId} />
    </AppShell>
  );
}
