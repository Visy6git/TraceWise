import React from 'react';
import { BrainCircuit, FileOutput } from 'lucide-react';

export type WorkspaceMode = 'learning' | 'generator';

export function WorkspaceModeTabs({ mode, onChange, generatorEnabled }: {
  mode: WorkspaceMode;
  onChange: (mode: WorkspaceMode) => void;
  generatorEnabled: boolean;
}) {
  return (
    <nav className="tw-mode-tabs" aria-label="TraceWise workspace mode">
      <button className={mode === 'learning' ? 'active' : ''} onClick={() => onChange('learning')}>
        <BrainCircuit size={15} /> Learning Workbench
      </button>
      <button className={mode === 'generator' ? 'active' : ''} disabled={!generatorEnabled}
        title={generatorEnabled ? 'Generate Section 16.3 using an approved blueprint' : 'Approve a Stage 3 blueprint to unlock this workspace'}
        onClick={() => onChange('generator')}>
        <FileOutput size={15} /> Section Generator
        {!generatorEnabled && <span className="tw-tab-lock">Locked</span>}
      </button>
    </nav>
  );
}
