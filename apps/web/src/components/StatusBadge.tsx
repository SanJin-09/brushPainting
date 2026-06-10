import React from "react";
import type { ImageStatus, JobStatus } from "../lib/types";

type Props = { status: ImageStatus | JobStatus };

export default function StatusBadge({ status }: Props) {
  return <span className={`badge badge-${status}`}>{status}</span>;
}
