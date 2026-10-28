#!/usr/bin/env python3
"""Schedule one-shot Codex CLI session resumes via Linux systemd user timers.

No third-party dependencies. Intended for trusted local projects only.
"""
import argparse
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
from typing import Any
import uuid

DEFAULT_MESSAGE = (
    "Riprendi il lavoro che stavi svolgendo in questa sessione. "
    "Controlla lo stato attuale dei file prima di modificarli; "
    "continua le attività incompiute, esegui i test opportuni e "
    "riassumi ciò che hai fatto e ciò che resta da fare. "
    "Non effettuare operazioni distruttive senza autorizzazione."
)
JOB_PATTERN = re.compile(r"^[a-f0-9]{12}$")


def state_root() -> Path:
    override = os.environ.get("CODEX_SCHEDULER_STATE")
    if override:
        return Path(override).expanduser().resolve()
    base = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
    return (base / "codex-scheduler").resolve()


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser().resolve()


def ensure_state() -> Path:
    root = state_root()
    for directory in (root, root / "jobs", root / "logs", root / "locks"):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
    return root


def project_path(value: str) -> Path:
    result = Path(value).expanduser().resolve()
    if not result.is_dir():
        raise ValueError(f"La directory del progetto non esiste: {result}")
    return result


def discover_sessions() -> list[dict[str, Any]]:
    root = codex_home() / "sessions"
    if not root.is_dir():
        return []
    found = {}
    for path in root.glob("**/rollout-*.jsonl"):
        try:
            with path.open("r", encoding="utf-8") as file:
                for _, line in zip(range(15), file):
                    obj = json.loads(line)
                    if obj.get("type") != "session_meta":
                        continue
                    meta = obj.get("payload") or {}
                    session_id = str(meta.get("id") or meta.get("session_id") or "")
                    uuid.UUID(session_id)
                    cwd = meta.get("cwd")
                    if not isinstance(cwd, str) or not cwd:
                        break
                    session = {
                        "id": session_id,
                        "project": str(Path(cwd).expanduser().resolve()),
                        "updated": path.stat().st_mtime,
                        "file": str(path),
                    }
                    prior = found.get(session_id)
                    if prior is None or session["updated"] > prior["updated"]:
                        found[session_id] = session
                    break
        except (OSError, ValueError, UnicodeError, TypeError):
            continue
    return sorted(found.values(), key=lambda obj: obj["updated"], reverse=True)


def sessions_for(project: Path | None = None) -> list[dict[str, Any]]:
    sessions = discover_sessions()
    return [s for s in sessions if s["project"] == str(project)] if project else sessions


def job_path(job_id: str) -> Path:
    if not JOB_PATTERN.fullmatch(job_id):
        raise ValueError("ID job non valido")
    return state_root() / "jobs" / f"{job_id}.json"


def load_job(job_id: str) -> dict[str, Any]:
    try:
        return json.loads(job_path(job_id).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Job non trovato: {job_id}") from exc


def save_job(job: dict[str, Any]) -> None:
    ensure_state()
    file = job_path(job["id"])
    tmp = file.with_name(f".{file.stem}-{secrets.token_hex(4)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(job, output, indent=2, ensure_ascii=False)
            output.write("\n")
        os.replace(tmp, file)
    finally:
        if tmp.exists():
            tmp.unlink()


def unit_name(job_id: str) -> str:
    return f"codex-scheduler-{job_id}"


def check_systemd() -> None:
    if not shutil.which("systemd-run") or not shutil.which("systemctl"):
        raise RuntimeError("systemd-run e systemctl sono necessari su Linux")
    proc = subprocess.run(["systemctl", "--user", "show-environment"], capture_output=True, text=True)
    if proc.returncode:
        raise RuntimeError("Impossibile contattare systemd --user. Verifica la sessione utente.\n" + proc.stderr.strip())


def schedule(args: argparse.Namespace) -> None:
    project = project_path(args.project)
    candidates = sessions_for(project)
    if args.session:
        try:
            selected_id = str(uuid.UUID(args.session))
        except ValueError as exc:
            raise ValueError("L'ID sessione deve essere un UUID") from exc
        chosen = next((s for s in candidates if s["id"] == selected_id), None)
        if chosen is None:
            raise ValueError("Sessione non trovata in questo progetto. Prova 'sessions --project ...'.")
    elif args.latest:
        if not candidates:
            raise ValueError("Nessuna sessione Codex trovata in questo progetto")
        chosen = candidates[0]
    else:
        raise ValueError("Seleziona una sessione con --session UUID oppure --latest")
    try:
        when = dt.datetime.strptime(args.at, "%Y-%m-%d %H:%M")
    except ValueError as exc:
        raise ValueError("Formato data richiesto: 'YYYY-MM-DD HH:MM' (ora locale)") from exc
    if when.timestamp() <= dt.datetime.now().timestamp():
        raise ValueError("L'orario deve essere nel futuro")
    binary = shutil.which("codex")
    if not binary:
        raise RuntimeError("Comando 'codex' non disponibile nel PATH")
    if not args.allow_non_git:
        git = subprocess.run(["git", "-C", str(project), "rev-parse", "--is-inside-work-tree"],
                             capture_output=True, text=True)
        if git.returncode or git.stdout.strip() != "true":
            raise RuntimeError("Il progetto non è in un repository Git. Usa --allow-non-git solo se necessario.")
    if not args.dry_run:
        check_systemd()
    job_id = secrets.token_hex(6)
    job = {
        "id": job_id,
        "session": chosen["id"],
        "project": str(project),
        "at": args.at,
        "message": args.message or DEFAULT_MESSAGE,
        "status": "scheduled",
        "created": dt.datetime.now().astimezone().isoformat(),
        "codex_bin": str(Path(binary).resolve()),
        "codex_home": str(codex_home()),
        "path": os.environ.get("PATH", ""),
        "allow_non_git": args.allow_non_git,
    }
    cmd = [
        "systemd-run", "--user", "--quiet", f"--unit={unit_name(job_id)}",
        f"--on-calendar={when.strftime('%Y-%m-%d %H:%M:%S')}",
        "--timer-property=AccuracySec=1s", "--property=Type=oneshot",
        "--property=TimeoutStartSec=0", "--collect",
        f"--setenv=CODEX_SCHEDULER_STATE={state_root()}",
        sys.executable, str(Path(__file__).resolve()), "run", job_id,
    ]
    print(f"Job: {job_id}\nSessione: {chosen['id']}\nProgetto: {project}\nOra locale: {args.at}")
    if args.dry_run:
        print("ANTEPRIMA: non è stato registrato alcun timer.")
        print("Comando timer:", " ".join(cmd))
        return
    save_job(job)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode:
        job["status"] = "scheduling-failed"
        job["error"] = (proc.stderr or proc.stdout).strip()
        save_job(job)
        raise RuntimeError("Impossibile creare il timer: " + job["error"])
    print("Timer creato. Vedi 'codex-scheduler jobs' o 'systemctl --user list-timers --all'.")


def run_job(job_id: str) -> int:
    ensure_state()
    lock_path = state_root() / "locks" / (job_id + ".lock")
    with lock_path.open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Job già in esecuzione", file=sys.stderr)
            return 3
        job = load_job(job_id)
        if job["status"] != "scheduled":
            print("Job non eseguibile nello stato: " + job["status"], file=sys.stderr)
            return 4
        # Lock by session as well as job. Prevents parallel scheduler jobs on one session.
        session_lock = state_root() / "locks" / (job["session"] + ".lock")
        with session_lock.open("a+") as s_lock:
            try:
                fcntl.flock(s_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                job["status"] = "failed"
                job["error"] = "Un altro job è già in esecuzione sulla stessa sessione"
                save_job(job)
                print(job["error"], file=sys.stderr)
                return 5
            job["status"] = "running"
            job["started"] = dt.datetime.now().astimezone().isoformat()
            save_job(job)
            env = os.environ.copy()
            env["PATH"] = job["path"]
            env["CODEX_HOME"] = job["codex_home"]
            command = [job["codex_bin"], "exec", "--sandbox", "workspace-write"]
            if job.get("allow_non_git"):
                command.append("--skip-git-repo-check")
            command += ["resume", job["session"], job["message"]]
            log_path = state_root() / "logs" / f"{job_id}.log"
            fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                with os.fdopen(fd, "a", encoding="utf-8") as log:
                    log.write(f"Job {job_id}; started {job['started']}; session {job['session']}\n")
                    log.flush()
                    try:
                        code = subprocess.run(command, cwd=job["project"], env=env,
                                              stdin=subprocess.DEVNULL, stdout=log,
                                              stderr=subprocess.STDOUT, check=False).returncode
                    except OSError as exc:
                        log.write("Errore di avvio: " + str(exc) + "\n")
                        code = 127
                    log.write(f"\n--- Exit code: {code} ---\n")
            finally:
                job["finished"] = dt.datetime.now().astimezone().isoformat()
                job["exit_code"] = code
                job["status"] = "completed" if code == 0 else "failed"
                save_job(job)
            print("Job", job_id, job["status"], "exit", code)
            return code


def show_sessions(args: argparse.Namespace) -> None:
    project = None if args.all else project_path(args.project)
    sessions = sessions_for(project)
    if not sessions:
        print("Nessuna sessione trovata.")
        return
    for s in sessions[:args.limit]:
        date = dt.datetime.fromtimestamp(s["updated"]).strftime("%Y-%m-%d %H:%M")
        print(f"{date}  {s['id']}  {s['project']}")


def show_jobs(_args: argparse.Namespace) -> None:
    jobs = []
    for file in (state_root() / "jobs").glob("*.json"):
        try:
            jobs.append(json.loads(file.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    if not jobs:
        print("Nessun job registrato.")
        return
    for job in sorted(jobs, key=lambda x: x.get("created", ""), reverse=True):
        print(f"{job['id']}  {job['status']:18s}  {job['at']}  {job['project']}  {job['session']}")


def cancel(args: argparse.Namespace) -> None:
    job = load_job(args.job)
    if job["status"] != "scheduled":
        raise ValueError("Si possono annullare soltanto i job ancora programmati")
    check_systemd()
    proc = subprocess.run(["systemctl", "--user", "stop", unit_name(args.job) + ".timer"],
                          capture_output=True, text=True)
    if proc.returncode:
        raise RuntimeError("Stop timer non riuscito: " + proc.stderr.strip())
    job["status"] = "cancelled"
    save_job(job)
    print("Annullato", args.job)


def show_logs(args: argparse.Namespace) -> None:
    load_job(args.job)
    path = state_root() / "logs" / f"{args.job}.log"
    if not path.exists():
        print("Nessun log disponibile (il job non è ancora partito).")
        return
    print(path.read_text(encoding="utf-8", errors="replace"))


def doctor(_args: argparse.Namespace) -> None:
    for name in ("codex", "git", "systemd-run", "systemctl"):
        print(f"{name}: {shutil.which(name) or 'NON TROVATO'}")
    print(f"Codex home: {codex_home()}")
    print(f"Sessioni rilevate: {len(discover_sessions())}")
    print(f"Stato: {state_root()}")
    try:
        check_systemd()
        print("systemd --user: OK")
    except RuntimeError as exc:
        print("systemd --user: NON DISPONIBILE", exc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="codex-scheduler", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("sessions", help="Elenca sessioni Codex per progetto")
    p.add_argument("--project", default=os.getcwd())
    p.add_argument("--all", action="store_true", help="Mostra tutte le directory")
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(func=show_sessions)
    p = sub.add_parser("schedule", help="Programma una ripresa singola")
    p.add_argument("--project", default=os.getcwd())
    select = p.add_mutually_exclusive_group(required=True)
    select.add_argument("--session", help="UUID sessione preciso")
    select.add_argument("--latest", action="store_true", help="Sessione più recente nel progetto")
    p.add_argument("--at", required=True, help="'YYYY-MM-DD HH:MM' ora locale Linux")
    p.add_argument("--message", help="Istruzione da inviare alla sessione")
    p.add_argument("--allow-non-git", action="store_true", help="Permetti progetti fuori da Git")
    p.add_argument("--dry-run", action="store_true", help="Anteprima senza timer")
    p.set_defaults(func=schedule)
    p = sub.add_parser("run", help=argparse.SUPPRESS)
    p.add_argument("job")
    p.set_defaults(func=lambda a: sys.exit(run_job(a.job)))
    p = sub.add_parser("jobs", help="Elenca job programmati e conclusi")
    p.set_defaults(func=show_jobs)
    p = sub.add_parser("cancel", help="Annulla job ancora programmato")
    p.add_argument("job")
    p.set_defaults(func=cancel)
    p = sub.add_parser("logs", help="Stampa il log di un job")
    p.add_argument("job")
    p.set_defaults(func=show_logs)
    p = sub.add_parser("doctor", help="Verifica dipendenze")
    p.set_defaults(func=doctor)
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (ValueError, RuntimeError) as exc:
        print("Errore:", exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
