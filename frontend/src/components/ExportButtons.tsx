import { useState } from 'react';
import { Download } from 'lucide-react';
import type { ExportFormat } from '../api/endpoints';
import { errorMessage, useToast } from '../lib/toastContext';

const DEFAULT_FORMATS: ExportFormat[] = ['docx', 'pdf', 'pptx'];

export function ExportButtons<F extends string = ExportFormat>({
  onExport,
  formats = DEFAULT_FORMATS as unknown as F[],
  label = 'Export',
}: {
  onExport: (f: F) => Promise<unknown>;
  formats?: F[];
  label?: string;
}) {
  const [busy, setBusy] = useState<F | null>(null);
  const { notify } = useToast();
  return (
    <div className="btn-group" role="group" aria-label={label}>
      {formats.map((f) => (
        <button
          key={f}
          type="button"
          className="btn btn-sm"
          disabled={busy !== null}
          aria-busy={busy === f}
          onClick={async () => {
            setBusy(f);
            try {
              const name = await onExport(f);
              notify(`Downloaded ${typeof name === 'string' ? name : f.toUpperCase()}`);
            } catch (e) {
              notify(`Export failed: ${errorMessage(e)}`, 'error');
            } finally {
              setBusy(null);
            }
          }}
        >
          <Download size={13} aria-hidden />
          {f.toUpperCase()}
        </button>
      ))}
    </div>
  );
}
