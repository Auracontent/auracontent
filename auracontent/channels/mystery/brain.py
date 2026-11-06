import os
from pathlib import Path
from core.base_brain import BaseBrain


class MysteryBrain(BaseBrain):
    channel_name = "mystery"

    def _load_prompt(self, prompt_filename):
        """
        Lit le fichier Markdown spécifique à la chaîne.
        Idéalement, cette méthode devrait être dans BaseBrain pour que 
        CapitalSimpleBrain et MimoluneBrain en profitent automatiquement.
        """
        base_dir = Path(__file__).parent.parent  # Ajuste selon l'arborescence exacte
        filepath = base_dir / "channels" / self.channel_name / "prompts" / prompt_filename
        
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return f.read().strip()
        except FileNotFoundError:
            print(f"⚠️ Fichier prompt introuvable : {filepath}")
            return ""

    def build_script_prompt(self, topic, scene_count, chosen_hook, grounding_block, correction_feedback=""):
        # 1. Chargement des instructions depuis les fichiers .md
        system_msg = self._load_prompt("system.md")
        script_template = self._load_prompt("scripts.md")

        # 2. Remplacement sécurisé des variables (évite .format() si ton Markdown contient des accolades JSON {})
        user_msg = script_template.replace("{topic}", str(topic)) \
                                  .replace("{scene_count}", str(scene_count)) \
                                  .replace("{chosen_hook}", str(chosen_hook)) \
                                  .replace("{grounding_block}", str(grounding_block))

        # 3. Ajout du feedback de correction si c'est un retry (fact-checking échoué)
        if correction_feedback:
            user_msg += f"\n\n{correction_feedback}"

        return [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg}
        ]

    def check_script_logic(self, topic, data):
        # Appel du WikidataChecker et du LLM pour le fact-checking
        issues = []
        
        # Exemple d'intégration de ta logique de vérification
        geo_issues = self._check_wikidata_locations(data.get("scenes", []))
        if geo_issues:
            issues.extend(geo_issues)
            
        return issues
    
    def build_title_vars(cfg, used_topics, stats_text=""):
    b = cfg["brain"]

    # région et catégorie : rotation, hors des dernières utilisées
    last_regions = load_last_regions(n=b["region_lookback"])
    region = random.choice([r for r in b["regions"] if r not in last_regions] or b["regions"])

    last_cats = load_last_categories(n=2)
    category = random.choice([c for c in b["theme_categories"] if c not in last_cats] or b["theme_categories"])

    # ban temporaire du champ lexical sur-représenté
    recent = " ".join(used_topics[-8:]).lower()
    ban_hits = sum(recent.count(w) for w in b["banned_if_recent"])
    ban_block = ""
    if ban_hits >= 2:
        ban_block = ("INTERDICTION TEMPORAIRE STRICTE : ces concepts ont été trop utilisés récemment : "
                     + ", ".join(b["banned_if_recent"]) + ". N'utilise AUCUN de ces mots ni concepts.")

    used_block = ""
    if used_topics:
        used_block = ("SUJETS DÉJÀ TRAITÉS (propose un univers, un vocabulaire, un format et une région "
                      "radicalement différents) :\n- " + "\n- ".join(used_topics[-30:]))

    return {
        "forced_region": region, "forced_category": category,
        "ban_block": ban_block, "stats_block": stats_text, "used_topics_block": used_block,
    }, region, category, ban_hits