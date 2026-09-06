"""Candidate-to-Cantera stage shared by interactive and production campaigns."""

from __future__ import annotations

from typing import Mapping, Sequence


def simulate_candidate(row: Mapping, catalyst_name: str,
                       temperatures: Sequence[float],
                       reactor_types: Sequence[str] | None = None,
                       forbid_mock: bool = True) -> dict:
    """Build one candidate mechanism and run its reactor-condition sweep."""
    from pipeline.process.reactor_mechanisms import (
        CandidateKinetics, write_full_mechanism)
    from pipeline.process.reactor_models import run_reactor_sweep

    kinetics = CandidateKinetics.from_screening_row(
        row, candidate_id=str(row.get('candidate_id', catalyst_name)))
    mechanism = write_full_mechanism(catalyst_name, kinetics=kinetics)
    barrier = float(row.get('E_act'))
    try:
        dE_H = float(row.get('dE_H'))
    except (TypeError, ValueError):
        dE_H = 0.0
    extra = {
        'co2_permitted': False,
        'fluidized_mode': 'circulating',
        'max_regen_cycles': 3,
        'regen_mechanism': 'mechanical',
    }
    sweep = run_reactor_sweep(
        catalyst_name, str(mechanism), temperatures=list(temperatures),
        reactor_types=None if reactor_types is None else list(reactor_types),
        catalyst_E_act_eV=barrier,
        catalyst_dE_H_eV=dE_H,
        reactor_config_kwargs=extra)
    if forbid_mock and any(result.get('mock') for result in sweep):
        raise RuntimeError('mock reactor output is forbidden in production')
    best = max(sweep, key=lambda result: result.get('CH4_conversion', 0.0)) \
        if sweep else {}
    return {
        'catalyst': catalyst_name,
        'candidate_id': kinetics.candidate_id,
        'E_act': barrier,
        'mechanism_file': str(mechanism),
        'sweep': sweep,
        'best_condition': best,
    }
