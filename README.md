# Citizens Online

A Nextcloud [ExApp](https://docs.nextcloud.com/server/latest/developer_manual/exapp_development/index.html)
for running **online citizens' assemblies** in Nextcloud Talk: participants are split into Talk
breakout rooms, each browser records its own microphone, a facilitator bot keeps time and speaking
balance, and what was said becomes an evidence-linked report an organizer reviews before publication.

```text
50 citizens → 10 Talk breakout rooms → 1 browser per participant
                          │
            records locally, uploads while it can
                          │
                   Citizens Online
                          │
      live captions (Vosk) · speaking time from audio activity
                          │
        facilitator bot · per-room analysis with evidence
                          │
                    human review
                          │
             final report (PDF / MD / JSON)
```

The in-person sibling of this app is [Citizens](https://github.com/theRAGEhero/nextcloud-citizens);
the process vocabulary (Routes, modules) comes from Democracy Routes. See [`PLAN.md`](PLAN.md) for the
architecture and roadmap, and [`docs/SPEC.md`](docs/SPEC.md) for the specification it implements.

**Alpha.** See [`TESTING.md`](TESTING.md) to try it.

## Licence

AGPL-3.0-or-later — see [LICENSE](LICENSE).
