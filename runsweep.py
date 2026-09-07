#!/usr/bin/env python3
"""Run a reactor-cell sweep from an XML spec.

    python runsweep.py sweeps/headline_cat9_1300K.xml

Schema: docs/sweep-template.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline.process.xml_sweep import run_xml_sweep


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Run a Cantera reactor-cell sweep from XML')
    parser.add_argument(
        'input_xml', type=Path,
        help='Sweep specification (see docs/sweep-template.md)')
    args = parser.parse_args()
    run_xml_sweep(args.input_xml)


if __name__ == '__main__':
    main()
