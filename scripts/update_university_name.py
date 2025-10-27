#!/usr/bin/env python
"""
Utility CLI per rinominare un'università nel database SQLite.

Uso esempi (PowerShell):
  # Elenca le università
  python scripts/update_university_name.py list

  # Rinomina cercando per nome corrente (case-insensitive)
  python scripts/update_university_name.py rename --current "TECHNICAL UNIVERSITY OF MUNICH" --new "TU MUNICH"

  # Rinomina per ID
  python scripts/update_university_name.py rename --id 3 --new "Università di Pisa"
"""

import argparse
import sys
from typing import Optional

try:
    from app.core.database import db_manager
except Exception as e:
    print("Errore: impossibile importare il database manager. Esegui il comando dalla root del progetto.")
    print(e)
    sys.exit(1)


def cmd_list(_: argparse.Namespace) -> int:
    rows = db_manager.list_universities()
    if not rows:
        print("Nessuna università trovata.")
        return 0
    print(f"Trovate {len(rows)} università:\n")
    for r in rows:
        print(f"- ID: {r['id']:>3} | Nome: {r['university_name']} | Email: {r['institutional_email']}")
    return 0


def cmd_rename(args: argparse.Namespace) -> int:
    new_name = args.new.strip() if args.new else None
    if not new_name:
        print("Errore: specificare --new <nuovo_nome>.")
        return 2

    if args.id is None and not args.current:
        print("Errore: specificare --id <id> oppure --current <nome_attuale>.")
        return 2

    # Esegui rinomina per ID o per nome corrente
    if args.id is not None:
        ok = db_manager.update_university_name_by_id(args.id, new_name)
        if ok:
            print(f"✅ Università con ID {args.id} rinominata in: {new_name}")
            return 0
        else:
            print("❌ Rinomina fallita. Possibile conflitto di nome già esistente o ID inesistente.")
            return 1
    else:
        current = args.current.strip()
        ok = db_manager.update_university_name(current, new_name)
        if ok:
            print(f"✅ Università '{current}' rinominata in: {new_name}")
            return 0
        else:
            print("❌ Rinomina fallita. Possibile conflitto di nome già esistente o nome attuale non trovato.")
            return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Rinomina università nel DB")

    sub = p.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="Elenca università")
    p_list.set_defaults(func=cmd_list)

    p_rename = sub.add_parser("rename", help="Rinomina università")
    p_rename.add_argument("--id", type=int, help="ID dell'università da rinominare")
    p_rename.add_argument("--current", type=str, help="Nome attuale (case-insensitive)")
    p_rename.add_argument("--new", type=str, required=True, help="Nuovo nome")
    p_rename.set_defaults(func=cmd_rename)

    return p


def main(argv: Optional[list] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
