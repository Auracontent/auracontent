#!/usr/bin/env bash
# Installe tout ce qu'il faut pour travailler sur AuraContent, sur n'importe quelle machine :
#   - un PC Linux (Ubuntu/Debian, Fedora), un Mac (Homebrew), Windows via WSL, un service Onyxia, un conteneur...
# Usage :
#   - depuis le dépôt cloné :   bash init.sh
#   - sans le dépôt :           curl -fsSL https://raw.githubusercontent.com/Auracontent/auracontent/main/init.sh | bash
#   - Onyxia :                  URL "raw" ci-dessus dans l'onglet Init du service
# Réglages facultatifs :
#   AURACONTENT_DIR (où cloner), AURACONTENT_REPO_URL (un fork), DEV=1 (outils de test/lint), SKIP_CLAUDE=1 (sans Claude Code)
set -euo pipefail

REPO_URL="${AURACONTENT_REPO_URL:-https://github.com/Auracontent/auracontent.git}"
DEFAULT_PACKAGES="ffmpeg fonts-dejavu-core"
say() { printf '%s\n' "$*"; }

# ---------- 0. Où est le dépôt ? ----------
# lancé depuis le dépôt -> on reste là ; sinon AURACONTENT_DIR, sinon le dossier de travail Onyxia, sinon ./auracontent
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2> /dev/null && pwd || pwd)"
if [ -n "${AURACONTENT_DIR:-}" ]; then REPO_DIR="$AURACONTENT_DIR"
elif [ -f "$HERE/pyproject.toml" ] && [ -d "$HERE/auracontent" ]; then REPO_DIR="$HERE"
elif [ -d /home/onyxia/work ]; then REPO_DIR=/home/onyxia/work/auracontent
else REPO_DIR="$PWD/auracontent"; fi

# ---------- 1. Quel système ? ----------
OS="$(uname -s)"; PM=none; SUDO=""
if [ "$OS" = Darwin ]; then
    if command -v brew &> /dev/null; then PM=brew; else say "❌ Installe d'abord Homebrew : https://brew.sh"; exit 1; fi
elif command -v apt-get &> /dev/null; then PM=apt
elif command -v dnf &> /dev/null; then PM=dnf
fi
if [ "$PM" != brew ] && [ "$PM" != none ] && [ "$(id -u)" -ne 0 ]; then
    if command -v sudo &> /dev/null; then SUDO=sudo; else say "⚠️  Pas de sudo : les paquets système ne seront pas installés."; PM=none; fi
fi
say "🖥️  Système : $OS · gestionnaire : $PM · dépôt : $REPO_DIR"

# ---------- 2. Le dépôt (git d'abord si besoin) ----------
if ! command -v git &> /dev/null; then
    case "$PM" in apt) $SUDO apt-get update -qq && $SUDO apt-get install -y -qq git ;; dnf) $SUDO dnf install -y -q git ;; brew) brew install git ;;
        none) say "❌ Installe git, puis relance."; exit 1 ;; esac
fi
if [ ! -f "$REPO_DIR/pyproject.toml" ]; then
    say "⬇️  Clonage de $REPO_URL"
    git clone "$REPO_URL" "$REPO_DIR"
fi
cd "$REPO_DIR"

# ---------- 3. Paquets système (packages.txt, noms Debian/Ubuntu, traduits pour les autres systèmes) ----------
if [ -f packages.txt ]; then PACKAGES=$(grep -vE '^\s*(#|$)' packages.txt | tr '\n' ' '); else PACKAGES="$DEFAULT_PACKAGES"; fi
translate() {   # $1 = gestionnaire, puis les noms Debian
    local pm=$1; shift
    for p in "$@"; do
        case "$pm:$p" in
            dnf:fonts-dejavu-core) echo dejavu-sans-fonts ;;
            brew:fonts-dejavu-core|brew:fontconfig) ;;            # macOS a déjà des polices ; DejaVu est embarquée par Pillow si besoin
            *) echo "$p" ;;
        esac
    done
}
# shellcheck disable=SC2086
LIST=$(translate "$PM" $PACKAGES | tr '\n' ' ')
say "📦 Paquets : ${LIST:-aucun}"
case "$PM" in
    # shellcheck disable=SC2086
    apt)  $SUDO apt-get update -qq && $SUDO apt-get install -y -qq $LIST curl ca-certificates ;;
    # shellcheck disable=SC2086
    dnf)  $SUDO dnf install -y -q $LIST curl ;;
    # shellcheck disable=SC2086
    brew) [ -n "$LIST" ] && brew install $LIST ;;
    none) say "   À installer à la main : $PACKAGES (+ curl)" ;;
esac
command -v ffmpeg &> /dev/null || say "⚠️  ffmpeg introuvable : le montage vidéo ne marchera pas tant qu'il n'est pas installé"

# ---------- 4. Python (uv gère lui-même la bonne version de Python) ----------
if ! command -v uv &> /dev/null; then
    say "🐍 Installation de uv..."
    if [ "$PM" = brew ]; then brew install uv
    else curl -LsSf https://astral.sh/uv/install.sh | sh || python3 -m pip install --quiet --user uv || python3 -m pip install --quiet --break-system-packages uv; fi
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi
GROUPS_ARGS="--group default --group media"; [ "${DEV:-0}" = 1 ] && GROUPS_ARGS="$GROUPS_ARGS --group dev"
uv python install 3.12
# shellcheck disable=SC2086
uv sync --locked $GROUPS_ARGS

# ---------- 5. Claude Code (facultatif : SKIP_CLAUDE=1) ----------
if [ "${SKIP_CLAUDE:-0}" != 1 ]; then
    if ! command -v claude &> /dev/null; then
        if ! command -v npm &> /dev/null; then
            case "$PM" in apt) $SUDO apt-get install -y -qq nodejs npm ;; dnf) $SUDO dnf install -y -q nodejs npm ;; brew) brew install node ;; none) ;; esac
        fi
        if command -v npm &> /dev/null; then
            say "🤖 Installation du CLI Claude Code..."
            npm install -g @anthropic-ai/claude-code 2> /dev/null || $SUDO npm install -g @anthropic-ai/claude-code || say "⚠️  Claude Code non installé"
        else say "⚠️  npm introuvable : Claude Code non installé (https://nodejs.org)"; fi
    fi
    if command -v code-server &> /dev/null; then
        say "🧩 Installation de l'extension VS Code Claude Code..."
        code-server --install-extension anthropic.claude-code --force > /dev/null || true
    fi
fi

# ---------- 6. Secrets (Vault, variables d'environnement ou fichier .env non versionné) ----------
if [ ! -f .env ] && [ -f .env.example ]; then cp .env.example .env; say "📝 .env créé depuis .env.example : remplis tes clés dedans"; fi
if [ -f .env ]; then set -a; . ./.env; set +a; fi
if [ -z "${GEMINI_API_KEY:-}${GROQ_API_KEY:-}${OPENROUTER_API_KEY:-}" ]; then
    say "⚠️  Aucune clé de modèle de langage : il en faut au moins une (GEMINI_API_KEY, GROQ_API_KEY ou OPENROUTER_API_KEY)"
fi
for var in GEMINI_API_KEY GROQ_API_KEY OPENROUTER_API_KEY PEXELS_API_KEY PIXABAY_API_KEY WIKIMEDIA_CONTACT HF_TOKEN; do
    if [ -z "${!var:-}" ]; then say "ℹ️  $var absent (ajoute-le dans Vault ou .env)"; fi
done

say "✅ Environnement prêt dans $REPO_DIR — vérifier : uv run python -m auracontent.cli.doctor"
