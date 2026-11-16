PROJECT SENTINEL — REDESIGNED UI
================================
This is a separate redesigned source-code copy. The original source ZIP was preserved unchanged.

What changed:
- Light, Stripe-inspired interface (not affiliated with Stripe).
- Three key financial signals prominently displayed.
- Clear impact-based color legend: green = positive; amber = review; red = risk.
- No misleading plus signs in the summary cards.
- Project cost variances expressed as plain English (for example, “Over budget by $70,180”).
- Unconfirmed project budgets show the implications of each budget alternative.
- Reviewer notes, charts, data-quality information, detailed methodology, and supporting evidence
  remain available under “Detailed analysis and evidence”.
- Upload screen, buttons, and chart styling refreshed.
- Date parser correction for forms such as "January 2027" carried into this full source ZIP.

IMPORTANT
- This ZIP does not include any .env file, user API key, saved investigations, or private data.
- If you already run Sentinel on Windows, use the separate "sentinel-UI-UPDATE-WINDOWS.zip" instead.
  Its Apply_UI_Update.bat patches only the frontend in your EXISTING installation and first
  backs up each changed file. It leaves your .env, backend, and saved data unchanged.
- With the Windows update, restart the frontend after applying: press Ctrl+C in the window
  running npm run dev; type npm run dev again; then refresh http://localhost:3000.
- Continue to use the backend command normally, and keep both windows open.
- Security: this is a hackathon prototype. It does not fix existing vulnerable dependencies,
  introduce login/authorization, or validate financial correctness on real businesses.

Affected frontend files:
frontend/app/globals.css
frontend/app/layout.tsx
frontend/components/ui.tsx
frontend/features/outlook/OutlookScreen.tsx
frontend/features/outlook/DetailSections.tsx
frontend/features/outlook/MetricChart.tsx
frontend/features/upload/UploadScreen.tsx
frontend/tailwind.config.js

No additional frontend libraries or dependencies were added.
