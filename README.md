# Codex Scheduler — Linux

Una Skill per programmare la ripresa di una **sessione Codex CLI già esistente**, senza tenere aperto Codex mentre aspetti. Impiega i timer `systemd --user` e `codex exec resume ID`.

## Installazione

```bash
unzip codex-scheduler-linux.zip
bash codex-scheduler/install.sh
~/.local/bin/codex-scheduler doctor
```

Riavvia Codex CLI e usa la skill `$codex-scheduler` oppure direttamente il comando `codex-scheduler` (assicurati che `~/.local/bin` sia nel `PATH`).

## Esempio

```bash
codex-scheduler sessions --project "$HOME/progetti/sito"
codex-scheduler schedule --project "$HOME/progetti/sito" --latest --at '2026-10-29 03:00' --dry-run
codex-scheduler schedule --project "$HOME/progetti/sito" --latest --at '2026-10-29 03:00'
codex-scheduler jobs
codex-scheduler logs ID_JOB
codex-scheduler cancel ID_JOB
```

Puoi anche passare `--session UUID` invece di `--latest` per evitare ambiguità, e `--message 'Continua a lavorare...'` per cambiare il prompt inviato a Codex.

Il progetto deve essere un repository Git, salvo scelta esplicita `--allow-non-git`. Lo script cerca le sessioni locali in `${CODEX_HOME:-~/.codex}/sessions/`, confrontandone l'esatta directory di lavoro (`cwd`). La selezione avviene **al momento della pianificazione**: non cambia se altre sessioni vengono aperte dopo.

L'ora è quella **locale del PC Linux**. Usa date complete `YYYY-MM-DD HH:MM`; in prossimità dei cambi ora legale/solare, controlla il timer con `systemctl --user list-timers --all`.

## Esecuzione e privacy

- Assicurati che Codex CLI sia installato e autenticato e che la sessione sia leggibile all'utente che crea il timer.
- La sessione Codex da riprendere non deve essere già attiva in un altro terminale al momento dell'esecuzione.
- La modalità non interattiva usa `--sandbox workspace-write` e non disabilita le protezioni; alcune approvazioni potrebbero richiedere l'intervento manuale e impedire al lavoro di completarsi.
- Il computer deve rimanere acceso e non sospeso. Se vuoi conservare i timer utente dopo il logout, usa `sudo loginctl enable-linger "$USER"` quando appropriato.
- I job e i log sono salvati in `~/.local/state/codex-scheduler/` (oppure `$XDG_STATE_HOME/codex-scheduler`, sovrascrivibile con `$CODEX_SCHEDULER_STATE`). Non pubblicarli su GitHub: possono contenere percorsi privati, ID di sessioni e output del modello.
- La sessione effettiva di Codex mantiene il contesto recuperabile dalla sua cronologia, ma non può recuperare attività in corso che non siano state persistite.
- Dopo un'eventuale modifica del contesto o di Codex CLI, verifica la compatibilità della funzione resume.

## Verifica e test

```bash
python3 -m unittest discover -s codex-scheduler/tests -v
```

I test non contattano Codex né OpenAI; simulano chiamate CLI e scheduler. Il funzionamento reale su una specifica installazione Linux va testato dall'utente.

## Riferimenti

- Codex CLI reference: https://learn.chatgpt.com/docs/cli/reference
- Non-interactive Codex: https://learn.chatgpt.com/docs/non-interactive-mode
- Codex skills: https://learn.chatgpt.com/docs/build-skills
