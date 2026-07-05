# MOLGANG — Quantum lab (`web/sim/`)

A physics/quantum simulation surface for MOLGANG, and the first step toward a
**quantum-chemistry simulator** (tracked in
[#214](https://github.com/Knitweb/molgang/issues/214)).

`quantum-lab.html` is a molgang-themed launcher that opens two grid-based quantum
simulators by [ray-pH](https://ray-ph.github.io/) and explains the roadmap:

- **Quantum Wavefunction** — [px_qWavefun](https://github.com/ray-pH/px_qWavefun):
  real-time Schrödinger wavefunction visualization (orbital/bonding intuition).
- **Quantum Circuits** — [quantumQ](https://github.com/ray-pH/quantumQ): a puzzle
  game about quantum circuits and logic gates.

## Attribution & licensing (important)

- The **pixelPhysics hub** (<https://github.com/ray-pH/pixelPhysics>) is **MIT**.
- The **individual module repos** (`px_qWavefun`, `quantumQ`) currently carry
  **no license**. Therefore they are **linked/embedded, not vendored** here.
- Vendoring the module source into this repo (roadmap phase 2) requires the
  author's permission or an added OSI license upstream. Do **not** copy their
  source in until that is resolved.

The embedded preview (`<details>` in the page) points at the authors' GitHub
Pages build. Those pages 301-redirect to an `http` custom domain, so on an
`https` deployment the browser blocks the frame as mixed content — the page
therefore leads with an **“Open simulator ↗”** link that always works, and the
embed is a best-effort progressive enhancement.

## Roadmap toward a quantum-chemistry simulator

1. **Embed** the pixelPhysics quantum sims (this page).
2. **Wire** `knitwebs/chemistry` term-nodes → sim inputs (elements, bonds,
   reaction conditions from #109).
3. **Compute** electronic structure server-side (`RDKit` + `PySCF`).
4. **Quantum** path via `Qiskit Nature` / `OpenFermion` / `PennyLane`; results
   woven back as Knits and pulse-verified.

In-browser rendering candidates for later phases: **3Dmol.js**, **RDKit.js**.
