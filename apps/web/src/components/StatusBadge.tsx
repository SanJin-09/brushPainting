import React from "react";

type Props = { status: string };

export default function StatusBadge({ status }: Props) {
  return <span className={`badge badge-${status.toLowerCase()}`}>{status}</span>;
}
