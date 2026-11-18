"""Refonte V2 de Capital Simple : moteur de réalisation (finance uniquement, opt-in).

S'appuie sur le moteur linework (Pillow + FFmpeg) sans le modifier :
- easing.py   : courbes d'accélération par image clé (« ease » sur la clé d'arrivée) ;
- props.py    : objets du quotidien dessinés par le code, dans le style trait à la main ;
- captions.py : minutage des mots (Edge TTS WordBoundary, ou estimation) et sous-titres mot par mot (ASS) ;
- director.py : peintre V2 (caméra, easing), rendu des plans, transitions et assemblage final.
"""
