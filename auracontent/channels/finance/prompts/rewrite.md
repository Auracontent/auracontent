# System
Tu corriges un script de vidéo courte de pédagogie financière déjà presque prêt. Tu ne réécris QUE ce qu'on te demande, en respectant toutes les règles du script. Tu produis uniquement du JSON valide, sans texte autour.

# User
SCRIPT ACTUEL (les autres scènes sont validées et ne changent pas) :
{script}

À RÉÉCRIRE, avec la consigne précise de chacun :
{instructions}

Garde le rôle de chaque scène, ses chiffres exacts et la suite du récit avec les scènes voisines.

RETOURNE uniquement les éléments demandés :
{"scenes": [{"id": <numéro>, "text": "<nouveau texte>"}], "on_screen_title": "<seulement si demandé>", "closing_cta": "<seulement si demandé>", "title": "<seulement si demandé>"}
