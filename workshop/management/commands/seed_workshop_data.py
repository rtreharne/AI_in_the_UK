from __future__ import annotations

import re
from pathlib import Path

from django.core.management.base import BaseCommand

from workshop.models import Sector, WorkshopRun, WorkshopSection, WorkshopSettings


FLOW_PATTERN = re.compile(r'^\s*\d+\.\s*(.+?)\s*\((\d+)\s*min\)\s*$', re.IGNORECASE)
SECTOR_PATTERN = re.compile(r'^\s*\d+\.\s*(.+?)\s*$')

FACILITATOR_INTRO_TEXT = """# Welcome

Today, you are competing innovation teams bidding for **£10 million** in funding to develop an AI-powered solution for your sector. Your task is to identify a real problem, design a credible solution, and convince the room that your idea deserves investment.

## Why This Matters

AI is already everywhere. It is shaping education, healthcare, transport, business, public services, and everyday decision-making. Its influence is growing fast. But while attention often goes to what AI can do, much less thought is given to what it should do.

Questions of fairness, bias, accountability, sustainability, and unintended harm are still too often treated as an afterthought. This workshop starts from the position that these issues must be part of the conversation from the beginning.

## Purpose of This Session

The purpose of this session is to get you working together to explore how AI might be used in the near future to solve real UK problems in ways that are effective, responsible, and ethically defensible. You will develop an idea for your sector, listen to another team’s proposal, and judge it through the lens of sustainability, ethicality, and morality. You will then return to your own idea and strengthen it in response to those same concerns.

## By the End of the Session, You Should Be Able To

- identify a real and important problem in your sector
- propose a realistic AI-based solution
- evaluate solutions in terms of sustainability, ethicality, and morality
- strengthen a solution by responding to concerns and challenges
- communicate a clear and persuasive case for your solution

## How We Will Work

This is an active, collaborative workshop. You will need to think quickly, work together, challenge assumptions, and make decisions. The goal is not simply to produce the most exciting idea. It is to develop the strongest case for an AI solution that is practical, responsible, and worth backing.

### Before We Start: Choose Your Roles

Assign one role to each member of your group before research begins.

### 1. AI Operator
You will use AI tools to generate options quickly and refine early ideas.
You are required to draft candidate solutions, test prompts, and bring useful outputs back to the team.

### 2. Researcher
You will check whether claims are realistic, current, and evidence-based.
You are required to challenge weak assumptions, verify key facts, and identify practical constraints.

### 3. Scribe
You will capture decisions and keep the proposal structured and coherent.
You are required to record the problem, solution, risks, safeguards, and final pitch points clearly.

### 4. Orator
You will present the team’s case in each pitch round.
You are required to deliver a clear 1-minute pitch, respond to critique, and communicate revisions confidently."""

SECTION_DESCRIPTIONS = {
    'research and first pitch preparation': """## Section Goal
Use this time to prepare your first proposal.

## What To Do Now
- agree the specific problem in your sector
- explain why the problem matters now in the UK
- design a realistic AI-enabled solution
- identify expected benefits and practical delivery constraints

## Output For The Next Round
Prepare a 1-minute first pitch covering:
1. the problem
2. the proposed AI solution
3. the expected impact""",
    'first pitch round': "First pitch round in progress.",
    'research and anti-pitch preparation': """## Section Goal
Prepare a focused critique of another team’s proposal.

## Rotation Instruction
Pass your sector clockwise around the room to the next group before you begin.

## What To Evaluate
- fairness and bias risks
- accountability and governance gaps
- sustainability and long-term impact
- likely unintended harms

## Output For The Next Round
Prepare a 1-minute anti-pitch with your strongest concerns and concrete challenge questions.""",
    'anti-pitch round': "Anti-pitch round in progress.",
    'final revision': """## Section Goal
Strengthen your original proposal after critique.

## What To Improve
- address the strongest ethical and practical concerns raised
- refine safeguards so they are realistic and enforceable
- improve feasibility, clarity, and expected outcomes

## Output For The Next Round
Prepare your final 1-minute pitch with clear improvements and risk controls.""",
    'final pitch round': "Final pitch round in progress.",
    'vote and feedback': """## Section Goal
Evaluate the final proposals and submit feedback.

## What To Do
- scan the **Vote QR** code on the right side of the screen
- select the proposal you think is strongest overall
- submit a session rating and short written feedback

## Reminder
Vote for the proposal that is effective, realistic, and ethically defensible.""",
    'award to best ai solution': """## Section Goal
Review results and recognise the strongest proposal.

## What Happens Now
- final votes are revealed live
- the winning team is announced
- reflect briefly on what made the winning case strong

## Reflection Prompt
Which safeguards or design choices most improved trust and real-world viability?""",
}


class Command(BaseCommand):
    help = 'Seed workshop sections, sectors, settings, and active run state.'

    def handle(self, *args, **options):
        base_dir = Path(__file__).resolve().parents[3]
        session_file = base_dir / 'session_overview.md'
        sectors_file = base_dir / 'sectors.md'

        sections = self._load_sections(session_file)
        sectors = self._load_sectors(sectors_file)

        if sections:
            updated_count = 0
            for order, (title, minutes) in enumerate(sections, start=1):
                section, created = WorkshopSection.objects.get_or_create(
                    order=order,
                    defaults={
                        'title': title,
                        'description': self._default_description(title),
                        'duration_seconds': minutes * 60,
                        'enabled': True,
                    },
                )
                if created:
                    updated_count += 1
                    continue

                desired_description = self._default_description(title)
                changed = False
                if section.title != title:
                    section.title = title
                    changed = True
                if section.duration_seconds != minutes * 60:
                    section.duration_seconds = minutes * 60
                    changed = True
                if desired_description and section.description != desired_description:
                    section.description = desired_description
                    changed = True
                if changed:
                    section.save(update_fields=['title', 'duration_seconds', 'description'])
                    updated_count += 1

            self.stdout.write(self.style.SUCCESS(f'Ensured {len(sections)} workshop sections ({updated_count} changes).'))
        else:
            self.stdout.write('No workshop sections discovered; skipping section seed.')

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

    def _default_description(self, section_title: str) -> str:
        title = ' '.join(section_title.lower().split())
        if 'introduction' in title and 'facilitator' in title:
            return FACILITATOR_INTRO_TEXT
        return SECTION_DESCRIPTIONS.get(title, '')
