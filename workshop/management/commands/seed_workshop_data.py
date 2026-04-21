from __future__ import annotations

import re
from pathlib import Path

from django.core.management.base import BaseCommand

from workshop.models import Sector, WorkshopRun, WorkshopSection, WorkshopSettings


FLOW_PATTERN = re.compile(r'^\s*\d+\.\s*(.+?)\s*\((\d+)\s*min\)\s*$', re.IGNORECASE)
SECTOR_PATTERN = re.compile(r'^\s*\d+\.\s*(.+?)\s*$')


class Command(BaseCommand):
    help = 'Seed workshop sections, sectors, settings, and active run state.'

    def handle(self, *args, **options):
        base_dir = Path(__file__).resolve().parents[3]
        session_file = base_dir / 'session_overview.md'
        sectors_file = base_dir / 'sectors.md'

        sections = self._load_sections(session_file)
        sectors = self._load_sectors(sectors_file)

        if not WorkshopSection.objects.exists() and sections:
            for order, (title, minutes) in enumerate(sections, start=1):
                WorkshopSection.objects.create(
                    order=order,
                    title=title,
                    description='',
                    duration_seconds=minutes * 60,
                    enabled=True,
                )
            self.stdout.write(self.style.SUCCESS(f'Seeded {len(sections)} workshop sections.'))
        else:
            self.stdout.write('Workshop sections already present or none discovered; skipping section seed.')

        if not Sector.objects.exists() and sectors:
            for order, name in enumerate(sectors, start=1):
                Sector.objects.create(order=order, name=name)
            self.stdout.write(self.style.SUCCESS(f'Seeded {len(sectors)} sectors.'))
        else:
            self.stdout.write('Sectors already present or none discovered; skipping sector seed.')

        WorkshopSettings.get_solo()
        WorkshopRun.get_solo()
        self.stdout.write(self.style.SUCCESS('Ensured singleton settings and run records.'))

    def _load_sections(self, path: Path):
        if not path.exists():
            self.stdout.write(self.style.WARNING(f'Missing {path.name}; skipping section seed.'))
            return []

        in_workshop_flow = False
        sections = []

        for raw_line in path.read_text(encoding='utf-8').splitlines():
            line = raw_line.strip()
            if line.lower().startswith('## workshop flow'):
                in_workshop_flow = True
                continue
            if in_workshop_flow and line.startswith('## '):
                break
            if not in_workshop_flow or not line:
                continue

            match = FLOW_PATTERN.match(line)
            if not match:
                continue
            title, minutes = match.group(1), int(match.group(2))
            sections.append((title.strip(), minutes))

        return sections

    def _load_sectors(self, path: Path):
        if not path.exists():
            self.stdout.write(self.style.WARNING(f'Missing {path.name}; skipping sector seed.'))
            return []

        sectors = []
        for raw_line in path.read_text(encoding='utf-8').splitlines():
            match = SECTOR_PATTERN.match(raw_line)
            if match:
                sectors.append(match.group(1).strip())

        return sectors
