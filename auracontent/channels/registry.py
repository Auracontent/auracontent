from auracontent.channels.mystery.brain import MysteryBrain

# Chaque chaîne : un Brain (sous-classe de BaseBrain) + config/channels/<nom>.yaml.
# Finance : à réactiver quand channels/finance/brain.py (FinanceBrain) existera.
CHANNEL_REGISTRY = {
    "mystery": MysteryBrain,
}
