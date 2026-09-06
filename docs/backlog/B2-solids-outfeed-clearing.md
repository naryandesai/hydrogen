# B2 — Solids produce → outfeed/clear → return

**Acceptance**

- Mechanical / consumable outfeed is the default solids carbon policy. Oxidative regen remains locked unless `co2_permitted=True`.
- Circulating fluidized carbon removal acts **during** integration, not after `net.advance()`. **Shipped:** `simulate_fluidized_bed` substeps and applies `circulating_carbon_removal_rate_1_s` between them. PFR is still discrete regen only.
- Reported metrics distinguish single-pass X from cycle-averaged production.
- Default `max_regen_cycles >= 1` is not sufficient by itself: outfeed restores sites **between** passes; inventory **during** a pass is B1.

**Why**

`max_regen_cycles = 0` was a side effect of blocking CO₂ burnoff. Fixed beds clog and ΔP rises [1,2]. Fluidized / circulating beds exist so carbon-laden particles can leave while stripped particles return [1,2]. Pinilla et al. [4] is the fixed-vs-fluidized **deactivation** comparison (higher X and faster coke in a fixed bed at the same WHSV), not the existence proof for circulating beds.

**Refs**

1. Alves et al., *Renew. Sustain. Energy Rev.* **2021**, *137*, 110465.
2. Sánchez-Bastardo et al., *Ind. Eng. Chem. Res.* **2021**, *60*, 11855–11881.
4. Pinilla et al., *Int. J. Hydrogen Energy* **2012**.
6. Abdollahi et al., *Energies* **2024**, *17*, 290 (melt skim — analogous continuous C takeoff).
