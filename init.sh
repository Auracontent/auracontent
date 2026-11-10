#!/usr/bin/env bash
# Script d'initialisation d'un service Onyxia pour AuraContent.
# Usage :
#   - à la main :    bash init.sh
#   - automatique :  URL "raw" GitHub de ce fichier dans l'onglet Init du service Onyxia
set -euo pipefail

REPO_URL="${AURACONTENT_REPO_URL:-}"   # optionnel : URL du dépôt à cloner s'il est absent
REPO_DIR="${AURACONTENT_DIR:-/home/onyxia/work/auracontent_v2}"
DEFAULT_PACKAGES="ffmpeg fonts-dejavu-core"

# 1. Récupérer le dépôt si besoin
if [ ! -d "$REPO_DIR" ] && [ -n "$REPO_URL" ]; then
    git clone "$REPO_URL" "$REPO_DIR"
fi

# 2. Paquets système (packages.txt si présent, sinon liste par défaut)
if [ -f "$REPO_DIR/packages.txt" ]; then
    PACKAGES=$(grep -vE '^\s*(#|$)' "$REPO_DIR/packages.txt" | tr '\n' ' ')
else
    PACKAGES="$DEFAULT_PACKAGES"
fi
echo "📦 Installation : $PACKAGES"
sudo apt-get update -qq
# shellcheck disable=SC2086
sudo apt-get install -y -qq $PACKAGES

# 3. Dépendances Python
if [ -f "$REPO_DIR/pyproject.toml" ]; then
    cd "$REPO_DIR"
    uv sync --locked --group default --group media
fi

# 4. Vérification des secrets (injectés par Vault ou lus depuis .env)
for var in GEMINI_API_KEY GROQ_API_KEY OPENROUTER_API_KEY PEXELS_API_KEY PIXABAY_API_KEY WIKIMEDIA_CONTACT; do
    if [ -z "${!var:-}" ]; then
        echo "⚠️  $var absent (ajoute-le dans Vault ou .env)"
    fi
done

echo "✅ Environnement prêt"
