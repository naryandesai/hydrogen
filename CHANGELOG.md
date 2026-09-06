# Changelog

## [Unreleased]

### 2026-09-06 — Solids X mole balance, wired melt flotation

PFR/fluidized `CH4_conversion` is the Ar-tracer ratio `1 - (x_CH4/x_Ar)/(x_CH4,0/x_Ar,0)`. The H2 mole-balance is exact only for CH4/H2/inert (equilibrium check). The solids YAML has an active C2 chain, so that denominator deflates bed X in the low-Da regime. `1 - x_CH4/x_CH4,0` remains `CH4_mole_fraction_drop` only.

PFR/fluidized disable the Cantera energy equation (`thermal_mode=isothermal_energy_disabled`) so they match isothermal MMBCR instead of running adiabatic and self-quenching. Exit T is reported. Melt wall-loss / interface sag is still a separate duty account, not “no energy balance.”

`mmbcr_carbon_removal_rate_1_s` is a flotation frequency. Production default is `None` = unconstrained (`η = 1`); the knob is wired but off. `0` fouls the interface. Detachment ablation labels PFR as not wired (discrete regen only). Circulating fluidized removal runs during integrate substeps (B2 slice).

Melt `k0 ≤ 1` m/s is a **guardrail** against inventing Da, not a physical bound like loading ≤ 1. Scorecard `judge_catalyst` is set only when a named judge is present; otherwise `headline_catalyst` is the best non-H-parked row. PFR `theta_C_axial` is labeled time-on-stream. MMBCR no longer reports fake C2 / `solid_C_selectivity=1`.

### 2026-09-06 — Phase 2 carbon model, phase admissibility, MMBCR rate form

Shipped working-tree changes. Durable rule: [ADR 0001](docs/adr/0001-pyrolysis-phase-admissibility.md). Open work: issues B1–B5.

**Admissibility.** `phase_stable_at_application_T` rejects encoded phases that do not exist at pyrolysis T. First entry MetalHydride; also MOF, COF, MXene, Perovskite. Filter is **candidate selection only** — coverage certificate / 21.1B denominator / 14-class enumeration unchanged. MetalHydride is exempt from reserved validation quotas on both applications. MOF/COF/MXene/Perovskite are exempt from reserved **pyrolysis** validation slots (they still earn PEMFC quota).

**Carbon / mechanisms.** Gas-phase `C_graphite` removed. Condensed `C(gr)` (`fixed-stoichiometry`). Surface path ends at `C_s`. `co2_permitted=False`. Mechanical PFR outfeed default `max_regen_cycles=3`. H₂ selectivity gate off by default.

**Coking / surrogate.** MoltenMetal `coking_index` is explicit NaN. Missing key fails closed. Surrogate coking head uses masked MSE (no `fillna(0)`).

**MMBCR.** Rate is `k(E_act,T) × a_bubble × (X_eq − X)` with flotation (no Langmuir lattice). This **cannot exceed X_eq** and **reaches X_eq for large k·a·τ by construction**. The 0.1 eV → X = 0.985 result is a sanity check on k0 and area, not kinetic closure. **Closure: sanity-checked on MMBCR; pending on PFR and fluidized** (B5). Cross-reactor comparison now systematically favors MMBCR; within MMBCR ranking saturates once Da is large.

**Coking descriptor vs hydrides.** MetalHydride remains in `SLAB_COKING_INDEX_CLASSES` (slab exists). That is not pyrolysis admissibility.
