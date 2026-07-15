# Attribution

This frontend was bootstrapped from **SADAR — Flight Conformance Monitor** by
**devrup404** (https://huggingface.co/spaces/devrup404/sadar), used under the **MIT
License**.

What we reused from SADAR:

- The React + Vite project shape and the `frontend/src/api.ts` response-interface
  contract (`FlightSummary`, `FlightDetail`, `PathPoint`, `MetricRow`, …), so our serve
  layer can speak the same shapes.
- The lat/lon → SVG projection helper (`src/lib/geo.ts`, adapted from his
  `components/geo.ts`).

What we changed (Direction C "Forensic Dossier", a post-hoc analyst-triage tool):

- The information architecture is rebuilt from a live-controller **Monitor** into a
  retrospective **ranked queue → case file** flow. Our model scores a whole completed
  segment once, so a live scope would be dishonest (see
  `backend/docs/architecture/sadar-merge-design.md` §4.5).
- The visual language is restyled to the "Forensic Dossier" tokens in `/DESIGN.md`
  (paper-cream on dark slate, editorial serif), replacing his green-on-black radar scope.
- The model, data, and serve layer are ours (LSTM-AE, OpenSky-LEMD, `backend/serve/`).

MIT license text from the upstream project is reproduced in `LICENSE.SADAR`.
