#!/usr/bin/env python3
"""Regenerate + publish the full Madd Hatchery tee line to a storefront.

Regens each concept's design (img2img via the configured backend) then runs
scripts/publish_store.py (transparent print art + transparent per-color back/front
mockups). madd_style = design on back + MH chest logo on front; nickel = front print.

Usage:
  python scripts/batch_madd.py [--api http://localhost:3310] [--only <concept-substr>] [--variants 1]
"""
import sys, types, subprocess, os, json, urllib.request, re, argparse
from pathlib import Path

ROOT = Path('/app/tee-empire'); sys.path.insert(0, str(ROOT))
for n, d in (('empire', 'empire'), ('empire.core', 'core')):
    m = types.ModuleType(n); m.__path__ = [str(ROOT / d)]; m.__package__ = n; sys.modules[n] = m
for line in (ROOT / '.env').read_text().splitlines():
    if '=' in line and not line.strip().startswith('#'):
        k, v = line.split('=', 1); os.environ.setdefault(k.strip(), v.split('#', 1)[0].strip())

import sqlite3
from empire.core.store import Store

ap = argparse.ArgumentParser()
ap.add_argument('--api', default='http://localhost:3310')
ap.add_argument('--only', default='')          # substring filter on concept slug
ap.add_argument('--variants', default='1')     # EMPIRE_OPENROUTER_VARIANTS for this run
ap.add_argument('--skip-regen', action='store_true')  # publish existing art only
ap.add_argument('--dump-dir', default='')             # write payloads instead of POSTing
args = ap.parse_args()
os.environ['EMPIRE_OPENROUTER_VARIANTS'] = args.variants

API = args.api
TOK = os.environ.get('MADDHATCHERY_ADMIN_TOKEN', '') if args.dump_dir else os.environ['MADDHATCHERY_ADMIN_TOKEN']
LOGO = '/app/maddhatch/public/assets/v3/logo_2026.png'


def slugify(t): return re.sub(r'-+', '-', re.sub(r'[^a-z0-9]+', '-', t.lower())).strip('-')


s = Store()
jobs = []
for c in s.list_concepts(brand='madd_hatchery'):
    if args.only and args.only not in c.slug:
        continue
    base = slugify(c.product_title)
    if c.lane == 'madd_style':
        jobs.append((c.slug, base + '-tee', c.product_title + ' Tee', 'madd-tee', 'dual'))
    elif c.lane == 'nickel':
        jobs.append((c.slug, base + '-tee', c.product_title + ' Tee', 'nickel-tee', 'front'))
print(f'{len(jobs)} tees | regen={not args.skip_regen} variants={args.variants}\n', flush=True)

for cslug, pslug, name, cat, mode in jobs:
    print(f'=== {name} ({mode}) ===', flush=True)
    if not args.skip_regen:
        con = sqlite3.connect('data/empire.db')
        con.execute('DELETE FROM designs WHERE concept_slug=?', (cslug,)); con.commit(); con.close()
        r = subprocess.run([sys.executable, '-m', 'empire', 'design', '--brand', 'madd_hatchery',
                            '--product-type', 'shirt', '--concepts', cslug, '--live'],
                           cwd=str(ROOT), capture_output=True, text=True, timeout=420)
        # surface the art source (openrouter-edit good; placeholder = gen failed)
        for ln in (r.stdout + r.stderr).splitlines():
            if 'source' in ln.lower() or 'placeholder' in ln.lower() or 'failed' in ln.lower():
                print('  ' + ln[:140])
    art = ROOT / 'data' / 'art' / f'madd_hatchery__{cslug}.png'
    if not art.exists() or art.stat().st_size < 100_000:
        print(f'  !! SKIP publish — no good art ({art.stat().st_size if art.exists() else "missing"} bytes)')
        continue
    logo = LOGO if mode == 'dual' else ''
    desc = 'Design on the back, little MH mark on the chest.' if mode == 'dual' else 'Bold front print on a soft heavy-cotton tee.'
    cmd = [sys.executable, 'scripts/publish_store.py', '--brand', 'madd_hatchery',
           '--concept', cslug, '--product', 'tee', '--slug', pslug, '--name', name,
           '--category', cat, '--price', '28', '--description', desc, '--logo', logo, '--api', API]
    if args.dump_dir:
        cmd += ['--dump-dir', args.dump_dir]
    pub = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=600)
    for ln in pub.stdout.splitlines():
        if any(k in ln for k in ('blueprint', 'printify product', 'mockups:', 'published', 'dumped')):
            print('  ' + ln)
    if pub.returncode != 0:
        print('  !! publish FAILED rc', pub.returncode, '\n  ' + '\n  '.join((pub.stderr or '').splitlines()[-6:]))

print('\nALL DONE', flush=True)
