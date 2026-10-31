"use client";

import { AppShell } from "@/components/AppShell";
import { CurriculaWorkbench } from "@/components/CurriculaWorkbench";

// O3 · Liste des curriculums (refonte C3) — super admin. Sélection → /ops/curricula/[frameworkId].
export default function CurriculaPage() {
  return (
    <AppShell>
      <CurriculaWorkbench />
    </AppShell>
  );
}
