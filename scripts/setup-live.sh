#!/usr/bin/env bash
# Take this deployment live: gate it, add the two API keys, flip the switch.
#
# Run it, paste each key when prompted, done. Keys are read with `read -s`, so
# they are never echoed to the terminal, never written to a file, and never land
# in your shell history.
#
#   bash scripts/setup-live.sh
#
# Order matters and this script enforces it: the access gate goes in FIRST.
# With live keys behind no gate, the production guard deliberately refuses to
# serve, because on this plan a production URL is reachable by anyone holding it
# and live keys behind an open URL can spend real money.

set -euo pipefail

SCOPE="vi-labs-projects"
ENVIRONMENT="production"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
ok()  { printf '  ✓ %s\n' "$*"; }

# Replace rather than fail: these variables already exist on the project as
# blank placeholders, and `vercel env add` refuses to overwrite a name that is
# already present.
replace() {
  local name="$1" value="$2"
  vercel env rm "$name" "$ENVIRONMENT" --scope "$SCOPE" --yes >/dev/null 2>&1 || true
  printf '%s' "$value" | vercel env add "$name" "$ENVIRONMENT" --scope "$SCOPE" >/dev/null
  ok "$name set"
}

say "1/4  Access gate"
if [ -n "${VSM_ACCESS_KEY_VALUE:-}" ]; then
  GATE="$VSM_ACCESS_KEY_VALUE"
else
  GATE="$(openssl rand -base64 24)"
  printf '  Generated a login password. SAVE IT NOW — it is shown once:\n\n      %s\n\n' "$GATE"
  read -r -p "  Saved it? [enter to continue] " _
fi
replace VSM_ACCESS_KEY "$GATE"

say "2/4  Anthropic key"
printf '  From console.anthropic.com, or the data-science team.\n'
printf '  Starts with sk-ant-  (input is hidden)\n'
read -r -s -p "  ANTHROPIC_API_KEY: " ANTHROPIC_KEY; echo
if [ -z "$ANTHROPIC_KEY" ]; then
  echo "  ✗ empty — aborting so the app is not left half-configured" >&2; exit 1
fi
case "$ANTHROPIC_KEY" in
  sk-ant-*) ;;
  *) printf '  ! That does not start with sk-ant-. Continue anyway? [y/N] '
     read -r a; [ "$a" = "y" ] || { echo "  aborted"; exit 1; } ;;
esac
replace ANTHROPIC_API_KEY "$ANTHROPIC_KEY"

say "3/4  Bright Data key"
printf '  Bright Data control panel → Account settings → API keys\n'
printf '  (input is hidden)\n'
read -r -s -p "  BRIGHTDATA_API_KEY: " BD_KEY; echo
if [ -z "$BD_KEY" ]; then
  echo "  ✗ empty — aborting" >&2; exit 1
fi
# Catch the commonest paste mistake: the docs template rather than the key.
case "$BD_KEY" in
  *"replace with API Key"*|*"Bearer"*|*"curl"*|*"Secret:"*)
    echo "  ✗ that looks like a docs snippet, not a key — aborting" >&2; exit 1 ;;
esac
replace BRIGHTDATA_API_KEY "$BD_KEY"

# The zones already match this app's defaults (dataweb_serp_api1 / dataweb), so
# they are left alone deliberately.

say "4/4  Go live and redeploy"
replace VSM_OFFLINE 0
vercel --prod --scope "$SCOPE" >/dev/null
ok "redeployed"

say "Done"
cat <<'EOF'
  Next: open the connection check and press "Run connection test".
      https://vi-signal-mine-pink.vercel.app/healthz/brightdata

  It makes one cheap real call per Bright Data product and reports pass/fail,
  so a wrong key or zone shows up for a few cents instead of mid-sweep.

  The site is now gated: your browser will ask for a password. Any username,
  the access key as the password.
EOF
