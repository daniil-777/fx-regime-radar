# E-mail hook for the weekly report (documented, not enabled)

The Monday workflow (`.github/workflows/weekly.yml`) writes `docs/weekly/<date>.md`, an
e-mail-safe `docs/weekly/<date>.html` twin, and `docs/feed.xml`. **Nothing is e-mailed today**
and no subscriber list exists (see `docs/PRIVACY.md`). Zero paid services are used.

## Free ways to subscribe right now
* RSS: `docs/feed.xml` (any feed reader; last 52 Mondays).
* GitHub: "Watch → Custom → Releases/Commits" on the repository, or a free RSS-to-e-mail bridge
  pointed at the feed (the reader's choice, their data, not ours).

## The hook (when a provider is chosen later)
Add one step after "Write this Monday's report" in `weekly.yml`:

```yaml
      - name: Send the weekly e-mail (opt-in list only)
        if: ${{ secrets.WEEKLY_MAIL_API_KEY != '' }}
        run: python scripts/send_weekly.py docs/weekly/$(date -u +%F).html
        env:
          WEEKLY_MAIL_API_KEY: ${{ secrets.WEEKLY_MAIL_API_KEY }}
```

`scripts/send_weekly.py` (not written yet) should: read the HTML twin, POST it to the
provider's campaign API (any provider with a free tier and a list hosted on their side), and
write the subscriber count back to `data/subscribers.json` as `{"subscribers": [...]}` **or**
simply `{"count": N}` — `fxradar.metrics_page` counts a list; extend `_subscribers` if you
store only a count. Requirements before flipping it on:

1. Opt-in only, double opt-in preferred; one-click unsubscribe in the footer.
2. The HTML already carries the disclaimer and uses inline styles only (max-width 600, light
   palette from `weekly.LIGHT_TOKENS`); do not add tracking pixels.
3. Secrets via repository secrets only (rule 9); the job must succeed when the secret is absent.
4. Update `docs/PRIVACY.md` with the provider's name and data location first.

Educational tool. Not investment advice.
