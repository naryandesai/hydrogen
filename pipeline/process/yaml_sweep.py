"""Load a reactor-cell sweep from YAML and run it.

Input specs live under sweeps/*.yaml (git-tracked). Run products go to
results/sweeps/<name>/ (gitignored). See docs/sweep-template.md.

This is not a Cantera mechanism file. Root keys are name / catalyst /
conditions / cells. Mechanism YAML lives under mechanisms/.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

from pipeline.common.utils import BASE_DIR, SWEEPS_DIR, setup_logger

logger = setup_logger('yaml_sweep', 'reactor/yaml_sweep.log')

ALLOWED_REACTORS = ('PFR', 'Fluidized', 'MMBCR')
DEFAULT_POLICY = {
    'co2_permitted': False,
    'fluidized_mode': 'circulating',
    'max_regen_cycles': 3,
    'regen_mechanism': 'mechanical',
}


@dataclass
class SweepCell:
    name: str
    catalyst_particle_mm: float
    metal_loading: float
    metal_dispersion: float


@dataclass
class SweepJob:
    name: str
    description: str
    catalyst_name: str
    temperatures_K: List[float]
    reactor_types: List[str]
    policy: dict
    cells: List[SweepCell]
    source_file: str
    screening_csv: Optional[str] = None
    screening_index: Optional[int] = None
    kinetics: dict = field(default_factory=dict)


def _require_mapping(value: Any, label: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f'{label} must be a mapping')
    return value


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ('true', '1', 'yes'):
            return True
        if text in ('false', '0', 'no'):
            return False
    raise ValueError(f'expected boolean, got {value!r}')


def _as_float_list(value: Any, label: str) -> List[float]:
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, str):
        parts = [p for p in value.replace(',', ' ').split() if p]
        if not parts:
            raise ValueError(f'{label}: expected at least one number')
        return [float(p) for p in parts]
    if isinstance(value, list):
        if not value:
            raise ValueError(f'{label}: expected at least one number')
        return [float(v) for v in value]
    raise ValueError(f'{label} must be a number or a list of numbers')


def _as_name_list(value: Any, label: str) -> List[str]:
    if isinstance(value, str):
        names = [p for p in value.replace(',', ' ').split() if p]
    elif isinstance(value, list):
        names = [str(v).strip() for v in value if str(v).strip()]
    else:
        raise ValueError(f'{label} must be a string or a list of names')
    if not names:
        raise ValueError(f'{label}: expected at least one name')
    return names


def _resolve(path_text: str) -> Path:
    path = Path(path_text)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def _load_yaml(path: Path) -> dict:
    text = path.read_text(encoding='utf-8')
    try:
        from ruamel.yaml import YAML
        data = YAML(typ='safe', pure=True).load(text)
    except ImportError:
        try:
            import yaml
        except ImportError as exc:
            raise ImportError(
                'sweep specs need ruamel.yaml (Cantera) or PyYAML') from exc
        data = yaml.safe_load(text)
    return _require_mapping(data, 'sweep YAML')


def parse_sweep(yaml_path: Path) -> SweepJob:
    """Parse one sweep spec. Does not touch Cantera or write mechanisms."""
    yaml_path = Path(yaml_path)
    if yaml_path.suffix.lower() == '.xml':
        raise ValueError(
            'sweep specs are YAML; convert the file and see docs/sweep-template.md')
    if not yaml_path.is_file():
        raise FileNotFoundError(f'no such sweep file: {yaml_path}')
    root = _load_yaml(yaml_path)
    name = str(root.get('name') or yaml_path.stem).strip()
    if not name:
        raise ValueError('sweep name is required')

    catalyst = _require_mapping(root.get('catalyst'), 'catalyst')
    catalyst_name = str(catalyst.get('name') or name).strip()
    screening = catalyst.get('screening')
    kinetics_raw = catalyst.get('kinetics')
    screening_csv = None
    screening_index = None
    kinetics = {}
    if screening is not None:
        screening = _require_mapping(screening, 'catalyst.screening')
        csv_text = screening.get('csv')
        index_val = screening.get('index')
        if not csv_text or index_val is None:
            raise ValueError('catalyst.screening requires csv and index')
        screening_csv = str(csv_text)
        screening_index = int(index_val)
    if kinetics_raw is not None:
        kinetics_raw = _require_mapping(kinetics_raw, 'catalyst.kinetics')
        for key in ('E_act', 'dE_H', 'dE_CH3', 'dE_C'):
            raw = kinetics_raw.get(key)
            if raw is not None and raw != '':
                kinetics[key] = float(raw)
    if screening is None and 'E_act' not in kinetics:
        raise ValueError(
            'catalyst needs screening: {csv, index} or kinetics: {E_act}')

    conditions = _require_mapping(root.get('conditions'), 'conditions')
    if 'temperatures_K' in conditions:
        temperatures = _as_float_list(conditions['temperatures_K'], 'temperatures_K')
    elif 'temperatures' in conditions:
        temperatures = _as_float_list(conditions['temperatures'], 'temperatures')
    else:
        raise ValueError('conditions.temperatures_K is required')
    reactor_types = _as_name_list(conditions.get('reactors'), 'reactors')
    unknown = [r for r in reactor_types if r not in ALLOWED_REACTORS]
    if unknown:
        raise ValueError(f'unknown reactor type(s) {unknown}; allowed {ALLOWED_REACTORS}')

    policy = dict(DEFAULT_POLICY)
    policy_raw = root.get('policy')
    if policy_raw is not None:
        policy_raw = _require_mapping(policy_raw, 'policy')
        if 'co2_permitted' in policy_raw:
            policy['co2_permitted'] = _as_bool(policy_raw['co2_permitted'])
        if 'fluidized_mode' in policy_raw:
            policy['fluidized_mode'] = str(policy_raw['fluidized_mode']).strip()
        if 'max_regen_cycles' in policy_raw:
            policy['max_regen_cycles'] = int(policy_raw['max_regen_cycles'])
        if 'regen_mechanism' in policy_raw:
            policy['regen_mechanism'] = str(policy_raw['regen_mechanism']).strip()

    cells_raw = root.get('cells')
    if not isinstance(cells_raw, list) or not cells_raw:
        raise ValueError('cells must be a non-empty list')
    cells = []
    for i, cell_raw in enumerate(cells_raw):
        cell_raw = _require_mapping(cell_raw, f'cells[{i}]')
        cell_name = str(cell_raw.get('name') or f'cell_{i}').strip()
        try:
            d_p = float(cell_raw['catalyst_particle_mm'])
            loading = float(cell_raw['metal_loading'])
            dispersion = float(cell_raw['metal_dispersion'])
        except KeyError as exc:
            raise ValueError(
                f'{cell_name}: missing {exc.args[0]}') from exc
        if d_p <= 0:
            raise ValueError(f'{cell_name}: catalyst_particle_mm must be positive')
        if not (0.0 < loading <= 1.0 and 0.0 < dispersion <= 1.0):
            raise ValueError(
                f'{cell_name}: metal_loading and metal_dispersion must be in (0, 1]')
        cells.append(SweepCell(cell_name, d_p, loading, dispersion))

    description = root.get('description') or ''
    if not isinstance(description, str):
        raise ValueError('description must be a string')
    return SweepJob(
        name=name,
        description=' '.join(description.split()),
        catalyst_name=catalyst_name,
        temperatures_K=temperatures,
        reactor_types=reactor_types,
        policy=policy,
        cells=cells,
        source_file=str(yaml_path.resolve()),
        screening_csv=screening_csv,
        screening_index=screening_index,
        kinetics=kinetics,
    )


def _load_kinetics_row(job: SweepJob):
    import pandas as pd
    from pipeline.process.reactor_mechanisms import CandidateKinetics

    if job.screening_csv is not None:
        path = _resolve(job.screening_csv)
        if not path.is_file():
            raise FileNotFoundError(f'screening CSV not found: {path}')
        frame = pd.read_csv(path)
        if job.screening_index not in frame.index:
            raise KeyError(
                f'screening row {job.screening_index} missing from {path}')
        row = frame.loc[job.screening_index]
        return row, CandidateKinetics.from_screening_row(
            row, candidate_id=job.catalyst_name)
    return job.kinetics, CandidateKinetics(
        methane_activation_eV=float(job.kinetics['E_act']),
        h_adsorption_eV=job.kinetics.get('dE_H'),
        ch3_adsorption_eV=job.kinetics.get('dE_CH3'),
        c_adsorption_eV=job.kinetics.get('dE_C'),
        sources={'methane_activation_eV': 'sweep_yaml'},
    )


def _print_table(job: SweepJob, records: list) -> None:
    print(f'\nSweep: {job.name}')
    if job.description:
        print(job.description)
    print(
        f"{'cell':<22} {'reactor':<10} {'T_K':>7} {'X':>10} "
        f"{'a_1/m':>12} {'WHSV':>8} {'dP_bar':>8}"
    )
    for rec in records:
        a = rec.get('active_sv_1_m')
        whsv = rec.get('WHSV_h-1')
        dp = rec.get('ergun_delta_p_bar')
        print(
            f"{rec['cell']:<22} {rec['reactor_type']:<10} "
            f"{rec['T_K']:7.1f} {rec['CH4_conversion']:9.4%} "
            f"{(f'{a:.1f}' if a is not None else '—'):>12} "
            f"{(f'{whsv:.1f}' if whsv is not None else '—'):>8} "
            f"{(f'{dp:.3f}' if dp is not None else '—'):>8}"
        )


def run_sweep(yaml_path: Path) -> dict:
    """Parse YAML, write one mechanism, run every cell × T × reactor, persist JSON."""
    from pipeline.process.reactor_mechanisms import write_full_mechanism
    from pipeline.process.reactor_models import run_reactor_sweep

    job = parse_sweep(yaml_path)
    row, kinetics = _load_kinetics_row(job)
    try:
        e_act = float(row.get('E_act', kinetics.methane_activation_eV))
        dE_H = float(row.get('dE_H', 0.0) or 0.0)
    except (TypeError, ValueError, AttributeError):
        e_act = float(kinetics.methane_activation_eV)
        dE_H = float(job.kinetics.get('dE_H') or 0.0)

    mech = write_full_mechanism(job.catalyst_name, kinetics=kinetics)
    records = []
    for cell in job.cells:
        results = run_reactor_sweep(
            job.catalyst_name, str(mech),
            temperatures=list(job.temperatures_K),
            reactor_types=list(job.reactor_types),
            catalyst_E_act_eV=e_act,
            catalyst_dE_H_eV=dE_H,
            reactor_config_kwargs={
                **job.policy,
                'catalyst_particle_mm': cell.catalyst_particle_mm,
                'metal_loading': cell.metal_loading,
                'metal_dispersion': cell.metal_dispersion,
            },
        )
        for result in results:
            records.append({
                'cell': cell.name,
                'catalyst_particle_mm': cell.catalyst_particle_mm,
                'metal_loading': cell.metal_loading,
                'metal_dispersion': cell.metal_dispersion,
                'reactor_type': result.get('reactor_type'),
                'T_K': result.get('T_K'),
                'CH4_conversion': result.get('CH4_conversion'),
                'active_sv_1_m': result.get('active_sv_1_m'),
                'WHSV_h-1': result.get('WHSV_h-1'),
                'ergun_delta_p_bar': result.get('ergun_delta_p_bar'),
                'surface_loaded': result.get('surface_loaded'),
                'graphite_loaded': result.get('graphite_loaded'),
            })

    payload = {
        'job': asdict(job),
        'mechanism_file': str(mech),
        'written_at': datetime.now(timezone.utc).isoformat(),
        'records': records,
    }
    out_dir = SWEEPS_DIR / job.name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / 'run.json'
    out_json.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
    shutil.copy2(job.source_file, out_dir / 'input.yaml')
    logger.info(f'Wrote {out_json} ({len(records)} records)')
    _print_table(job, records)
    print(f'\nWrote {out_json}')
    return payload
