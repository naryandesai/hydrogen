# B5 — Do not send Phase 2 conversion to DFT until solids closure passes

**Type:** Gate. Blocks the DFT / Phase 3 milestone.

**Acceptance**

- Phase 2 `CH4_conversion` is not used to pick DFT candidates until a fast catalyst (E_act ≈ 0.1 eV, modest H desorption) approaches tabulated X_eq on **PFR and fluidized**, where the Langmuir surface is actually integrated.
- MMBCR 0.1 eV → X_eq is **not** this gate. That form relaxes to X_eq by construction (B3).
- Header language: **closure sanity-checked on MMBCR; pending on PFR and fluidized.**
- Observed counterexample to ranking: 0.01 eV CH₄ + |dE_H| ≈ 5 eV → ~0.02% X (H parked as H_s) on the old solids path.

**Why**

Until Da is not ≪ 1 on the resolved surface reactors, Phase 2 X ranks inventory and H-blocking, not catalysts.
