import { notFound } from "next/navigation";
import Workspace from "../components/workspace";

export default async function Page({
  params,
}: {
  params: Promise<{ section: string }>;
}) {
  const { section } = await params;
  if (
    ![
      "dashboard",
      "discovery",
      "topology",
      "logs",
      "reports",
      "clients",
      "settings",
    ].includes(section)
  )
    notFound();
  return <Workspace section={section} />;
}
