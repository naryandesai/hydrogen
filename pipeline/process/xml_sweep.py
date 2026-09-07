"""Load a reactor-cell sweep from XML and run it.

Input specs live under sweeps/*.xml (git-tracked). Run products go to
results/sweeps/<name>/ (gitignored). See docs/sweep-template.md.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from xml.etree import ElementTree as ET

from pipeline.common.utils import BASE_DIR, SWEEPS_DIR, setup_logger

logger = setup_logger('xml_sweep', 'reactor/xml_sweep.log')

ALLOWED_REACTORS = ('PFR', 'Fluidized', 'MMBCR')
_SPLIT = re.compile(r'[\s,]+')


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
    source_xml: str
    screening_csv: Optional[str] = None
    screening_index: Optional[int] = None
    kinetics: dict = field(default_factory=dict)


def _child(root: ET.Element, tag: str, required: bool = False) -> Optional[ET.Element]:
    node = root.find(tag)
    if required and node is None:
        raise ValueError(f'sweep XML is missing required <{tag}>')
    return node


def _text(node: Optional[ET.Element], default: str = '') -> str:
    if node is None or node.text is None:
        return default
    return node.text.strip()


def _floats(text: str) -> List[float]:
    parts = [p for p in _SPLIT.split(text.strip()) if p]
    if not parts:
        raise ValueError('expected at least one number')
    return [float(p) for p in parts]


def _as_bool(text: str) -> bool:
    value = text.strip().lower()
    if value in ('true', '1', 'yes'):
        return True
    if value in ('false', '0', 'no'):
        return False
    raise ValueError(f'expected boolean, got {text!r}')


def _resolve(path_text: str) -> Path:
    path = Path(path_text)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def parse_sweep_xml(xml_path: Path) -> SweepJob:
    """Parse one sweep spec. Does not touch Cantera or write mechanisms."""
    xml_path = Path(xml_path)
    if not xml_path.is_file():
        raise FileNotFoundError(f'no such sweep file: {xml_path}')
    root = ET.parse(xml_path).getroot()
    if root.tag != 'sweep':
        raise ValueError(f'root element must be <sweep>, got <{root.tag}>')
    name = (root.get('name') or xml_path.stem).strip()
    if not name:
        raise ValueError('sweep @name is required')

    catalyst = _child(root, 'catalyst', required=True)
    catalyst_name = (catalyst.get('name') or name).strip()
    screening = catalyst.find('screening')
    kinetics_el = catalyst.find('kinetics')
    screening_csv = None
    screening_index = None
    kinetics = {}
    if screening is not None:
        csv_text = screening.get('csv')
        index_text = screening.get('index')
        if not csv_text or index_text is None:
            raise ValueError('<screening> requires csv and index attributes')
        screening_csv = csv_text
        screening_index = int(index_text)
    if kinetics_el is not None:
        for key in ('E_act', 'dE_H', 'dE_CH3', 'dE_C'):
            raw = kinetics_el.get(key)
            if raw is not None and raw != '':
                kinetics[key] = float(raw)
    if screening is None and 'E_act' not in kinetics:
        raise ValueError('catalyst needs <screening csv= index=> or <kinetics E_act=>')

    conditions = _child(root, 'conditions', required=True)
    temperatures = _floats(_text(_child(conditions, 'temperatures', required=True)))
    reactor_text = _text(_child(conditions, 'reactors', required=True))
    reactor_types = [r for r in _SPLIT.split(reactor_text) if r]
    unknown = [r for r in reactor_types if r not in ALLOWED_REACTORS]
    if unknown:
        raise ValueError(f'unknown reactor type(s) {unknown}; allowed {ALLOWED_REACTORS}')

    policy_el = _child(root, 'policy')
    policy = {
        'co2_permitted': False,
        'fluidized_mode': 'circulating',
        'max_regen_cycles': 3,
        'regen_mechanism': 'mechanical',
    }
    if policy_el is not None:
        if policy_el.find('co2_permitted') is not None:
            policy['co2_permitted'] = _as_bool(_text(policy_el.find('co2_permitted')))
        if policy_el.find('fluidized_mode') is not None:
            policy['fluidized_mode'] = _text(policy_el.find('fluidized_mode'))
        if policy_el.find('max_regen_cycles') is not None:
            policy['max_regen_cycles'] = int(_text(policy_el.find('max_regen_cycles')))
        if policy_el.find('regen_mechanism') is not None:
            policy['regen_mechanism'] = _text(policy_el.find('regen_mechanism'))

    cells_el = _child(root, 'cells', required=True)
    cells = []
    for cell_el in cells_el.findall('cell'):
        cell_name = (cell_el.get('name') or f'cell_{len(cells)}').strip()
        d_p = float(_text(_child(cell_el, 'catalyst_particle_mm', required=True)))
        loading = float(_text(_child(cell_el, 'metal_loading', required=True)))
        dispersion = float(_text(_child(cell_el, 'metal_dispersion', required=True)))
        if d_p <= 0:
            raise ValueError(f'{cell_name}: catalyst_particle_mm must be positive')
        if not (0.0 < loading <= 1.0 and 0.0 < dispersion <= 1.0):
            raise ValueError(
                f'{cell_name}: metal_loading and metal_dispersion must be in (0, 1]')
        cells.append(SweepCell(cell_name, d_p, loading, dispersion))
    if not cells:
        raise ValueError('<cells> must contain at least one <cell>')

    return SweepJob(
        name=name,
        description=' '.join(_text(_child(root, 'description')).split()),
        catalyst_name=catalyst_name,
        temperatures_K=temperatures,
        reactor_types=reactor_types,
        policy=policy,
        cells=cells,
        source_xml=str(xml_path.resolve()),
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
        sources={'methane_activation_eV': 'sweep_xml'},
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


def run_xml_sweep(xml_path: Path) -> dict:
    """Parse XML, write one mechanism, run every cell × T × reactor, persist JSON."""
    from pipeline.process.reactor_mechanisms import write_full_mechanism
    from pipeline.process.reactor_models import run_reactor_sweep

    job = parse_sweep_xml(xml_path)
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
    shutil.copy2(job.source_xml, out_dir / 'input.xml')
    logger.info(f'Wrote {out_json} ({len(records)} records)')
    _print_table(job, records)
    print(f'\nWrote {out_json}')
    return payload
