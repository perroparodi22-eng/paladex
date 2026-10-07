import { requireAdmin } from "@/server/auth/guard";
import { AdminNav } from "@/components/admin/AdminNav";

export default async function PanelLayout({ children }: { children: React.ReactNode }) {
  await requireAdmin();
  return (
    <div className="lg:grid lg:min-h-dvh lg:grid-cols-[232px_minmax(0,1fr)]">
      <AdminNav />
      <div className="min-w-0 px-4 pb-24 pt-6 sm:px-6 lg:px-10 lg:pt-8">{children}</div>
    </div>
  );
}
