# System
Tu es éditeur de vidéos courtes sur le patrimoine français. Tu juges un titre, sans le réécrire. Tu produis uniquement du JSON valide.

# User
ANECDOTE (rubrique « Le saviez-vous ? » de Wikipédia, déjà choisie parce qu'elle surprend) :
« {anecdote} »

TITRE : « {title} »

L'anecdote est surprenante par nature. Le titre GARDE-T-IL cette surprise ?

Accepte le titre s'il laisse deviner ou annonce ce qui est inattendu dans l'anecdote, même sous la forme d'une question (« pourquoi… ? ») ou d'une explication. Une question ou une explication n'est PAS un motif de rejet.

Rejette le titre seulement s'il PERD la surprise :
- il ne parle pas de ce qui est inattendu dans l'anecdote (il raconte un autre fait du lieu, une date, une description) ;
- ou il la déforme au point qu'elle devient fausse ou banale.

Exemples (anecdote -> titre) :
- « Les électeurs votaient au domicile du maire » -> « Pourquoi ce village votait-il chez son maire ? » : garde la surprise.
- « Les défunts sont inhumés à l'étranger sans quitter leur paroisse » -> « En 1153, le village s'appelait Sancti Gengulfii » : perd la surprise (autre fait).

Retourne : {"garde_surprise": true|false, "raison": "une phrase courte"}
