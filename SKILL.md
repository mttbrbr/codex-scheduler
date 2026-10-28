---
name: codex-scheduler
description: Pianifica su Linux la ripresa di una sessione Codex CLI già esistente ad un orario indicato, con timer systemd --user. Usa questa skill quando l'utente chiede di far continuare Codex più tardi, di vedere gli avvii programmati o di annullarli. Non riguarda Claude Code.
---

# Codex Scheduler (Linux)

Questa skill NON mantiene Codex aperto durante l'attesa. Usa `codex exec resume SESSION_ID` in un job di `systemd --user`, quindi serve Codex CLI installato, autenticato e un host acceso.

Strumento installato: `$HOME/.local/bin/codex-scheduler`. In alternativa richiama `scripts/codex_scheduler.py` qui accanto.

## Per una nuova schedulazione

1. Individua la directory del progetto interessato; non indovinarla quando vi sono più progetti possibili.
2. Leggi le sessioni: `codex-scheduler sessions --project '/percorso/assoluto'`.
3. Identifica la sessione esatta. Se ci sono più sessioni non facilmente distinguibili, chiedi all'utente quale usare o mostra i rispettivi ID; non scegliere arbitrariamente.
4. Interpreta l'orario richiesto usando il fuso locale dell'utente/sistema. Passa allo script la data in `YYYY-MM-DD HH:MM`, con le virgolette.
5. Prima di schedulare, prova una simulazione aggiungendo `--dry-run`:

   `codex-scheduler schedule --project '/percorso/assoluto' --session UUID --at '2026-10-29 03:00' --dry-run`

6. Quando tutto è chiaro, ripeti SENZA `--dry-run`. Conferma all'utente soltanto dopo che lo script segnala che il timer è stato creato.
7. Usa `--latest` soltanto se l'utente ha esplicitamente chiesto l'ultima sessione.

## Comandi

- `codex-scheduler doctor`
- `codex-scheduler sessions --project '/percorso/progetto'`
- `codex-scheduler sessions --all`
- `codex-scheduler schedule --project '/percorso/progetto' --session UUID --at 'YYYY-MM-DD HH:MM'`
- `codex-scheduler schedule --project '/percorso/progetto' --latest --at 'YYYY-MM-DD HH:MM'`
- `codex-scheduler jobs`
- `codex-scheduler logs JOB_ID`
- `codex-scheduler cancel JOB_ID`

## Limiti e sicurezza

- Non usare né consigliare flag come `--yolo`, `--dangerously-bypass-approvals-and-sandbox` o privilegi di root per aggirare approvazioni.
- Questa versione esegue `codex exec --sandbox workspace-write resume SESSION_ID ...`. Se un task richiede approvazione interattiva, può fallire o fermarsi: non promettere autonomia assoluta.
- Non sincronizza con una sessione Codex aperta in un altro terminale; assicurati che la stessa sessione non sia contemporaneamente attiva. Previene solo doppioni generati dallo scheduler.
- Non è un agente che si riavvia ogni volta che si azzera il limite: una schedulazione = un avvio.
- I log possono contenere dati sensibili; restano nella directory privata `$XDG_STATE_HOME/codex-scheduler` (default `~/.local/state/codex-scheduler`).
- Timer utente: per l'esecuzione dopo il logout potrebbe essere necessario `sudo loginctl enable-linger "$USER"`; il PC deve restare acceso e non sospeso.
