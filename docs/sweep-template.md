# Reactor-cell sweep XML

Define a sweep in XML, then run:

```powershell
conda activate cp2k-env
$env:PYTHONUTF8="1"
python runsweep.py sweeps/headline_cat9_1300K.xml
```

`runsweep.py` loads the file, builds one `CandidateKinetics` mechanism, and
runs every `<cell>` at every listed temperature and reactor. Results go to
`results/sweeps/<name>/run.json` (plus a copy of the input XML). Specs under
`sweeps/` are git-tracked; run products under `results/sweeps/` are not.

The stored example is [`sweeps/headline_cat9_1300K.xml`](../sweeps/headline_cat9_1300K.xml)
— the 1300 K `cat_9` fractional vs 1×1 envelope cells.

## Template

```xml
<?xml version="1.0" encoding="UTF-8"?>
<sweep name="my_sweep">
  <description>Optional note. Printed with the results table.</description>

  <!-- Catalyst name is the Cantera surface suffix: mechanism_<name>.yaml -->
  <catalyst name="cat_9">
    <!-- Preferred: kinetics from a screening CSV row (0-based index). -->
    <screening csv="results/screening/ga_full_database.csv" index="9"/>

    <!-- Or, if there is no CSV, give barriers / adsorption energies in eV.
         Adsorption values set surface enthalpies; they are not barriers. -->
    <!--
    <kinetics E_act="0.43" dE_H="-0.90" dE_CH3="-2.80" dE_C="2.52"/>
    -->
  </catalyst>

  <conditions>
    <!-- Space- or comma-separated. Unit is always K. -->
    <temperatures unit="K">773.15, 1300</temperatures>
    <!-- Subset of: PFR, Fluidized, MMBCR -->
    <reactors>PFR, Fluidized, MMBCR</reactors>
  </conditions>

  <policy>
    <co2_permitted>false</co2_permitted>
    <fluidized_mode>circulating</fluidized_mode>
    <max_regen_cycles>3</max_regen_cycles>
    <regen_mechanism>mechanical</regen_mechanism>
  </policy>

  <!-- Each cell is one (d_p, loading, dispersion). Loading and dispersion
       are area fractions in (0, 1]. a = a_geom × loading × dispersion. -->
  <cells>
    <cell name="fractional">
      <catalyst_particle_mm>0.13</catalyst_particle_mm>
      <metal_loading>0.5</metal_loading>
      <metal_dispersion>0.3</metal_dispersion>
    </cell>
    <cell name="envelope_1x1">
      <catalyst_particle_mm>0.13</catalyst_particle_mm>
      <metal_loading>1.0</metal_loading>
      <metal_dispersion>1.0</metal_dispersion>
    </cell>
  </cells>
</sweep>
```

## Rules

- Root must be `<sweep>` with a non-empty `@name`.
- Catalyst needs `<screening csv= index=>` **or** `<kinetics E_act=>`.
- `metal_loading` and `metal_dispersion` must be in `(0, 1]`. Do not invent BET.
- Γ stays locked at `2.5e-9 mol/cm²` in the mechanism writer. The XML does not
  expose site density.
- MMBCR X at 1300 K near 98.5% is X_eq by construction, not a catalyst rank.
- Relative paths resolve from the repository root.

## Output columns

| Field | Meaning |
|---|---|
| `cell` | `<cell @name>` |
| `X` | Ar-tracer CH₄ conversion |
| `a_1/m` | Active solids area (`a_geom × loading × dispersion`); blank for MMBCR |
| `WHSV` | 1/τ in h⁻¹ (historical name) |
| `dP_bar` | Ergun ΔP; blank for MMBCR |
