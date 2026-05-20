"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import AddChartModal from "./AddChartModal";

export default function AddChartFab() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        className="add-chart-fab"
        onClick={() => setOpen(true)}
        title="Add chart manually"
        aria-label="Add chart"
      >
        <Plus size={20} strokeWidth={2.5} />
      </button>
      <AddChartModal open={open} onClose={() => setOpen(false)} />
    </>
  );
}
